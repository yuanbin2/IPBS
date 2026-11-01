import assert from "node:assert/strict";
import test from "node:test";
import { removeDuplicateDetectionBoxes } from "../../src/features/blog/utils/ocrDetection.ts";

test("OCR detection merges contour duplicates for a clear large-font line", () => {
  const boxes = [
    { x: 59, y: 507, width: 250, height: 13 },
    { x: 60, y: 507, width: 249, height: 13 },
  ];
  const result = removeDuplicateDetectionBoxes(boxes);
  assert.equal(result.removed, 1);
  assert.deepEqual(result.boxes, [{ x: 59, y: 507, width: 250, height: 13 }]);
});

test("OCR detection retains neighboring words and nearby rows", () => {
  const boxes = [
    { x: 59, y: 507, width: 128, height: 13 },
    { x: 193, y: 507, width: 116, height: 13 },
    { x: 59, y: 529, width: 250, height: 13 },
  ];
  const result = removeDuplicateDetectionBoxes(boxes);
  assert.equal(result.removed, 0);
  assert.deepEqual(result.boxes, boxes);
});

test("OCR detection keeps partly overlapping distinct text boxes", () => {
  const boxes = [
    { x: 10, y: 20, width: 110, height: 20 },
    { x: 80, y: 20, width: 110, height: 20 },
  ];
  const result = removeDuplicateDetectionBoxes(boxes);
  assert.equal(result.removed, 0);
  assert.equal(result.boxes.length, 2);
});
