# coding:utf-8
import os
import select
import logging
import time
import sys
import argparse
import subprocess
import queue
import threading

import psutil
import linuxfd

logger = logging.getLogger()


DEFAULT_ROOT_CG = "/sys/fs/cgroup/memory/docker"
DEFAULT_SYNC_TARGET_INTERVAL = 1
DEFAULT_RESTART_GRACE_PERIOD = 10


class RestartRequestedMessage:
    def __init__(self, cg):
        self.cg = cg


class RestartCompleteMessage:
    def __init__(self, cg):
        self.cg = cg


def restart(queue, grace_period, cg):
    # Snapshot task usage
    logger.info("%s: restarting", cg.name())

    for pid in cg.pids():
        proc = psutil.Process(pid)
        logger.info("%s: task %s: %s: %s", cg.name(), pid,
                    proc.cmdline(), proc.memory_info())

    # We initiate the restart first. This increases our chances of getting a
    # successful restart by signalling a potential memory hog before we
    # allocate extra memory.
    restart_cmd = ["docker", "restart", "-t", str(grace_period), cg.name()]
    proc = subprocess.Popen(restart_cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)

    # Try and allocate 10% of extra memory to give this cgroup a chance to
    # shut down gracefully.
    # NOTE: we look at free memory (rather than available) so that we don't
    # have to e.g. free some buffers to grant this extra memory.
    memory_limit = cg.memory_limit_in_bytes()
    free_memory = psutil.virtual_memory().free
    extra = int(memory_limit / 10)  # Make parameterizable

    logger.debug("%s: memory_limit: %s, free_memory: %s, extra: %s",
                 cg.name(), memory_limit, free_memory, extra)
    if free_memory > extra:
        new_limit = memory_limit + extra
        logger.info("%s: increasing memory limit to %s", cg.name(),
                    new_limit)
        cg.set_memory_limit_in_bytes(new_limit)

    out, err = proc.communicate()
    ret = proc.poll()
    if ret != 0:
        logger.error("%s: failed to restart", cg.name())
        logger.error("%s: status: %s", cg.name(), ret)
        logger.error("%s: stdout: %s", cg.name(), out)
        logger.error("%s: stderr: %s", cg.name(), err)

    # TODO: Make this a finally?
    logger.info("%s: restart complete", cg.name())
    queue.put(RestartCompleteMessage(cg))


class ContainerRestarter:
    def __init__(self, queue, grace_period):
        self.grace_period = grace_period
        self.queue = queue
        self._running_restarts = set()

    def _handle_restart_requested(self, cg):
        if cg in self._running_restarts:
            logger.info("%s: already being restarted", cg.name())
            return
        logger.debug("%s: scheduling restart", cg.name())
        self._running_restarts.add(cg)

        threading.Thread(target=restart, name="restart-job",
                         args=(self.queue, self.grace_period, cg,)).start()

    def _handle_restart_complete(self, cg):
        logger.debug("%s: registering restart complete", cg.name())
        self._running_restarts.remove(cg)

    def run(self):
        # TODO: Exit everything when this fails
        while True:
            message = self.queue.get()
            if isinstance(message, RestartRequestedMessage):
                self._handle_restart_requested(message.cg)
            elif isinstance(message, RestartCompleteMessage):
                self._handle_restart_complete(message.cg)
            else:
                raise Exception("Unexpected message: {0}".format(message))


class CgroupMonitor:
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
            oom_control_status = self._read_oom_control_status()
        except OSError:
            logger.warning("%s: cgroup is stale", self.name())
            if raise_for_stale:
                raise
            return

        if oom_control_status["oom_kill_disable"] == "0":
            self.on_oom_killer_enabled(job_queue)

        if oom_control_status["under_oom"] == "1":
            self.on_oom_event(job_queue)

    def _read_oom_control_status(self):
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


