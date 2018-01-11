# coding:utf-8
import os
import time
import pwd
import grp
import subprocess
import unittest
import uuid
import resource
import logging
import random
import threading
from six.moves import queue

from captain_comeback.index import CgroupIndex
from captain_comeback.cgroup import Cgroup
from captain_comeback.restart.messages import RestartRequestedMessage
from captain_comeback.activity.messages import (NewCgroupMessage,
                                                StaleCgroupMessage)
from captain_comeback.activity.status import PROC_STATUSES_RAW

from captain_comeback.test.queue_assertion_helper import (
        QueueAssertionHelper)


logger = logging.getLogger("TEST")


HOG = os.path.join(os.path.dirname(__file__), '..', '..', 'integration', 'hog')
DEVNULL = open(os.devnull, 'w')
CG_PARENT_BASE = "captain-comeback-integration"
CG_ROOT_DIR = "/sys/fs/cgroup/memory"


def descriptor_from_cg_path(path):
    return "memory:{0}".format(path.replace(CG_ROOT_DIR, ""))


def create_cg(name, parent_path=None):
    parent_path = parent_path or CG_ROOT_DIR
    path = "{0}/{1}".format(parent_path, name)

    logger.info("create_cg: %s", path)

    user_name = pwd.getpwuid(os.geteuid()).pw_name
    group_name = grp.getgrgid(os.getegid()).gr_name
    user_spec = "{0}:{1}".format(user_name, group_name)

    subprocess.check_call(["sudo", "cgcreate", "-g",
                           descriptor_from_cg_path(path),
                           "-t", user_spec, "-a", user_spec])

    return path


def delete_cg(path, recursive=False):
    logger.info("delete_cg: %s", path)

    command = ["sudo", "cgdelete", "-g", descriptor_from_cg_path(path)]
    if recursive:
        command.append("-r")
    subprocess.call(command)


def quick_create_cg(name, parent_path):
    # sudo + cgcreate is way too slow to trigger a race here, so we
    # sacrifice test portability (these must run as root) for
    # speed.
    path = os.path.join(parent_path, name)
    logger.debug("quick_create_cg: make %s", name)
    os.mkdir(path)
    return path


def quick_delete_cg(name):
    logger.debug("quick_del_cg: del %s", name)
    os.rmdir(name)


def create_random_cg(parent_path=None):
    return create_cg(str(uuid.uuid4()), parent_path)


def set_memlimit(path):
    logger.info("set memlimit in: %s", path)
    cg = Cgroup(path)
    cg.set_memory_limit_in_bytes(1024 * 1024 * 128)  # 128 MB


def trigger_oom(path):
    logger.info("trigger oom in: %s", path)

    subprocess.Popen(
        ["sudo", "cgexec", "-g", descriptor_from_cg_path(path), HOG],
        stdout=DEVNULL, stderr=DEVNULL
    )


