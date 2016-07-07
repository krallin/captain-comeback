# coding:utf-8
import os
import logging
import linuxfd

from captain_comeback.restart.messages import RestartRequestedMessage

logger = logging.getLogger()


class Cgroup(object):
    def __init__(self, path):
        self.path = path
        self.oom_control = None
        self.event = None

    def name(self):
        return self.path.split("/")[-1]

    def open(self):
        e = "{0} is already open".format(self.name())
        assert self.oom_control is None, e
        assert self.event is None, e

        # TODO: CLOEXEC?
        logger.debug("%s: open", self.name())
        self.oom_control = open(self._oom_control_file_path(), "r")
        self.event = linuxfd.eventfd(initval=0, nonBlocking=True)

        req = "{0} {1}\n".format(self.event_fileno(),
                                 self.oom_control.fileno())
        with open(self._evt_control_file_path(), "w") as evt_control:
            evt_control.write(req)

    def close(self):
        e = "{0} is already closed".format(self.name())
        assert self.oom_control is not None, e
        assert self.event is not None, e

        logger.debug("%s: close", self.name())

        self.oom_control.close()
        self.oom_control = None

        os.close(self.event.fileno())
        self.event = None

    def event_fileno(self):
        return self.event.fileno()

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
        job_queue.put(RestartRequestedMessage(self))

    def wakeup(self, job_queue, raise_for_stale=False):
        logger.debug("%s: wakeup", self.name())

        try:
            oom_control_status = self.oom_control_status()
        except EnvironmentError:
            logger.warning("%s: cgroup is stale", self.name())
            if raise_for_stale:
                raise
            return

        if oom_control_status["oom_kill_disable"] == "0":
            self.on_oom_killer_enabled(job_queue)

        if oom_control_status["under_oom"] == "1":
            self.on_oom_event(job_queue)

    def oom_control_status(self):
        self.oom_control.seek(0)
        lines = self.oom_control.readlines()
        return dict([entry.strip().split(' ') for entry in lines])

    def memory_limit_in_bytes(self):
        with open(self._memory_limit_file_path(), "r") as f:
            return int(f.read())

    def set_memory_limit_in_bytes(self, new_limit):
        with open(self._memory_limit_file_path(), "w") as f:
            f.write(str(new_limit))
            f.write("\n")

    def pids(self):
        with open(self._tasks_file_path()) as f:
            return [int(t) for t in f.readlines()]

    def _oom_control_file_path(self):
        return os.path.join(self.path, "memory.oom_control")

    def _evt_control_file_path(self):
        return os.path.join(self.path, "cgroup.event_control")

    def _memory_limit_file_path(self):
        return os.path.join(self.path, "memory.limit_in_bytes")

    def _tasks_file_path(self):
        return os.path.join(self.path, "tasks")
