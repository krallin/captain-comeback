# coding:utf-8
from six.moves import queue


class QueueAssertionHelper(object):
    ANY_CG = object()

    def assertHasMessageForCg(self, q, message_class, cg_path):
        msg = q.get_nowait()
        self.assertIsInstance(msg, message_class)
        if cg_path is self.ANY_CG:
            return
        self.assertEqual(cg_path, msg.cg.path)

    def assertHasNoMessages(self, q):
        self.assertRaises(queue.Empty, q.get_nowait)
