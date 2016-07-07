# coding:utf-8
import os
import logging
import select

from captain_comeback.cgroup import Cgroup

logger = logging.getLogger()


class CgroupIndex(object):
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
            except EnvironmentError:
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
            cg = Cgroup(path)
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
