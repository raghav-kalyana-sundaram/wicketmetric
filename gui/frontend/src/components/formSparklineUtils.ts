/**
 * Pure helpers for FormSparkline — separate file for React Fast Refresh.
 */

export type Trend = "up" | "down" | "stable";

export function detectTrend(values: number[]): Trend {
  if (values.length < 3) return "stable";

  const third = Math.max(1, Math.floor(values.length / 3));
  const firstSlice = values.slice(0, third);
  const lastSlice = values.slice(-third);

  const firstAvg = firstSlice.reduce((a, b) => a + b, 0) / firstSlice.length;
  const lastAvg = lastSlice.reduce((a, b) => a + b, 0) / lastSlice.length;

  const delta = lastAvg - firstAvg;
  const range = Math.max(...values) - Math.min(...values);

  const threshold = range > 0 ? range * 0.1 : 2;

  if (delta > threshold) return "up";
  if (delta < -threshold) return "down";
  return "stable";
}

/**
 * Trend from slope over the last N points (e.g. last 10 innings).
 */
export function detectTrendFromLastN(
  values: number[],
  lastN: number = 10,
): Trend {
  const slice = values.slice(-lastN);
  if (slice.length < 2) return "stable";
  const first = slice[0];
  const last = slice[slice.length - 1];
  const slope = (last - first) / (slice.length - 1);
  const threshold = 0.4;
  if (slope > threshold) return "up";
  if (slope < -threshold) return "down";
  return "stable";
}
