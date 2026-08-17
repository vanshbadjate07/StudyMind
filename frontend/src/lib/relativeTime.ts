const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["week", 60 * 60 * 24 * 7],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
];

const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "3 days ago", "2 hours ago", "just now". Also handles a timestamp in the
 * future (e.g. clock skew) — anything within a minute of now in either
 * direction reads as "just now"; beyond that it reads as "in 3 days" rather
 * than silently collapsing to "just now" regardless of how far in the
 * future the timestamp is. */
export function formatRelativeTime(isoDate: string): string {
  const seconds = (Date.now() - new Date(isoDate).getTime()) / 1000;
  const absSeconds = Math.abs(seconds);
  if (absSeconds < 60) return "just now";
  for (const [unit, unitSeconds] of UNITS) {
    if (absSeconds >= unitSeconds) {
      const magnitude = Math.floor(absSeconds / unitSeconds);
      return formatter.format(seconds > 0 ? -magnitude : magnitude, unit);
    }
  }
  const magnitude = Math.floor(absSeconds / 60);
  return formatter.format(seconds > 0 ? -magnitude : magnitude, "minute");
}
