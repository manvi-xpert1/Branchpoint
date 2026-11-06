/** Turning a list of per-run values (e.g. downtime) into histogram bars. */

export interface Bin {
  label: string;
  from: number;
  to: number; // inclusive for the last bin, exclusive otherwise
  count: number;
}

/**
 * Group values into bars for a histogram.
 *
 * Simulated downtime often takes only a few distinct values (e.g. 0, 4,
 * 10, 14 when it depends on which events happened). In that case we show
 * one bar per distinct value, which is easier to read than ranges.
 * Otherwise the range is split into `maxBins` equal-width bins.
 */
export function histogram(values: number[], maxBins = 20): Bin[] {
  if (values.length === 0) return [];
  const distinct = [...new Set(values)].sort((a, b) => a - b);
  if (distinct.length <= maxBins) {
    return distinct.map((v) => ({
      label: fmtNum(v), from: v, to: v, count: values.filter((x) => x === v).length,
    }));
  }
  const min = distinct[0];
  const max = distinct[distinct.length - 1];
  const width = (max - min) / maxBins;
  const bins: Bin[] = Array.from({ length: maxBins }, (_, i) => {
    const from = min + i * width;
    const to = i === maxBins - 1 ? max : from + width;
    return { label: `${fmtNum(from)}–${fmtNum(to)}`, from, to, count: 0 };
  });
  for (const v of values) {
    // The max value belongs to the last bin rather than a bin past the end.
    const i = Math.min(Math.floor((v - min) / width), maxBins - 1);
    bins[i].count += 1;
  }
  return bins;
}

/**
 * Index of the bar a value falls in: the last bar that starts at or below
 * it (-1 if it is below the first). Used to mark the p95 bar. An
 * interpolated p95 such as 12 lands on the 10 bar when the bars are 0, 4,
 * 10, 14.
 */
export function binIndexOf(bins: Bin[], value: number): number {
  let index = -1;
  bins.forEach((b, i) => { if (b.from <= value) index = i; });
  return index;
}

function fmtNum(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
