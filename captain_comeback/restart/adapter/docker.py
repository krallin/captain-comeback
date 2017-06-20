import subprocess
import logging
import time

logger = logging.getLogger()

DOCKER_FATAL_ERRORS = [
    "No such container",
    "no such id",
]


def restart(cg):
    try_docker(cg, "docker", "stop", "-t", "0", cg.name())
    if not try_docker(cg, "docker", "restart", "-t", "0", cg.name()):
        raise Exception("docker restart failed")


def try_docker(cg, *command):
    retry_schedule = [0, 2, 5, 10]

    while retry_schedule:
        sleep_for = retry_schedule.pop(0)
        if sleep_for:
            logger.error("%s: wait %d seconds before retrying",
                         cg.name(), sleep_for)
            time.sleep(sleep_for)

        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        out, err = [x.decode("utf-8").strip() for x in proc.communicate()]
        ret = proc.poll()

        if ret == 0:
            return True

        logger.error("%s: failed: %s", cg.name(), str(command))
        logger.error("%s: status: %s", cg.name(), ret)
        logger.error("%s: stdout: %s", cg.name(), out)
        logger.error("%s: stderr: %s", cg.name(), err)

        if any(e in err for e in DOCKER_FATAL_ERRORS):
            logger.error("%s: fatal error: no more retries", cg.name())
            break

    logger.error("%s: failed after all retries", cg.name())
    return False
