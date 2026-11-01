/**
 * A long composite must not be sent to the detector as one image: the OCR
 * library caps its longest input side at 1920px and would shrink every line.
 * Bands overlap so text at a seam is visible in both crops; the midpoint of
 * the overlap owns each recognized line exactly once.
 */
import type { OcrLine } from "./screenshotOcr";

export interface OcrBand {
  top: number;
  bottom: number;
  keepTop: number;
  keepBottom: number;
}

/** Later bands are wider to amortize detector startup. The first band is shorter
 * so a useful first draft can reach the editor without waiting for a whole page. */
export const OCR_BAND_HEIGHT = 1440;
export const OCR_FIRST_BAND_HEIGHT = 640;
export const OCR_BAND_OVERLAP = 128;

export function planOcrBands(height: number, bandHeight = OCR_BAND_HEIGHT, overlap = OCR_BAND_OVERLAP, firstBandHeight = OCR_FIRST_BAND_HEIGHT): OcrBand[] {
  if (!Number.isSafeInteger(height) || height < 1 || !Number.isSafeInteger(bandHeight) || bandHeight < 1 ||
      !Number.isSafeInteger(overlap) || overlap < 0 || overlap >= bandHeight ||
      !Number.isSafeInteger(firstBandHeight) || firstBandHeight < 1 || firstBandHeight > bandHeight || overlap >= firstBandHeight) {
    throw new Error("OCR 分段尺寸无效");
  }
  if (height <= bandHeight) return [{ top: 0, bottom: height, keepTop: 0, keepBottom: height }];
  const bands: OcrBand[] = [];
  let top = 0;
  let index = 0;
  while (top < height) {
    const currentHeight = index === 0 ? firstBandHeight : bandHeight;
    const bottom = Math.min(height, top + currentHeight);
    bands.push({
      top,
      bottom,
      keepTop: top === 0 ? 0 : top + overlap / 2,
      keepBottom: bottom === height ? height : bottom - overlap / 2,
    });
    if (bottom === height) break;
    top = bottom - overlap;
    index += 1;
  }
  return bands;
}

/** Map a band-local OCR line back onto the final composite. */
export function mapBandLines(band: OcrBand, lines: OcrLine[], keepOutsideOwnership = false): OcrLine[] {
  return lines.flatMap((line) => {
    const y = band.top + line.bbox.y;
    const center = y + line.bbox.height / 2;
    if (!keepOutsideOwnership && (center < band.keepTop || center >= band.keepBottom)) return [];
    return [{ ...line, bbox: { ...line.bbox, y } }];
  });
}

/**
 * De-duplicate exact rows found in overlapping bands by both text and native
 * pixel geometry. Keep a row found only in its non-owning band: midpoint
 * ownership must not turn an owner-band detector miss into lost text.
 */
export function dedupeOverlappingBandLines(lines: OcrLine[]): OcrLine[] {
  const sorted = [...lines].sort((a, b) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x);
  const result: OcrLine[] = [];
  const withAlternative = (winner: OcrLine, other: OcrLine): OcrLine => {
    const alternatives = [...(winner.alternatives ?? []), ...(other.alternatives ?? []),
      ...(other.text === winner.text ? [] : [{ text: other.text, confidence: other.confidence }])]
      .filter((item, index, all) => item.text && item.text !== winner.text && all.findIndex((candidate) => candidate.text === item.text) === index)
      .slice(0, 3);
    return { ...winner, alternatives };
  };
  for (const line of sorted) {
    const normalized = line.text.replace(/\s+/g, "").toLocaleLowerCase();
    let duplicateIndex = -1;
    for (let index = result.length - 1; index >= 0; index -= 1) {
      const previous = result[index]!;
      if (line.bbox.y - (previous.bbox.y + previous.bbox.height) > Math.max(line.bbox.height, previous.bbox.height)) break;
      const sameText = previous.text.replace(/\s+/g, "").toLocaleLowerCase() === normalized;
      const verticalOverlap = Math.max(0, Math.min(line.bbox.y + line.bbox.height, previous.bbox.y + previous.bbox.height) - Math.max(line.bbox.y, previous.bbox.y));
      const horizontalOverlap = Math.max(0, Math.min(line.bbox.x + line.bbox.width, previous.bbox.x + previous.bbox.width) - Math.max(line.bbox.x, previous.bbox.x));
      const verticalRatio = verticalOverlap / Math.max(1, Math.min(line.bbox.height, previous.bbox.height));
      const horizontalRatio = horizontalOverlap / Math.max(1, Math.min(line.bbox.width, previous.bbox.width));
      const samePhysicalBox = verticalRatio >= 0.8 && horizontalRatio >= 0.8 && Math.abs(line.confidence - previous.confidence) >= 0.2;
      if ((sameText && verticalRatio >= 0.45 && horizontalRatio >= 0.45) || (!sameText && samePhysicalBox)) {
        duplicateIndex = index;
        break;
      }
    }
    if (duplicateIndex < 0) {
      result.push(line);
    } else {
      const previous = result[duplicateIndex]!;
      // The detector can emit overlapping boxes for one visual row. When the
      // recognition variants share near-identical geometry, prefer the clearly
      // stronger hypothesis but retain the other text as a visible review alternative.
      if (Math.abs(line.confidence - previous.confidence) >= 0.2 && line.text !== previous.text) {
        const winner = line.confidence > previous.confidence ? line : previous;
        const other = winner === line ? previous : line;
        result[duplicateIndex] = withAlternative(winner, other);
      } else {
        const winner = line.confidence > previous.confidence ? line : previous;
        const other = winner === line ? previous : line;
        result[duplicateIndex] = withAlternative(winner, other);
      }
    }
  }
  return result.sort((a, b) => a.bbox.y - b.bbox.y || a.bbox.x - b.bbox.x);
}
