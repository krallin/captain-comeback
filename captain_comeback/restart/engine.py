# coding:utf-8
import logging
import threading
import subprocess

import psutil

from captain_comeback.restart.messages import (RestartRequestedMessage,
                                               RestartCompleteMessage)


logger = logging.getLogger()


class RestartEngine(object):
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
        logger.info("ready to restart containers")
        while True:
            message = self.queue.get()
            if isinstance(message, RestartRequestedMessage):
                self._handle_restart_requested(message.cg)
            elif isinstance(message, RestartCompleteMessage):
                self._handle_restart_complete(message.cg)
            else:
                raise Exception("Unexpected message: {0}".format(message))


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
