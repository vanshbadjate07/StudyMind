import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { formatRelativeTime } from "./relativeTime";

const NOW = new Date("2026-06-15T12:00:00Z").getTime();

function isoAgo(seconds: number): string {
  return new Date(NOW - seconds * 1000).toISOString();
}

function isoFromNow(seconds: number): string {
  return new Date(NOW + seconds * 1000).toISOString();
}

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reads as 'just now' just under a minute ago", () => {
    expect(formatRelativeTime(isoAgo(59))).toBe("just now");
  });

  it("reads as '1 minute ago' just over a minute ago", () => {
    expect(formatRelativeTime(isoAgo(60))).toBe("1 minute ago");
  });

  it("reads as '1 hour ago' just over an hour ago", () => {
    expect(formatRelativeTime(isoAgo(60 * 60))).toBe("1 hour ago");
  });

  it("reads as '3 days ago' for a few days in the past", () => {
    expect(formatRelativeTime(isoAgo(60 * 60 * 24 * 3))).toBe("3 days ago");
  });

  it("reads as 'just now' for a timestamp a few seconds in the future (clock skew)", () => {
    expect(formatRelativeTime(isoFromNow(5))).toBe("just now");
  });

  it("reads as a forward-looking phrase for a timestamp well in the future, not 'just now'", () => {
    // Regression test: a large future skew used to silently collapse to
    // "just now" no matter how far ahead the timestamp was.
    const result = formatRelativeTime(isoFromNow(60 * 60 * 24 * 3));
    expect(result).not.toBe("just now");
    expect(result).toMatch(/^in /);
  });

  it("reads as a forward-looking phrase for a timestamp years in the future", () => {
    const result = formatRelativeTime(isoFromNow(60 * 60 * 24 * 365 * 5));
    expect(result).not.toBe("just now");
    expect(result).toMatch(/^in /);
  });
});
