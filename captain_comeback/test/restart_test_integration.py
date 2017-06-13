# coding:utf-8
import os
import unittest
import subprocess
import json
import socket
import time
from six.moves import queue

from captain_comeback.restart.engine import restart
from captain_comeback.restart.adapter import (docker, docker_wipe_fs, null)
from captain_comeback.cgroup import Cgroup
from captain_comeback.restart.messages import RestartCompleteMessage
from captain_comeback.activity.messages import (RestartCgroupMessage,
                                                RestartTimeoutMessage)

from captain_comeback.test.queue_assertion_helper import (
        QueueAssertionHelper)


CG_DOCKER_ROOT_DIR = "/sys/fs/cgroup/memory/docker/"

EXITS_WITH_TERM_1 = ["krallin/ubuntu-tini", "sleep", "100"]
EXITS_WITH_TERM_ALL = ["ubuntu", "sh", "-c", "sleep 100"]
EXITS_IF_FILE = [
    "ubuntu", "sh", "-c",
    "if test -f foo; then exit 1; else touch foo && sleep 100; fi"
]
NEVER_EXITS = ["ubuntu", "sleep", "100"]  # No default sighanders as PID 1


def docker_json(cg):
    j = subprocess.check_output(["docker", "inspect", cg.name()])
    j = j.decode("utf-8")
    return json.loads(j)[0]


def random_free_port():
    sock = socket.socket()
    sock.bind(('', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class RestartTestIntegration(unittest.TestCase, QueueAssertionHelper):
    def _launch_container(self, options):
        cmd = ["docker", "run", "-d"] + options
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)

        out, err = p.communicate()
        if p.returncode:
            m = "{0} failed with status {1}:\n{2}\n{3}".format(cmd,
                                                               p.returncode,
                                                               out, err)
            self.fail(m)
        cid = out.decode("utf-8").strip()
        self._cids.append(cid)
        return Cgroup("/".join([CG_DOCKER_ROOT_DIR, cid]))

    def setUp(self):
        self._cids = []

    def tearDown(self):
        for cid in self._cids:
            subprocess.check_output(["docker", "rm", "-f", cid])

    def test_notifies_queues(self):
        cg = self._launch_container(EXITS_WITH_TERM_1)
        job_q = queue.Queue()
        activity_q = queue.Queue()
        restart(docker, 10, cg, job_q, activity_q)

        self.assertHasMessageForCg(job_q, RestartCompleteMessage, cg.path)
        self.assertHasMessageForCg(activity_q, RestartCgroupMessage, cg.path)
        self.assertHasNoMessages(activity_q)

    def test_notifies_queues_timeout(self):
        cg = self._launch_container(NEVER_EXITS)
        job_q = queue.Queue()
        activity_q = queue.Queue()
        restart(docker, 3, cg, job_q, activity_q)

        self.assertHasMessageForCg(job_q, RestartCompleteMessage, cg.path)
        self.assertHasMessageForCg(activity_q, RestartCgroupMessage, cg.path)
        self.assertHasMessageForCg(activity_q, RestartTimeoutMessage, cg.path,
                                   grace_period=3)

    def test_restart_container_with_term_1(self):
        cg = self._launch_container(EXITS_WITH_TERM_1)

        pid_before = docker_json(cg)["State"]["Pid"]
        time_before = time.time()

        q = queue.Queue()
        restart(docker, 10, cg, q, q)

        time_after = time.time()
        pid_after = docker_json(cg)["State"]["Pid"]

        self.assertNotEqual(pid_before, pid_after)
        self.assertLess(time_after - time_before, 5)

    def test_restart_container_with_term_all(self):
        cg = self._launch_container(EXITS_WITH_TERM_ALL)

        pid_before = docker_json(cg)["State"]["Pid"]
        time_before = time.time()

        q = queue.Queue()
        restart(docker, 10, cg, q, q)

        time_after = time.time()
        pid_after = docker_json(cg)["State"]["Pid"]

        self.assertNotEqual(pid_before, pid_after)
        self.assertLess(time_after - time_before, 5)

    def test_restarts_misbehaved_container(self):
        cg = self._launch_container(NEVER_EXITS)

        pid_before = docker_json(cg)["State"]["Pid"]
        time_before = time.time()

        q = queue.Queue()
        restart(docker, 3, cg, q, q)

        time_after = time.time()
        pid_after = docker_json(cg)["State"]["Pid"]

        self.assertNotEqual(pid_before, pid_after)
        self.assertGreater(time_after - time_before, 2)

    def test_restarts_with_ports(self):
        host_port = random_free_port()

        options = ["-p", "{0}:80".format(host_port)] + EXITS_WITH_TERM_1
        cg = self._launch_container(options)
        q = queue.Queue()
        restart(docker, 10, cg, q, q)

        binding = docker_json(cg)["NetworkSettings"]["Ports"]["80/tcp"][0]
        port = int(binding["HostPort"])

        self.assertEqual(host_port, port)

    def test_restart_does_not_wipe_fs(self):
        q = queue.Queue()

        cg = self._launch_container(EXITS_IF_FILE)
        time.sleep(2)

        restart(docker, 1, cg, q, q)
        time.sleep(2)

        self.assertFalse(docker_json(cg)["State"]["Running"])

    def test_restart_kills_processes(self):
        q = queue.Queue()

        cg = self._launch_container(NEVER_EXITS)
        time.sleep(2)

        restart(null, 1, cg, q, q)
        time.sleep(2)

        self.assertFalse(docker_json(cg)["State"]["Running"])

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_restart_wipes_fs(self):
        q = queue.Queue()

        cg = self._launch_container(EXITS_IF_FILE)
        time.sleep(2)

        restart(docker_wipe_fs, 1, cg, q, q)
        time.sleep(2)

        self.assertTrue(docker_json(cg)["State"]["Running"])

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_restart_with_memory_limit(self):
        options = ["--memory", "10mb"] + EXITS_WITH_TERM_1
        cg = self._launch_container(options)
        q = queue.Queue()
        restart(docker, 10, cg, q, q)
