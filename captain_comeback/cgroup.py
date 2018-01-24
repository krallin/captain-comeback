# coding:utf-8
import os
import logging

import linuxfd
import psutil

from captain_comeback.restart.messages import (RestartRequestedMessage,
                                               MemoryPressureMessage)

logger = logging.getLogger()


class Cgroup(object):
    def __init__(self, path):
        self.path = path
        self.oom_control = None
        self.event_oom = None
        self.event_pressure = None

    def name(self):
        return self.path.split("/")[-1]

    def open(self):
        e = "{0} is already open".format(self.name())
        assert self.oom_control is None, e
        assert self.event_oom is None, e
        assert self.event_pressure is None, e

        # TODO: CLOEXEC?
        logger.debug("%s: open", self.name())
        self.oom_control = open(self._oom_control_file_path(), "r")
        self.event_oom = linuxfd.eventfd(initval=0, nonBlocking=True)
        logger.info("%s: event_oom=%d", self.name(), self.event_oom.fileno())

        oom_control_req = "{0} {1}\n".format(
            self.event_oom.fileno(),
            self.oom_control.fileno()
        )
        with open(self._evt_control_file_path(), "a") as evt_control:
            evt_control.write(oom_control_req)

        self.memory_pressure = open(self._memory_pressure_file_path(), "r")
        self.event_pressure = linuxfd.eventfd(initval=0, nonBlocking=True)
        logger.info("%s: event_pressure=%d", self.name(), self.event_pressure.fileno())

        memory_pressure_req = "{0} {1} critical\n".format(
            self.event_pressure.fileno(),
            self.memory_pressure.fileno()
        )
        with open(self._evt_control_file_path(), "a") as evt_control:
            evt_control.write(memory_pressure_req)

    def close(self):
        e = "{0} is already closed".format(self.name())
        assert self.oom_control is not None, e
        assert self.event_oom is not None, e
        assert self.event_pressure is not None, e

        logger.debug("%s: close", self.name())

        self.oom_control.close()
        self.oom_control = None

        os.close(self.event_oom.fileno())
        self.event_oom = None

        self.memory_pressure.close()
        self.memory_pressure = None

        os.close(self.event_pressure.fileno())
        self.event_pressure = None

    def event_fds(self):
        return [self.event_oom.fileno(), self.event_pressure.fileno()]

    def on_oom_killer_enabled(self, _job_queue):
        memory_limit = self.memory_limit_in_bytes()
        if (memory_limit < 0) or (memory_limit > 10**15):
            # Memory is unconstrained for this container; don't enable manual
            # OOM handling (note: in practice the memory limit is usually a
            # huge number when unconstrained, but on the other hand -1 is what
            # you write to the file. So, we check for both just to be safe.
            return

        logger.info("%s: set oom_kill_disable = 1", self.name())
        with open(self._oom_control_file_path(), "w") as f:
            f.write("1\n")

    def on_oom_event(self, job_queue):
        logger.warning("%s: under_oom", self.name())

        try:
            memory_stat_lines = self.memory_stat_lines()
        except EnvironmentError as e:
            logger.warning("%s: failed to read memory stat: %s", self.name(), e)
        else:
            for l in memory_stat_lines:
                logger.info("%s: %s", self.name(), l)

        job_queue.put(RestartRequestedMessage(self))

    def wakeup(self, job_queue, fd, raise_for_stale=False):
        logger.debug("%s: wakeup (%s)", self.name(), str(fd or "n/a"))

        # Woke up due to OOM pressure.
        if fd == self.event_pressure.fileno():
            try:
                usage = self.memory_usage_in_bytes()
                limit = self.memory_limit_in_bytes()
                logger.warning(
                    "%s: under_pressure %.2f (%d / %d)",
                    self.name(),
                    float(usage) / float(limit),
                    usage,
                    limit
                )
            except EnvironmentError:
                logger.warning(
                    "%s: under_pressure ? (? / ?)",
                    self.name()
                )

            job_queue.put(MemoryPressureMessage(self))

            return

        # Regular wakeup or oom event wakeup: we check the oom_control_status.
        try:
            oom_control_status = self.oom_control_status()

            if oom_control_status["oom_kill_disable"] == "0":
                self.on_oom_killer_enabled(job_queue)

            if oom_control_status["under_oom"] == "1":
                self.on_oom_event(job_queue)
        except EnvironmentError:
            logger.warning("%s: cgroup is stale", self.name())
            if raise_for_stale:
                raise
            return

    def oom_control_status(self):
        self.oom_control.seek(0)
        lines = self.oom_control.readlines()
        return dict([entry.strip().split(' ') for entry in lines])

    def memory_usage_in_bytes(self):
        with open(self._memory_usage_file_path(), "r") as f:
            return int(f.read())

    def memory_limit_in_bytes(self):
        with open(self._memory_limit_file_path(), "r") as f:
            return int(f.read())

    def set_memory_limit_in_bytes(self, new_limit):
        with open(self._memory_limit_file_path(), "w") as f:
            f.write(str(new_limit))
            f.write("\n")

    def pids(self):
        with open(self._procs_file_path()) as f:
            return set(int(t) for t in f.readlines())

    def ps_table(self):
        # Take a snapshot of the processes in this cgroup, which will be usable
        # after the cgroup exits.
        out = []
        for pid in self.pids():
            try:
                proc = psutil.Process(pid)
                out.append(proc.as_dict(ad_value=''))
            except psutil.NoSuchProcess:
                # Process has already exited
                pass
        return out

    def memory_stat_lines(self):
        with open(self._memory_stat_file_path()) as f:
            return [l.strip() for l in f.readlines()]

    def _oom_control_file_path(self):
        return os.path.join(self.path, "memory.oom_control")

    def _evt_control_file_path(self):
        return os.path.join(self.path, "cgroup.event_control")

    def _memory_pressure_file_path(self):
        return os.path.join(self.path, "memory.pressure_level")

    def _memory_usage_file_path(self):
        return os.path.join(self.path, "memory.usage_in_bytes")

    def _memory_limit_file_path(self):
        return os.path.join(self.path, "memory.limit_in_bytes")

    def _procs_file_path(self):
        return os.path.join(self.path, "cgroup.procs")

    def _memory_stat_file_path(self):
        return os.path.join(self.path, "memory.stat")