class CgroupMonitorIndex:
    def __init__(self, root_cg_path, epl, job_queue):
        self.root_cg_path = root_cg_path
        self.epl = epl
        self.job_queue = job_queue
        self._efd_hash = {}
        self._path_hash = {}

    def register(self, cg):
        cg.open()
        self._efd_hash[cg.event_fileno()] = cg
        self._path_hash[cg.path] = cg
        self.epl.register(cg.event_fileno(), select.EPOLLIN)

    def remove(self, cg):
        self.epl.unregister(cg.event_fileno())
        self._path_hash.pop(cg.path)
        self._efd_hash.pop(cg.event_fileno())
        cg.close()

    def sync(self):
        logger.debug("syncing cgroups")

        # Sync all monitors with disk, and remove stale ones. It's important to
        # actually *wakeup* monitors here, so as to ensure we don't race with
        # Docker when it creates a cgroup (which could result in us not seeing
        # the memory limit and therefore not disabling the OOM killer).
        for cg in list(self._path_hash.values()):
            try:
                cg.wakeup(self.job_queue, raise_for_stale=True)
            except OSError:
                logger.info("%s: deregistering", cg.name())
                self.remove(cg)

        for entry in os.listdir(self.root_cg_path):
            path = os.path.join(self.root_cg_path, entry)

            # Is this a CG or just a regular file?
            if not os.path.isdir(path):
                continue

            # We're already tracking this CG. It *might* have changed between
            # our check and now, but in that case we'll catch it at the next
            # sync.
            if path in self._path_hash:
                continue

            # This a new CG, register it.
            cg = CgroupMonitor(path)
            logger.info("%s: new cgroup", cg.name())

            # Register and wake up the CG immediately after, in case there
            # already is some handling to do (typically: disabling the OOM
            # killer). To avoid race conditions, we do this after registration
            # to ensure we can deregister immediately if the cgroup just
            # exited.
            self.register(cg)
            cg.wakeup(self.job_queue)

    def poll(self, timeout):
        events = self.epl.poll(timeout)
        for efd, event in events:
            if not event & select.EPOLLIN:
                raise Exception("Unexpected event: {0}".format(event))

            # Handle event and ackownledge
            cg = self._efd_hash[efd]
            cg.wakeup(self.job_queue)
            cg.event.read()


def main(root_cg_path, sync_target_interval, restart_grace_period):
    epl = select.epoll()
    job_queue = queue.Queue()
    index = CgroupMonitorIndex(root_cg_path, epl, job_queue)

    restarter = ContainerRestarter(job_queue, restart_grace_period)
    restarter_thread = threading.Thread(target=restarter.run, name="restarter")
    restarter_thread.daemon = True
    restarter_thread.start()

    while True:
        index.sync()
        next_sync = time.time() + sync_target_interval
        while True:
            poll_timeout = next_sync - time.time()
            if poll_timeout <= 0:
                break
            logger.debug("poll with timeout: %s", poll_timeout)
            index.poll(poll_timeout)


def _pre_main(argv):
    desc = "Autorestart containers that exceed their memory allocation"
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("--root-cg",
                        default=DEFAULT_ROOT_CG,
                        help="parent cgroup (children will be monitored)")
    parser.add_argument("--sync-interval",
                        default=DEFAULT_SYNC_TARGET_INTERVAL, type=float,
                        help="target sync interval to refresh cgroups")
    parser.add_argument("--restart-grace-period",
                        default=DEFAULT_RESTART_GRACE_PERIOD, type=int,
                        help="how long to wait before sending SIGKILL")
    parser.add_argument("--debug", default=False, action='store_true',
                        help="enable debug logging")

    ns = parser.parse_args(argv[1:])

    log_level = logging.DEBUG if ns.debug else logging.INFO
    log_format = "%(asctime)-15s %(levelname)-8s %(threadName)-10s -- " \
                 "%(message)s"
    logging.basicConfig(level=log_level, format=log_format)
    logger.setLevel(log_level)

    sync_interval = ns.sync_interval
    if sync_interval < 0:
        logger.warning("invalid sync interval %s, must be > 0", sync_interval)
        sync_interval = DEFAULT_SYNC_TARGET_INTERVAL

    restart_grace_period = ns.restart_grace_period
    if restart_grace_period < 0:
        logger.warning("invalid restart grace period %s, must be > 0",
                       restart_grace_period)
        restart_grace_period = DEFAULT_RESTART_GRACE_PERIOD

    main(ns.root_cg, sync_interval, restart_grace_period)

if __name__ == "__main__":
    _pre_main(sys.argv)
