import os
import sys
import threading
import time
import unittest

import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ui.capture_worker import CaptureWorker


def frame(a):
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.shape[1]*3,
                  QImage.Format.Format_RGB888).copy()


class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        page = np.random.default_rng(5).integers(0, 256, (800, 100, 3), dtype=np.uint8)
        self.a, self.b = frame(page[:500]), frame(page[100:600])
        self.worker = CaptureWorker()
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.worker.stop()
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())

    def wait_for(self, predicate, timeout=2):
        until = time.monotonic()+timeout
        while time.monotonic() < until:
            self.app.processEvents()
            if predicate(): return
            time.sleep(.01)
        self.fail('timed out waiting for worker')

    def submit(self, image, times=1):
        for _ in range(times):
            self.wait_for(lambda: self.worker.submit_frame(image))

    def test_retry_first_stable_frame_joins_old_anchor(self):
        self.submit(self.a)
        self.wait_for(lambda: self.worker._stitcher.frames == 1)
        self.worker.pause()
        self.worker.reset_session()
        self.submit(self.b, 3)
        self.wait_for(lambda: self.worker._stitcher.frames == 2)
        self.assertEqual(self.worker._stitcher.result().height(), 600)

    def test_pause_discards_old_queue_and_cancel_stops(self):
        self.submit(self.a)
        self.wait_for(lambda: self.worker._stitcher.frames == 1)
        self.worker.pause()
        self.assertEqual(self.worker._queue.qsize(), 0)
        self.assertFalse(self.worker.submit_frame(self.b))
        self.worker.stop()
        self.thread.join(2)
        self.assertEqual(self.worker._stitcher.frames, 1)

    def test_finish_processes_last_stable_frame(self):
        self.submit(self.a)
        self.wait_for(lambda: self.worker._stitcher.frames == 1)
        self.submit(self.b, 3)
        self.worker.request_result()
        self.wait_for(lambda: not self.thread.is_alive())
        self.assertEqual(self.worker._stitcher.result().height(), 600)


if __name__ == '__main__': unittest.main()
