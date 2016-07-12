# coding:utf-8
import os
import unittest
import subprocess
import json
import socket
import time
from six.moves import queue

from captain_comeback.restart.engine import restart
from captain_comeback.cgroup import Cgroup


CG_DOCKER_ROOT_DIR = "/sys/fs/cgroup/memory/docker/"

WELL_BEHAVED = ["krallin/ubuntu-tini", "sleep", "100"]
MIS_BEHAVED = ["ubuntu", "sleep", "100"]  # No default sighanders as PID 1


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


class RestartTestIntegration(unittest.TestCase):
    def _launch_container(self, options):
        cmd = ["docker", "run", "-d"] + options
        try:
            cid = subprocess.check_output(cmd).decode("utf-8").strip()
        except subprocess.CalledProcessError as e:
            m = "{0} failed with status {1}: {2}".format(cmd,
                                                         e.returncode,
                                                         e.output)
            self.fail(m)
        self._cids.append(cid)
        return Cgroup("/".join([CG_DOCKER_ROOT_DIR, cid]))

    def setUp(self):
        self._cids = []

    def tearDown(self):
        for cid in self._cids:
            subprocess.check_output(["docker", "rm", "-f", cid])

    def test_restarts_well_behaved_container(self):
        cg = self._launch_container(WELL_BEHAVED)

        pid_before = docker_json(cg)["State"]["Pid"]
        time_before = time.time()

        restart(queue.Queue(), 10, cg)

        time_after = time.time()
        pid_after = docker_json(cg)["State"]["Pid"]

        self.assertNotEqual(pid_before, pid_after)
        self.assertLess(time_after - time_before, 5)

    def test_restarts_misbehaved_container(self):
        cg = self._launch_container(MIS_BEHAVED)

        pid_before = docker_json(cg)["State"]["Pid"]
        time_before = time.time()

        restart(queue.Queue(), 3, cg)

        time_after = time.time()
        pid_after = docker_json(cg)["State"]["Pid"]

        self.assertNotEqual(pid_before, pid_after)
        self.assertGreater(time_after - time_before, 2)

    def test_restarts_with_ports(self):
        host_port = random_free_port()

        options = ["-p", "{0}:80".format(host_port)] + WELL_BEHAVED
        cg = self._launch_container(options)
        restart(queue.Queue(), 10, cg)

        binding = docker_json(cg)["NetworkSettings"]["Ports"]["80/tcp"][0]
        port = int(binding["HostPort"])

        self.assertEqual(host_port, port)

    @unittest.skipUnless(os.geteuid() == 0, "requires root")
    def test_restart_with_memory_limit(self):
        options = ["--memory", "10mb"] + WELL_BEHAVED
        cg = self._launch_container(options)
        restart(queue.Queue(), 10, cg)
