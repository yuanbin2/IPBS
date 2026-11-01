"""Stable public interface for the vertical screenshot matcher."""
from services.vertical_match import (Stitcher, StitchError, downsample,
                                     mean_abs_diff, is_limit_reason,
                                     MAX_FRAMES, MAX_TOTAL_HEIGHT, MAX_TOTAL_PIXELS,
                                     REASON_NO_OVERLAP, REASON_LIMIT_FRAMES,
                                     REASON_LIMIT_HEIGHT, REASON_LIMIT_PIXELS)
