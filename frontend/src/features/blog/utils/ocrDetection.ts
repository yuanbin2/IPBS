export interface DetectionBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Canvas-native contour extraction can emit two almost identical boxes for a
 * single line (commonly around anti-aliased glyph edges). ppu's per-line
 * recognizer treats them as two text fragments, concatenates both full crops,
 * then splits one CTC result back across the duplicate geometry. Remove only
 * near-identical boxes; adjacent words and merely overlapping neighboring
 * lines remain independent.
 */
export function removeDuplicateDetectionBoxes<T extends DetectionBox>(boxes: readonly T[]): {
  boxes: T[];
  removed: number;
} {
  const result: T[] = [];
  let removed = 0;
  for (const candidate of boxes) {
    const area = candidate.width * candidate.height;
    if (!(area > 0) || !Number.isFinite(area)) continue;
    let duplicateIndex = -1;
    for (let index = result.length - 1; index >= 0; index -= 1) {
      const previous = result[index];
      if (!previous) continue;
      const left = Math.max(candidate.x, previous.x);
      const top = Math.max(candidate.y, previous.y);
      const right = Math.min(candidate.x + candidate.width, previous.x + previous.width);
      const bottom = Math.min(candidate.y + candidate.height, previous.y + previous.height);
      const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
      const previousArea = previous.width * previous.height;
      const union = area + previousArea - intersection;
      const overlap = union > 0 ? intersection / union : 0;
      const centerDeltaX = Math.abs(candidate.x + candidate.width / 2 - previous.x - previous.width / 2);
      const centerDeltaY = Math.abs(candidate.y + candidate.height / 2 - previous.y - previous.height / 2);
      if (overlap >= 0.96 && centerDeltaX <= Math.max(2, Math.min(candidate.width, previous.width) * 0.02) &&
          centerDeltaY <= Math.max(2, Math.min(candidate.height, previous.height) * 0.12)) {
        duplicateIndex = index;
        break;
      }
    }
    if (duplicateIndex < 0) {
      result.push(candidate);
      continue;
    }
    const previous = result[duplicateIndex];
    if (!previous) continue;
    // Keep the union so deduplication cannot trim a border present in only one
    // of the two contour boxes. The boxes have already passed a strict IoU gate.
    result[duplicateIndex] = {
      ...previous,
      x: Math.min(candidate.x, previous.x),
      y: Math.min(candidate.y, previous.y),
      width: Math.max(candidate.x + candidate.width, previous.x + previous.width) - Math.min(candidate.x, previous.x),
      height: Math.max(candidate.y + candidate.height, previous.y + previous.height) - Math.min(candidate.y, previous.y),
    };
    removed += 1;
  }
  return { boxes: result, removed };
}