class CgroupTestIntegration(unittest.TestCase, QueueAssertionHelper):
    def setUp(self):
        name = "{0}-{1}".format(CG_PARENT_BASE, str(uuid.uuid4()))
        self.parent_cg_path = create_cg(name)

    def tearDown(self):
        # Kill every task in subgroups to be safe, then recursively tear down
        # everything.
        try:
            pids_cmd = "cat {0}/*/cgroup.procs".format(self.parent_cg_path)
            pids = subprocess.check_output(pids_cmd, shell=True,
                                           stderr=subprocess.PIPE).split()
        except subprocess.CalledProcessError:
            # No pids
            pass
        else:
            for pid in pids:
                logger.warn("cleanup proc: %s", str(pid))
                subprocess.check_call(["sudo", "kill", "-KILL", pid])

        logger.info("cleanup cg: %s", self.parent_cg_path)
        delete_cg(self.parent_cg_path, recursive=True)

    def test_index_sync(self):
        cg_path = create_random_cg(self.parent_cg_path)

        q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, q, q)
        index.open()
        index.sync()

        # Check that the CG was added to the path hash
        self.assertEqual(1, len(index._path_hash))

        # And that we have 2 EFDs
        self.assertEqual(2, len(index._efd_hash))

        # Check that the CG was registered (adding it again will cause an
        # error)
        cg = index._path_hash[cg_path]
        self.assertRaises(EnvironmentError, index.epl.register,
                          cg.event_oom.fileno())
        self.assertRaises(EnvironmentError, index.epl.register,
                          cg.event_pressure.fileno())

        index.close()

    def test_index_sync_many(self):
        cg_paths = [create_random_cg(self.parent_cg_path) for _ in range(10)]

        q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, q, q)
        index.open()
        index.sync()

        while cg_paths:
            self.assertEqual(len(cg_paths), len(index._path_hash))

            path = cg_paths.pop()
            self.assertIn(path, index._path_hash)

            delete_cg(path)
            index.sync()

            self.assertEqual(len(cg_paths), len(index._path_hash))
            self.assertNotIn(path, index._path_hash)

        index.close()

    def test_wakeup_on_sync(self):
        cg_path = create_random_cg(self.parent_cg_path)

        cg = Cgroup(cg_path)
        cg.open()
        cg.set_memory_limit_in_bytes(1024)
        self.assertEqual("0", cg.oom_control_status()["oom_kill_disable"])

        q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, q, q)
        index.open()
        index.sync()
        index.close()

        self.assertEqual("1", cg.oom_control_status()["oom_kill_disable"])
        cg.close()

    def test_index_poll(self):
        cg_path = create_random_cg(self.parent_cg_path)

        job_q = queue.Queue()
        activity_q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, job_q, activity_q)
        index.open()

        self.assertHasNoMessages(activity_q)
        index.sync()

        self.assertHasMessageForCg(activity_q, NewCgroupMessage, cg_path)

        set_memlimit(cg_path)
        index.sync()
        self.assertHasNoMessages(job_q)

        trigger_oom(cg_path)
        index.poll(10)

        # We might receive a few pressure notifications before we finally get
        # the OOM event. So, wait for the message 100 times.
        for _ in self.assertEvnetuallyHasMessageForCg(
            job_q, RestartRequestedMessage, cg_path
        ):
            index.poll(1)

        index.close()

    def test_index_poll_many(self):
        for _ in range(10):
            create_random_cg(self.parent_cg_path)
        cg_path = create_random_cg(self.parent_cg_path)

        job_q = queue.Queue()
        activity_q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, job_q, activity_q)
        index.open()

        self.assertHasNoMessages(activity_q)
        index.sync()
        for _ in range(11):
            self.assertHasMessageForCg(activity_q, NewCgroupMessage,
                                       self.ANY_CG)
        self.assertHasNoMessages(activity_q)

        set_memlimit(cg_path)
        index.sync()
        self.assertHasNoMessages(job_q)

        trigger_oom(cg_path)
        index.poll(10)

        # We might receive a few pressure notifications before we finally get
        # the OOM event. So, wait for the message 100 times.
        for _ in self.assertEvnetuallyHasMessageForCg(
            job_q, RestartRequestedMessage, cg_path
        ):
            index.poll(1)

        index.close()

    def test_index_poll_close(self):
        cg_path = create_random_cg(self.parent_cg_path)

        job_q = queue.Queue()
        activity_q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, job_q, activity_q)
        index.open()

        self.assertHasNoMessages(activity_q)
        index.sync()
        self.assertHasMessageForCg(activity_q, NewCgroupMessage, cg_path)

        delete_cg(cg_path)
        index.sync()
        self.assertHasMessageForCg(activity_q, StaleCgroupMessage, cg_path)

        index.close()

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_index_leak(self):
        job_q = queue.Queue()
        activity_q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, job_q, activity_q)

        fd_dir = os.path.join('/proc', str(os.getpid()), 'fd')

        fd_initial = len(os.listdir(fd_dir))
        logger.debug("fd_initial=%d", fd_initial)

        index.open()

        fd_intermediate = len(os.listdir(fd_dir))
        logger.debug("fd_intermediate=%d", fd_intermediate)

        for _ in range(100):
            fd0 = len(os.listdir(fd_dir))

            cgs = [
                quick_create_cg(str(uuid.uuid4()), self.parent_cg_path)
                for _ in range(100)
            ]

            index.sync()
            fd1 = len(os.listdir(fd_dir))

            index.sync()
            fd2 = len(os.listdir(fd_dir))

            logger.debug("fd0=%d, fd1=%d, fd2=%d", fd0, fd1, fd2)

            self.assertEqual(fd0, fd_intermediate)
            self.assertEqual(fd1, fd2)

            for cg in cgs:
                quick_delete_cg(cg)

            index.sync()

        index.close()
        fd_final = len(os.listdir(fd_dir))
        logger.debug("fd_final=%d", fd_final)

        self.assertEqual(fd_final, fd_initial)

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_index_race(self):
        ready_q = queue.Queue()
        exit_q = queue.Queue()

        cg_count = 100
        cg_cycle = 10
        index_syncs = 50

        file_limit = cg_count * 5
        resource.setrlimit(resource.RLIMIT_NOFILE, (file_limit, file_limit))

        def racer():
            cgs = [
                quick_create_cg(str(uuid.uuid4()), self.parent_cg_path)
                for _ in range(cg_count)
            ]

            ready_q.put(None)

            i = 0

            while True:
                i += 1

                try:
                    exit_q.get_nowait()
                except queue.Empty:
                    pass
                else:
                    break

                logger.debug("racer: shuffle (%d)", i)
                random.shuffle(cgs)

                logger.debug("racer: split (%d)", i)
                del_cgs, keep_cgs = cgs[:cg_cycle], cgs[cg_cycle:]

                logger.debug("racer: delete (%d)", i)
                for cg in del_cgs:
                    quick_delete_cg(cg)

                logger.debug("racer: remake (%d)", i)

                cgs = keep_cgs + [
                    quick_create_cg(str(uuid.uuid4()), self.parent_cg_path)
                    for _ in range(cg_cycle)
                ]

                logger.debug("racer: done (%d)", i)

            for cg in cgs:
                quick_delete_cg(cg)

        t = threading.Thread(target=racer)
        t.start()

        job_q = queue.Queue()
        activity_q = queue.Queue()
        index = CgroupIndex(self.parent_cg_path, job_q, activity_q)
        index.open()

        ready_q.get(timeout=5)

        try:
            for _ in range(index_syncs):
                index.sync()
            index.close()
        except Exception:
            logger.error("sync errorred")  # Make logs more usable
            raise
        finally:
            exit_q.put(None)
            t.join(5)

    def test_open_close(self):
        cg_path = create_random_cg(self.parent_cg_path)

        cg = Cgroup(cg_path)
        cg.open()
        cg.close()

    def test_set_memory_limit(self):
        cg_path = create_random_cg(self.parent_cg_path)

        # Memory limits are enforced as a page size count, so we have to make
        # sure we choose a number that's properly aligned.
        limit = 123 * resource.getpagesize()
        cg = Cgroup(cg_path)
        cg.set_memory_limit_in_bytes(limit)
        self.assertEqual(limit, cg.memory_limit_in_bytes())

    def test_disable_oom_killer(self):
        cg_path = create_random_cg(self.parent_cg_path)

        cg = Cgroup(cg_path)
        cg.open()
        cg.wakeup(queue.Queue(), None)
        self.assertEqual("0", cg.oom_control_status()["oom_kill_disable"])

        # The OOM Killer should be disabled if there is a task limit
        cg.set_memory_limit_in_bytes(1024)
        cg.wakeup(queue.Queue(), None)
        self.assertEqual("1", cg.oom_control_status()["oom_kill_disable"])

        cg.close()

    def test_stale_cgroup(self):
        cg_path = create_random_cg(self.parent_cg_path)

        cg = Cgroup(cg_path)
        cg.open()

        delete_cg(cg_path)

        q = queue.Queue()
        cg.wakeup(q, None)
        self.assertRaises(EnvironmentError, cg.wakeup, q, None, raise_for_stale=True)

        cg.close()

    def test_reopen(self):
        cg_path = create_random_cg(self.parent_cg_path)

        cg = Cgroup(cg_path)
        cg.open()
        self.assertRaises(AssertionError, cg.open)
        cg.close()

    def test_reclose(self):
        cg_path = create_random_cg(self.parent_cg_path)

        cg = Cgroup(cg_path)
        cg.open()
        cg.close()
        self.assertRaises(AssertionError, cg.close)

    def test_trigger_restart(self):
        cg_path = create_random_cg(self.parent_cg_path)

        q = queue.Queue()
        cg = Cgroup(cg_path)
        cg.open()

        cg.wakeup(q, None)
        self.assertHasNoMessages(q)

        set_memlimit(cg_path)
        cg.wakeup(q, None)
        self.assertHasNoMessages(q)

        trigger_oom(cg_path)

        # The test program should fill 128 MB rather fast; give it 10s
        for _ in range(100):
            cg.wakeup(q, None)
            try:
                msg = q.get_nowait()
            except queue.Empty:
                time.sleep(0.1)
                continue
            self.assertIsInstance(msg, RestartRequestedMessage)
            self.assertEqual(cg, msg.cg)
            break
        else:
            raise Exception("Queue never received a message!")

        cg.close()

    def test_ps_table(self):
        cg_path = create_random_cg(self.parent_cg_path)
        multithead_sleep = "\n".join([
            'import time, threading',
            't = threading.Thread(target=time.sleep, args=(10,))',
            't.start()',
            't.join()'
        ])
        subprocess.Popen(["sudo", "cgexec", "-g",
                          descriptor_from_cg_path(cg_path),
                          "sh", "-c", "sleep 10"])
        subprocess.Popen(["sudo", "cgexec", "-g",
                          descriptor_from_cg_path(cg_path),
                          "python", "-c", multithead_sleep])

        time.sleep(2)  # Sleep for a little bit to let them spawn
        cg = Cgroup(cg_path)
        table = cg.ps_table()

        # We should see 3 processes (but there are 4 threads here)
        self.assertEqual(3, len(table))
        by_name = {proc["name"]: proc for proc in table}
        self.assertEqual(["python", "sh", "sleep"], sorted(by_name.keys()))

        for name in ["sh", "sleep"]:
            proc = by_name[name]
            self.assertIsInstance(proc["pid"], int)
            self.assertIsInstance(proc["memory_info"].vms, int)
            self.assertIsInstance(proc["memory_info"].rss, int)
            self.assertIsInstance(proc["cmdline"], list)
            self.assertIn(proc["status"], PROC_STATUSES_RAW.keys())
