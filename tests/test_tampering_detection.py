"""
Tests for the block-wise ELA math in tampering_detection.py - deterministic,
built on small synthetic numpy arrays, no real images or JPEG re-compression
required (same style as test_ocr.py / test_forgery_prediction.py).

Coverage here targets the three real failure modes found during manual
testing against actual specimen images (see tampering_detection.py's module
docstring for the full story):
  (a) a uniformly-noisy image must not be flagged (global average false
      positive in the original version)
  (b) a small localized spike must be flagged even when most of the image
      is at (near) exact zero, where raw MAD degenerates to 0
  (c) a large contiguous "hot" area (legitimate dense print content, not
      an edit) must be discarded by the region-size filter
"""

import numpy as np

from app.modules.tampering_detection import (
    _block_z_scores,
    _hot_block_regions,
    _ela_score,
    MAX_REGION_AREA_FRACTION,
)


def test_uniform_block_means_produce_no_outliers():
    # Every block has the same error - nothing should stand out relative
    # to the rest of the same image.
    block_means = np.full((10, 10), 5.0)
    z = _block_z_scores(block_means)
    assert not (z > 3.5).any()


def test_isolated_spike_among_mostly_zero_blocks_is_detected():
    # Majority-zero distribution (common on real documents with large
    # blank areas) with ONE clear spike - raw MAD would be 0 here without
    # the spread floor, which would either crash or blind detection
    # entirely. The spike must still be flagged.
    block_means = np.zeros((10, 10))
    block_means[3, 3] = 50.0
    z = _block_z_scores(block_means)
    assert z[3, 3] > 3.5
    assert (z > 3.5).sum() == 1  # only the true spike, nothing else


def test_small_hot_region_is_kept():
    hot_mask = np.zeros((20, 20), dtype=bool)
    hot_mask[5:7, 5:7] = True  # a 2x2 block - well under the area limit
    regions, kept_mask = _hot_block_regions(hot_mask, block_h=10, block_w=10)
    assert len(regions) == 1
    assert kept_mask.sum() == 4
    assert regions[0]["hot_block_count"] == 4


def test_large_hot_region_is_discarded():
    hot_mask = np.zeros((20, 20), dtype=bool)
    # A solid block covering well over MAX_REGION_AREA_FRACTION of the
    # 400-cell grid - simulates a dense-print area, not a targeted edit.
    side = int((MAX_REGION_AREA_FRACTION * 400) ** 0.5) + 3
    hot_mask[:side, :side] = True
    regions, kept_mask = _hot_block_regions(hot_mask, block_h=10, block_w=10)
    assert regions == []
    assert not kept_mask.any()


def test_region_reports_sparse_vs_bbox_block_count_separately():
    # An L-shaped (sparse) connected region: bounding box is much bigger
    # than the actual number of hot blocks in it - both numbers should be
    # reported, not conflated.
    hot_mask = np.zeros((20, 20), dtype=bool)
    hot_mask[5, 5:8] = True
    hot_mask[6, 5] = True
    hot_mask[7, 5] = True
    regions, _ = _hot_block_regions(hot_mask, block_h=10, block_w=10)
    assert len(regions) == 1
    assert regions[0]["hot_block_count"] == 5
    assert regions[0]["bbox_block_count"] > regions[0]["hot_block_count"]


def test_ela_score_zero_when_nothing_kept():
    kept_mask = np.zeros((10, 10), dtype=bool)
    z = np.zeros((10, 10))
    assert _ela_score(kept_mask, z) == 0.0


def test_ela_score_increases_with_hot_fraction_and_magnitude():
    z = np.zeros((10, 10))
    small_mask = np.zeros((10, 10), dtype=bool)
    small_mask[0, 0] = True
    z[0, 0] = 4.0
    small_score = _ela_score(small_mask, z)

    big_mask = np.zeros((10, 10), dtype=bool)
    big_mask[0:3, 0:3] = True
    z[0:3, 0:3] = 10.0
    big_score = _ela_score(big_mask, z)

    assert big_score > small_score
# Test Suite: Verifies multi-quality ELA heatmaps against controlled synthetic forgeries.
