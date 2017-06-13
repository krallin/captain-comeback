import logging

logger = logging.getLogger()


def restart(cg):
    logger.warn("%s: not restarting", cg.name())
