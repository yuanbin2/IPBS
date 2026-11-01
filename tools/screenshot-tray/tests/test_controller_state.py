import os
import sys
import unittest
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from PyQt6.QtGui import QImage
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication
from ui.scroll_capture import ScrollCaptureController, _CaptureState


class ControllerStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stale_signal_and_retry_generation(self):
        c = ScrollCaptureController()
        c._state = _CaptureState.CAPTURING
        c._worker.generation = 2
        c._on_failed(1, 'no_overlap', 'old failure')
        self.assertEqual(c._state, _CaptureState.CAPTURING)
        c._on_failed(2, 'no_overlap', 'new failure')
        self.assertEqual(c._state, _CaptureState.PAUSED)
        self.assertEqual(c._worker.generation, 3)
        c._on_retry_clicked()
        self.assertEqual(c._state, _CaptureState.RECOVERING)
        self.assertEqual(c._worker.generation, 4)
        c.abort()

    def test_cancel_wins_over_late_finish_signal(self):
        c = ScrollCaptureController()
        c._state = _CaptureState.CAPTURING
        results = []
        c.finished.connect(lambda _image: results.append('finished'))
        c.cancelled.connect(lambda: results.append('cancelled'))
        c.finish()
        c._on_cancel_clicked()
        c._on_result_ready(c._worker.generation, QImage(2, 2, QImage.Format.Format_ARGB32))
        self.assertEqual(results, ['cancelled'])

    def test_timer_worker_finish_lifecycle(self):
        image = QImage(100, 500, QImage.Format.Format_ARGB32)
        image.fill(0xff123456)
        c = ScrollCaptureController()
        result = []
        c.finished.connect(lambda shot: result.append(shot.height()))
        with patch.object(c._window, 'show_near'), patch.object(c, '_show_indicators'), \
             patch.object(c, '_grab_selection', return_value=image), patch.object(c, '_register_escape'):
            c.start(QRect(0, 0, 100, 500))
            until = time.monotonic()+2
            while c._worker._stitcher.frames == 0 and time.monotonic() < until:
                self.app.processEvents()
                time.sleep(.01)
            self.assertEqual(c._worker._stitcher.frames, 1)
            c.finish()
            until = time.monotonic()+2
            while not result and time.monotonic() < until:
                self.app.processEvents()
                time.sleep(.01)
        self.assertEqual(result, [500])
        self.assertIsNone(c._thread)


if __name__ == '__main__': unittest.main()
