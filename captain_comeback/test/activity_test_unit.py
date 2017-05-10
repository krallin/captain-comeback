# coding:utf-8
import os
import unittest
import tempfile
import shutil
from six.moves import queue
from collections import namedtuple
import re
import psutil
import json

from captain_comeback.cgroup import Cgroup
from captain_comeback.activity.engine import ActivityEngine
from captain_comeback.activity.messages import (NewCgroupMessage,
                                                StaleCgroupMessage,
                                                RestartCgroupMessage,
                                                RestartTimeoutMessage,
                                                ExitMessage)


class ActivityTestUnit(unittest.TestCase):
    def setUp(self):
        self.activity_dir = tempfile.mkdtemp()
        self.q = queue.Queue()
        self.engine = ActivityEngine(self.activity_dir, self.q)

    def tearDown(self):
        shutil.rmtree(self.activity_dir)

    def test_exit(self):
        self.q.put(ExitMessage())
        self.engine.run()

    def test_new_cgroup(self):
        self.q.put(NewCgroupMessage(Cgroup("/some/foo")))
        self.q.put(ExitMessage())
        self.engine.run()
        self.assertHasLogged("foo", ["container has started"])

    def test_exit_cgroup(self):
        self.q.put(StaleCgroupMessage(Cgroup("/some/foo")))
        self.q.put(ExitMessage())
        self.engine.run()
        self.assertHasLogged("foo", ["container has exited"])

    def test_append(self):
        self.q.put(NewCgroupMessage(Cgroup("/some/foo")))
        self.q.put(StaleCgroupMessage(Cgroup("/some/foo")))
        self.q.put(ExitMessage())
        self.engine.run()
        self.assertHasLogged("foo", ["container has started",
                                     "container has exited"])

    def test_restart_cgroup(self):
        MemInfo = namedtuple('MemInfo', ["rss", "vms"])
        ps_table = [
            {
                "pid": 123,
                "ppid": 0,
                "memory_info": MemInfo(rss=1024*8, vms=1024*16),
                "cmdline": ["some", "proc"],
                "status": psutil.STATUS_STOPPED,
            },
            {
                "pid": 456,
                "ppid": 123,
                "memory_info": MemInfo(rss=1024*2, vms=1024*4),
                "cmdline": ["sh", "-c", "a && b"],
                "status": psutil.STATUS_RUNNING,
            }
        ]
        self.q.put(RestartCgroupMessage(Cgroup("/some/foo"), ps_table))
        self.q.put(ExitMessage())
        self.engine.run()
        self.assertHasLogged("foo", [
            "container exceeded its memory allocation",
            "container is restarting:",
            re.compile(r"123\s+0\s+16\s+8\s+T\s+some proc"),
            re.compile(r'456\s+123\s+4\s+2\s+R\s+sh -c "a && b"')
        ])

    def test_large_memory_value(self):
        # Newer versions of Python (e.g. 3.4) will show this value in
        # scientific notation, which isn't desirable here.
        size = 2 * 1024 * 1024 * 1024  # 2GB
        MemInfo = namedtuple('MemInfo', ["rss", "vms"])
        ps_table = [
            {
                "pid": 123,
                "ppid": 0,
                "memory_info": MemInfo(rss=size, vms=size),
                "cmdline": ["some", "proc"],
                "status": psutil.STATUS_RUNNING,
            }
        ]
        self.q.put(RestartCgroupMessage(Cgroup("/some/foo"), ps_table))
        self.q.put(ExitMessage())
        self.engine.run()
        self.assertHasLogged("foo", [
            "container exceeded its memory allocation",
            "container is restarting:",
            re.compile(r"123\s+0\s+2097152\s+2097152\s+R\s+some proc"),
        ])

    def test_restart_timeout(self):
        self.q.put(RestartTimeoutMessage(Cgroup("/some/foo"), 3))
        self.q.put(ExitMessage())
        self.engine.run()
        self.assertHasLogged("foo", [
            "container did not exit within 3 seconds grace period"
        ])

    def assertHasLogged(self, cg_name, messages):
        fname = os.path.join(self.activity_dir,
                             "{0}-json.log".format(cg_name))

        with open(fname) as f:
            for message, line in zip(messages, f):
                log = json.loads(line)["log"]
                print(log)

                if isinstance(message, str):
                    self.assertEqual(message, log)
                else:
                    # Assume it's a regexp
                    self.assertTrue(message.search(log))
