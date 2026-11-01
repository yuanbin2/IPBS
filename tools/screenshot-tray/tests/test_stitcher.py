import os
import sys
import unittest

import numpy as np
from PyQt6.QtGui import QImage

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from services.stitcher import Stitcher, StitchError


def image(a):
    a = np.ascontiguousarray(a.astype(np.uint8))
    return QImage(a.data, a.shape[1], a.shape[0], a.shape[1]*3,
                  QImage.Format.Format_RGB888).copy()


class StitchTest(unittest.TestCase):
    def page(self, h=2200, w=120):
        rng = np.random.default_rng(55)
        a = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        return a

    def test_1500_viewport_100_scroll_and_pixels(self):
        page = self.page()
        s = Stitcher()
        self.assertTrue(s.append(image(page[:1500])))
        self.assertTrue(s.append(image(page[100:1600])))
        self.assertEqual((s.result().height(), s.result().width()), (1600, 120))
        self.assertTrue(np.array_equal(page[:1600],
                         __import__('services.vertical_match', fromlist=['pixels']).pixels(s.result())))

    def test_micro_accumulates_from_successful_anchor(self):
        page = self.page(900)
        s = Stitcher()
        s.append(image(page[:500]))
        self.assertFalse(s.append(image(page[10:510])))
        self.assertTrue(s.append(image(page[20:520])))
        self.assertEqual(s.result().height(), 520)

    def test_reverse_does_not_append(self):
        page = self.page(900)
        s = Stitcher()
        s.append(image(page[100:600]))
        with self.assertRaises(StitchError) as cm:
            s.append(image(page[:500]))
        self.assertIn('向上滚动', cm.exception.message)
        self.assertEqual(s.result().height(), 500)

    def test_first_frame_pixel_limit(self):
        from unittest.mock import patch
        with patch('services.vertical_match.MAX_TOTAL_PIXELS', 100):
            with self.assertRaises(StitchError) as cm:
                Stitcher().append(image(self.page(20, 20)))
            self.assertEqual(cm.exception.reason, 'limit_pixels')

    def test_sparse_white_dark_and_color(self):
        for background in (255, 12, 120):
            with self.subTest(background=background):
                rng = np.random.default_rng(94)
                page = np.full((1300, 240, 3), background, dtype=np.uint8)
                for y in range(15, 1280, 24):
                    page[y:y+3, 32:200] = rng.integers(0, 256, (3, 168, 3), dtype=np.uint8)
                s = Stitcher()
                s.append(image(page[:500]))
                s.append(image(page[100:600]))
                self.assertEqual(s.result().height(), 600)

    def test_same_row_profile_different_horizontal_layout_rejected(self):
        old = np.full((500, 240, 3), 255, dtype=np.uint8)
        new = old.copy()
        for y in range(0, 500, 13):
            old[y:y+3, 20:65] = 0
            new[y:y+3, 175:220] = 0
        s = Stitcher()
        s.append(image(old))
        with self.assertRaises(StitchError):
            s.append(image(new))
        self.assertEqual(s.result().height(), 500)

    def test_local_animation_does_not_change_seam(self):
        page = self.page(900, 240)
        a, b = page[:500].copy(), page[100:600].copy()
        a[180:210, 5:15] = 0
        b[180:210, 5:15] = 255
        s = Stitcher()
        s.append(image(a))
        s.append(image(b))
        self.assertEqual(s.result().height(), 600)

    def test_fixed_header_is_not_appended_again(self):
        page = self.page(900, 240)
        a, b = page[:500].copy(), page[100:600].copy()
        a[:40], b[:40] = page[:40], page[:40]
        s = Stitcher()
        s.append(image(a))
        s.append(image(b))
        self.assertEqual(s.result().height(), 600)
        from services.vertical_match import pixels
        self.assertTrue(np.array_equal(pixels(s.result())[:40], page[:40]))

    def test_fixed_footer_removed_once(self):
        page = self.page(900, 240)
        a, b = page[:500].copy(), page[100:600].copy()
        footer = page[700:740]
        a[-40:], b[-40:] = footer, footer
        s = Stitcher()
        s.append(image(a))
        s.append(image(b))
        self.assertEqual(s.result().height(), 560)
        from services.vertical_match import pixels
        output = pixels(s.result())
        self.assertTrue(np.array_equal(output[450:560], b[350:460]))

    def test_periodic_table_is_ambiguous(self):
        rng = np.random.default_rng(23)
        row_block = rng.integers(0, 256, (20, 180, 3), dtype=np.uint8)
        page = np.tile(row_block, (45, 1, 1))
        s = Stitcher()
        s.append(image(page[:500]))
        with self.assertRaises(StitchError):
            s.append(image(page[40:540]))
        self.assertEqual(s.result().height(), 500)

    def test_horizontal_offset_rejected(self):
        page = self.page(800, 180)
        s = Stitcher()
        s.append(image(page[:500]))
        with self.assertRaises(StitchError) as cm:
            s.append(image(np.roll(page[100:600], 9, axis=1)))
        self.assertIn('水平偏移', cm.exception.message)
        self.assertEqual(s.result().height(), 500)

    def test_narrow_fixed_sidebar_is_rejected_before_append(self):
        page = self.page(800, 240)
        for side in (slice(None, 30), slice(-30, None)):
            with self.subTest(side=str(side)):
                first, second = page[:500].copy(), page[100:600].copy()
                sidebar = page[600:700, side]
                first[:, side] = np.tile(sidebar, (5, 1, 1))
                second[:, side] = first[:, side]
                s = Stitcher()
                s.append(image(first))
                with self.assertRaises(StitchError) as cm:
                    s.append(image(second))
                self.assertIn('侧栏', cm.exception.message)
                self.assertEqual(s.result().height(), 500)

    def test_plain_margin_is_not_a_fixed_sidebar(self):
        page = self.page(800, 240)
        page[:, :30] = 255
        s = Stitcher()
        s.append(image(page[:500]))
        self.assertTrue(s.append(image(page[100:600])))
        self.assertEqual(s.result().height(), 600)

    def test_next_frame_pixel_limit_preserves_result(self):
        from unittest.mock import patch
        page = self.page(800, 100)
        s = Stitcher()
        s.append(image(page[:500]))
        with patch('services.vertical_match.MAX_TOTAL_PIXELS', 55_000):
            with self.assertRaises(StitchError) as cm:
                s.append(image(page[100:600]))
        self.assertEqual(cm.exception.reason, 'limit_pixels')
        self.assertEqual(s.result().height(), 500)

    def test_static_small_noise_does_not_append(self):
        page = self.page(500, 180)
        noise = np.random.default_rng(3).integers(-2, 3, page.shape)
        altered = np.clip(page.astype(np.int16)+noise, 0, 255).astype(np.uint8)
        s = Stitcher()
        s.append(image(page))
        self.assertFalse(s.append(image(altered)))
        self.assertEqual(s.result().height(), 500)

    def test_single_narrow_content_zone_is_insufficient_evidence(self):
        rng = np.random.default_rng(4)
        page = np.full((800, 240, 3), 255, dtype=np.uint8)
        page[:, 115:125] = rng.integers(0, 256, (800, 10, 3), dtype=np.uint8)
        s = Stitcher()
        s.append(image(page[:500]))
        with self.assertRaises(StitchError):
            s.append(image(page[100:600]))
        self.assertEqual(s.result().height(), 500)

    def test_frame_and_height_limits(self):
        from unittest.mock import patch
        page = self.page(800, 100)
        with patch('services.vertical_match.MAX_TOTAL_HEIGHT', 400):
            with self.assertRaises(StitchError) as cm:
                Stitcher().append(image(page[:500]))
            self.assertEqual(cm.exception.reason, 'limit_height')
        s = Stitcher()
        s.append(image(page[:500]))
        with patch('services.vertical_match.MAX_FRAMES', 1):
            with self.assertRaises(StitchError) as cm:
                s.append(image(page[100:600]))
            self.assertEqual(cm.exception.reason, 'limit_frames')
        with patch('services.vertical_match.MAX_TOTAL_HEIGHT', 550):
            with self.assertRaises(StitchError) as cm:
                s.append(image(page[100:600]))
            self.assertEqual(cm.exception.reason, 'limit_height')
        self.assertEqual(s.result().height(), 500)


if __name__ == '__main__': unittest.main()
