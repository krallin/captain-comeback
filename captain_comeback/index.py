# coding:utf-8
import os
import logging
import select

from captain_comeback.cgroup import Cgroup
from captain_comeback.activity.messages import (NewCgroupMessage,
                                                StaleCgroupMessage)

logger = logging.getLogger()


class CgroupIndex(object):
    def __init__(self, root_cg_path, job_queue, activity_queue):
        self.root_cg_path = root_cg_path
        self.job_queue = job_queue
        self.activity_queue = activity_queue
        self.epl = None
        self._efd_hash = {}
        self._path_hash = {}

    def register(self, cg):
        logger.info("%s: registering", cg.name())

        for fd in cg.event_fds():
            self._efd_hash[fd] = cg
        self._path_hash[cg.path] = cg
        for fd in cg.event_fds():
            self.epl.register(fd, select.EPOLLIN)
        self.activity_queue.put(NewCgroupMessage(cg))

    def deregister(self, cg):
        logger.info("%s: deregistering", cg.name())
        self.activity_queue.put(StaleCgroupMessage(cg))
        for fd in cg.event_fds():
            self.epl.unregister(fd)
        self._path_hash.pop(cg.path)
        for fd in cg.event_fds():
            self._efd_hash.pop(fd)

    def sync(self):
        logger.debug("syncing cgroups")

        # Sync all monitors with disk, and deregister stale ones. It's
        # important to actually *wakeup* monitors here, so as to ensure we
        # don't race with Docker when it creates a cgroup (which could result
        # in us not seeing the memory limit and therefore not disabling the OOM
        # killer).
        for cg in list(self._path_hash.values()):
            try:
                cg.wakeup(self.job_queue, None, raise_for_stale=True)
            except EnvironmentError:
                self.deregister(cg)
                cg.close()

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

            # This a new CG, Register and wake it up immediately after in case
            # there already is some handling to do (typically: disabling the
            # OOM killer).
            cg = Cgroup(path)

            try:
                cg.open()
            except EnvironmentError as e:
                # CG exited before we had a chance to register it. That's OK.
                logger.warning("%s: error opening new cg: %s", cg.name(), e)
            else:
                self.register(cg)
                cg.wakeup(self.job_queue, None)

    def poll(self, timeout):
        events = self.epl.poll(timeout)
        for fd, event in events:
            if not event & select.EPOLLIN:
                raise Exception("Unexpected event: {0}".format(event))

            # Handle event
            cg = self._efd_hash[fd]
            cg.wakeup(self.job_queue, fd)

            # Acknowledge so we don't get notified again. We need 8 bytes.
            # http://man7.org/linux/man-pages/man2/read.2.html
            os.read(fd, 8)

    def open(self):
        assert self.epl is None, "already open"
        self.epl = select.epoll()
        logger.info("ready to sync")

    def close(self):
        assert self.epl is not None, "already closed"

        for cg in list(self._path_hash.values()):
            self.deregister(cg)
            cg.close()

        self.epl.close()
        self.epl = None
