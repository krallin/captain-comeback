# coding:utf-8
from six.moves import queue


class QueueAssertionHelper(object):
    ANY_CG = object()

    def assertHasMessageForCg(self, q, message_class, cg_path, **attrs):
        msg = q.get_nowait()
        self.assertIsInstance(msg, message_class)
        if cg_path is self.ANY_CG:
            return
        self.assertEqual(cg_path, msg.cg.path)
        for k, v in attrs.items():
            self.assertEqual(v, getattr(msg, k))

    def assertHasNoMessages(self, q):
        self.assertRaises(queue.Empty, q.get_nowait)
