import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

from ui.screen_compose import ScreenCapture, compose_selection
from ui.overlay_selector import OverlaySelector
from ui.scroll_capture import ScrollCaptureController


class FakeScreen:
    def __init__(self, rect, image, dpr):
        self._rect, self._image, self._dpr = rect, image, dpr

    def geometry(self):
        return self._rect

    def grabWindow(self, *_args):
        return QPixmap.fromImage(self._image)


def solid(w, h, dpr, color):
    image = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    image.setDevicePixelRatio(dpr)
    return image


class CompositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_single_dpr_and_both_production_entries(self):
        for dpr in (1, 1.25, 1.5, 2):
            with self.subTest(dpr=dpr):
                geom = QRect(0, 0, 400, 300)
                shot = solid(400, 300, dpr, "red")
                rect = QRect(20, 30, 200, 150)
                expected = compose_selection(rect, [ScreenCapture(geom, shot, dpr)], dpr)
                self.assertEqual((expected.width(), expected.height(), expected.devicePixelRatio()),
                                 (round(200 * dpr), round(150 * dpr), 1))
                self.assertEqual(expected.pixelColor(expected.width()-1, expected.height()-1), QColor("red"))
                screen = FakeScreen(geom, shot, dpr)
                selector = OverlaySelector()
                selector._shots = [QPixmap.fromImage(shot)]
                controller = ScrollCaptureController()
                controller._rect = rect
                with patch("ui.overlay_selector.QGuiApplication.screens", return_value=[screen]), \
                     patch("ui.scroll_capture.QGuiApplication.screens", return_value=[screen]):
                    a = selector._compose(rect)
                    b = controller._grab_selection()
                for actual in (a, b):
                    self.assertEqual((actual.width(), actual.height(), actual.devicePixelRatio()),
                                     (expected.width(), expected.height(), 1))
                    self.assertEqual(actual.pixelColor(actual.width()-1, actual.height()-1), QColor("red"))

    def test_reproduced_600x450_physical_image_at_dpr_1_5(self):
        capture = ScreenCapture(QRect(0, 0, 400, 300), solid(400, 300, 1.5, 'red'), 1.5)
        output = compose_selection(QRect(0, 0, 400, 300), [capture], 1.5)
        self.assertEqual((output.width(), output.height(), output.devicePixelRatio()), (600, 450, 1))
        self.assertEqual(output.pixelColor(599, 449), QColor('red'))

    def test_mixed_dpi_negative_origin_shared_boundary(self):
        left = ScreenCapture(QRect(-400, -50, 400, 300), solid(400, 300, 1.25, "red"), 1.25)
        right = ScreenCapture(QRect(0, -50, 400, 300), solid(400, 300, 2, "blue"), 2)
        output = compose_selection(QRect(-100, 10, 200, 100), [left, right], 1.25)
        self.assertEqual((output.width(), output.height()), (250, 125))
        self.assertEqual(output.pixelColor(124, 124), QColor("red"))
        self.assertEqual(output.pixelColor(125, 124), QColor("blue"))
        screens = [FakeScreen(left.geometry, left.image, left.dpr),
                   FakeScreen(right.geometry, right.image, right.dpr)]
        rect = QRect(-100, 10, 200, 100)
        selector = OverlaySelector()
        selector._shots = [QPixmap.fromImage(left.image), QPixmap.fromImage(right.image)]
        controller = ScrollCaptureController()
        controller._rect = rect
        with patch("ui.overlay_selector.QGuiApplication.screens", return_value=screens), \
             patch("ui.scroll_capture.QGuiApplication.screens", return_value=screens):
            actual = (selector._compose(rect), controller._grab_selection())
        for image in actual:
            self.assertEqual((image.width(), image.height()), (250, 125))
            self.assertEqual(image.pixelColor(124, 124), QColor("red"))
            self.assertEqual(image.pixelColor(125, 124), QColor("blue"))

    def test_null_and_mismatched_frames_are_rejected(self):
        self.assertIsNone(compose_selection(QRect(0, 0, 100, 100),
                          [ScreenCapture(QRect(0, 0, 100, 100), QImage(), 1)], 1))
        self.assertIsNone(compose_selection(QRect(0, 0, 100, 100),
                          [ScreenCapture(QRect(0, 0, 100, 100), solid(50, 50, 1, "red"), 1)], 1))
        self.assertIsNone(compose_selection(QRect(0, 0, 200, 100),
                          [ScreenCapture(QRect(0, 0, 100, 100), solid(100, 100, 1, "red"), 1)], 1))

    def test_overlapping_control_window_hidden_during_grab(self):
        shot = solid(200, 100, 1, 'red')
        screen = FakeScreen(QRect(0, 0, 200, 100), shot, 1)
        c = ScrollCaptureController()
        c._rect = QRect(0, 0, 200, 100)
        c._window._overlaps_selection = True
        with patch("ui.scroll_capture.QGuiApplication.screens", return_value=[screen]), \
             patch.object(c._window, 'isVisible', return_value=True), \
             patch.object(c._window, 'hide') as hide, patch.object(c._window, 'show') as show:
            result = c._grab_selection()
        self.assertEqual(result.pixelColor(199, 99), QColor('red'))
        hide.assert_called_once()
        show.assert_called_once()


if __name__ == "__main__":
    unittest.main()
