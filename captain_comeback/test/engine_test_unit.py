# coding:utf-8
import unittest
import tempfile
import shutil
import time

from captain_comeback.cgroup import Cgroup
from captain_comeback.restart import engine


class EngineTestUnit(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_try_docker_retry(self):
        # This script requires running twice to succeed
        test_file = "{0}/foo".format(self.test_dir)
        shell = 'if test -f {0};' \
                'then exit 0; ' \
                'else touch {0} && exit 1; ' \
                'fi'.format(test_file, test_file)

        cmd = ['sh', '-c', shell]
        ret = engine.try_docker(Cgroup("/some/foo"), *cmd)
        self.assertTrue(ret)

    def test_try_docker_without_retry(self):
        # This script will not succeed if run twice
        test_file = "{0}/foo".format(self.test_dir)
        shell = 'if test -f {0};' \
                'then exit 1; ' \
                'else touch {0} && exit 0; ' \
                'fi'.format(test_file, test_file)

        cmd = ['sh', '-c', shell]
        ret = engine.try_docker(Cgroup("/some/foo"), *cmd)
        self.assertTrue(ret)

    def test_try_docker_and_wait_fatal(self):
        t0 = time.time()
        cmd = ['docker', 'restart', 'foobar']
        ret = engine.try_docker(Cgroup("/some/foo"), *cmd)
        self.assertFalse(ret)
        self.assertLess(time.time() - t0, 1)
