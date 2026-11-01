"""Bounded, generation-aware capture worker. Commands never queue behind images."""
from __future__ import annotations

import logging
import queue
import threading
import time

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QImage

from services.stitcher import StitchError, Stitcher, downsample, is_limit_reason, mean_abs_diff

_LOG = logging.getLogger("tray.scroll")


class CaptureWorker(QObject):
    frame_collected = pyqtSignal(int, int, QImage)  # generation, count, thumbnail
    bottom_detected = pyqtSignal(int)
    failed = pyqtSignal(int, str, str)
    limit_reached = pyqtSignal(int, str)
    result_ready = pyqtSignal(int, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue(maxsize=3)
        self._stop = threading.Event()
        self._finish = threading.Event()
        self._deadline = 0.0
        self.generation = 0
        self._number = 0
        self._stitcher = Stitcher()
        self._paused = False
        _LOG.info("采集 worker idle -> capturing gen=%d", self.generation)

    def submit_frame(self, frame: QImage) -> bool:
        if self._stop.is_set() or self._paused or (self._finish.is_set() and time.monotonic() > self._deadline):
            return False
        try:
            self._number += 1
            self._queue.put_nowait((self.generation, self._number, frame))
            _LOG.debug("入队 frame=%d DPR=%.2f size=%dx%d depth=%d gen=%d",
                       self._number, frame.devicePixelRatio(), frame.width(), frame.height(),
                       self._queue.qsize(), self.generation)
            return True
        except queue.Full:
            _LOG.warning("采集队列满 depth=%d，保留原有中间帧；请分段停顿", self._queue.qsize())
            return False

    def reset_session(self):
        self.generation += 1
        self._paused = False
        self._clear()
        _LOG.info("采集状态 recovering generation=%d", self.generation)

    def pause(self):
        self.generation += 1
        self._paused = True
        self._clear()
        _LOG.info("采集 worker -> paused gen=%d", self.generation)

    def request_result(self):
        self._deadline = time.monotonic() + .65
        self._finish.set()
        _LOG.info("采集 worker -> finishing depth=%d gen=%d", self._queue.qsize(), self.generation)

    def stop(self):
        self._stop.set()
        self._clear()
        _LOG.info("采集 worker -> cancelled gen=%d", self.generation)

    def _clear(self):
        while True:
            try: self._queue.get_nowait()
            except queue.Empty: return

    def _collect(self, frame, generation, number):
        if self._stop.is_set() or generation != self.generation:
            return "stale"
        try:
            appended = self._stitcher.append(frame)
        except StitchError as exc:
            _LOG.warning("拒绝 frame=%d gen=%d reason=%s message=%s", number, generation, exc.reason, exc.message)
            self._paused = True
            self._clear()
            if is_limit_reason(exc.reason): self.limit_reached.emit(generation, exc.message)
            else: self.failed.emit(generation, exc.reason, exc.message)
            return "failed"
        if not appended: return "unchanged"
        canvas = self._stitcher.canvas()
        match = self._stitcher.last_match
        _LOG.info("采集成功 frame=%d gen=%d size=%dx%d DPR=%.2f shift=%s confidence=%s depth=%d output=%dx%d",
                  number, generation, frame.width(), frame.height(), frame.devicePixelRatio(),
                  match.shift if match else 0, f"{match.coverage:.2f}" if match else "initial",
                  self._queue.qsize(), canvas.width(), canvas.height())
        thumb = canvas.scaled(176, 100, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.FastTransformation)
        self.frame_collected.emit(generation, self._stitcher.frames, thumb)
        return "stitched"

    def run(self):
        baseline = None
        previous = None
        stable = 0
        seen_generation = self.generation
        last_success = None
        last_candidate = None
        while not self._stop.is_set():
            if self._finish.is_set() and time.monotonic() >= self._deadline:
                if (last_candidate is not None and not self._paused and
                        (last_success is None or mean_abs_diff(last_candidate, last_success) > 4)):
                    self._collect(last_candidate, self.generation, self._number)
                self.result_ready.emit(self.generation, self._stitcher.result())
                return
            try:
                generation, number, frame = self._queue.get(timeout=.05)
            except queue.Empty:
                continue
            if generation != self.generation or self._stop.is_set() or self._paused:
                continue
            if generation != seen_generation:
                seen_generation = generation
                baseline = previous = last_candidate = None
                last_success = self._stitcher.anchor()  # successful raw frame survives reset
                stable = 0
            ds = downsample(frame)
            if previous is None:
                previous, baseline = frame, ds
                if self._stitcher.is_empty():
                    if self._collect(frame, generation, number) == "stitched": last_success = frame
                continue
            change = mean_abs_diff(ds, baseline)
            baseline, previous = ds, frame
            if change > 3:
                stable = 0
                last_candidate = None
                continue
            stable += 1
            if stable < 2:
                continue
            last_candidate = frame
            if last_success is not None and mean_abs_diff(frame, last_success) <= 4:
                self.bottom_detected.emit(generation)  # UI says only "no change"
                continue
            status = self._collect(frame, generation, number)
            if status == "stitched":
                last_success = frame
                last_candidate = None
                stable = 0
            elif status == "unchanged":
                # Keep successful anchor; later micro movements can accumulate.
                stable = 0
