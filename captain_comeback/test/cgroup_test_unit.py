# coding:utf-8
import os
import shutil
import tempfile
import unittest
from six.moves import queue

from captain_comeback.cgroup import Cgroup

from captain_comeback.test.queue_assertion_helper import (
        QueueAssertionHelper)

class CgroupTestUnit(unittest.TestCase, QueueAssertionHelper):
    def setUp(self):
        self.mock_cg = tempfile.mkdtemp()

        self.write_oom_control()
        with open(self.cg_path("memory.pressure_level"), "w") as f:
            f.write('')

        self.monitor = Cgroup(self.mock_cg)
        self.queue = queue.Queue()

    def tearDown(self):
        shutil.rmtree(self.mock_cg)

    # Helpers

    def write_oom_control(self, oom_kill_disable="0", under_oom="0"):
        control = ["oom_kill_disable {0}".format(oom_kill_disable),
                   "under_oom {0}".format(under_oom)]

        with open(self.cg_path("memory.oom_control"), "w") as f:
            f.write("\n".join(control))
            f.write("\n")

    def write_memory_usage(self, memory_usage=12345):
        with open(self.cg_path("memory.usage_in_bytes"), "w") as f:
            f.write(str(memory_usage))
            f.write("\n")

    def write_memory_limit(self, memory_limit=9223372036854771712):
        with open(self.cg_path("memory.limit_in_bytes"), "w") as f:
            f.write(str(memory_limit))
            f.write("\n")

    def cg_path(self, path):
        return os.path.join(self.mock_cg, path)

    # Tests

    def test_open(self):
        self.write_oom_control()
        self.monitor.open()

        expected = "{0} {1}\n{2} {3} {4}\n".format(
                self.monitor.event_oom.fileno(),
                self.monitor.oom_control.fileno(),
                self.monitor.event_pressure.fileno(),
                self.monitor.memory_pressure.fileno(),
                "critical"
        )

        self.monitor.close()

        with open(self.cg_path("cgroup.event_control")) as f:
            self.assertEqual(expected, f.read())

    def test_wakeup_disable_oom_killer(self):
        self.write_oom_control()
        self.write_memory_limit(1024)

        self.monitor.open()
        self.monitor.wakeup(self.queue, None)
        self.monitor.close()

        with open(self.cg_path("memory.oom_control")) as f:
            self.assertEqual("1\n", f.read())

    def test_wakeup_oom_killer_is_disabled(self):
        self.write_oom_control(oom_kill_disable="1")
        self.write_memory_limit(1024)

        self.monitor.open()
        self.monitor.wakeup(self.queue, None)
        self.monitor.close()

        # File shoud not have been touched
        with open(self.cg_path("memory.oom_control")) as f:
            self.assertEqual("oom_kill_disable 1\n", f.readline())

    def test_wakeup_no_memory_limit(self):
        self.write_oom_control(oom_kill_disable="0")
        self.write_memory_limit()

        self.monitor.open()
        self.monitor.wakeup(self.queue, None)
        self.monitor.close()

        # File shoud not have been touched
        with open(self.cg_path("memory.oom_control")) as f:
            self.assertEqual("oom_kill_disable 0\n", f.readline())

    def test_wakeup_stale(self):
        self.write_oom_control(oom_kill_disable="0")

        self.monitor.open()

        os.close(self.monitor.oom_control.fileno())
        self.monitor.wakeup(self.queue, None)
        self.assertRaises(EnvironmentError, self.monitor.wakeup, None,
                          self.queue, raise_for_stale=True)

        # Close the other FD manually. We still need to attempt closing the
        # wrapper to avoid a resource warning.
        os.close(self.monitor.event_oom.fileno())
        try:
            self.monitor.oom_control.close()
        except EnvironmentError:
            pass

    def test_wakeup_pressure(self):
        self.monitor.open()

        self.write_memory_usage()
        self.write_memory_limit()

        self.monitor.wakeup(
            self.queue,
            self.monitor.event_pressure.fileno()
        )
        self.assertHasNoMessages(self.queue)

    def test_wakeup_pressure_stale(self):
        self.monitor.open()
        self.monitor.wakeup(
            self.queue,
            self.monitor.event_pressure.fileno()
        )
        self.assertHasNoMessages(self.queue)
