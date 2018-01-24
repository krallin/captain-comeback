# coding:utf-8


# TODO: We should pass a read-only view of the cgroup instead to ensure
# thread-safety.
class RestartRequestedMessage(object):
    def __init__(self, cg):
        self.cg = cg


class RestartCompleteMessage(object):
    def __init__(self, cg):
        self.cg = cg


class MemoryPressureMessage(object):
    def __init__(self, cg):
        self.cg = cg
