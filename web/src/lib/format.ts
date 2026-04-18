/**
 * Formatting utilities for dates, numbers, and scores.
 */

/** Format a score as 0-100 with one decimal. */
export function formatScore(value: number | null | undefined): string {
  if (value == null) return "--";
  return (value * 100).toFixed(1);
}

/** Format a raw 0-1 fraction as a percentage string. */
export function formatPercent(value: number | null | undefined): string {
  if (value == null) return "--";
  return `${(value * 100).toFixed(0)}%`;
}

/** Format a number with appropriate precision for display. */
export function formatNumber(
  value: number | null | undefined,
  decimals = 2
): string {
  if (value == null) return "--";
  return value.toFixed(decimals);
}

/**
 * Format a snake_case region string as title case.
 * e.g. "southeast_asia" -> "Southeast Asia"
 */
export function formatRegion(region: string): string {
  return region
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** Format an ISO date string as "Jan 15, 2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Format an ISO datetime string as "Jan 15, 2026 10:30 AM". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Relative time: "2 hours ago", "5 minutes ago", etc. */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "--";
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;

  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;

  return formatDate(iso);
}

/** Get a CSS color class for an alert tier. */
export function tierColor(tier: string | null | undefined): string {
  switch (tier) {
    case "ESCALATE":
      return "text-red-600 dark:text-red-400";
    case "ALERT":
      return "text-amber-600 dark:text-amber-400";
    case "WATCH":
      return "text-blue-600 dark:text-blue-400";
    default:
      return "text-muted-foreground";
  }
}

/** Get a CSS background class for an alert tier badge. */
export function tierBgColor(tier: string | null | undefined): string {
  switch (tier) {
    case "ESCALATE":
      return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300";
    case "ALERT":
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300";
    case "WATCH":
      return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300";
    default:
      return "bg-muted text-muted-foreground";
  }
}

/**
 * Format an observation value with the appropriate unit for its indicator.
 *
 * Indicator codes follow conventions from source_indicators.yaml:
 * - Rates/yields/spreads (percent, DGS*, UST_*, TIPS_*, CPI_*, etc.) -> "33.20%"
 * - USD prices (GOLD, OIL_WTI, *_FUTURES, etc.) -> "$2,345.60"
 * - Index values (VIX, S&P, CLI, BCI) -> "4,512.30"
 * - Counts/ratios -> plain number
 */
export function formatObservationValue(
  value: number | null | undefined,
  indicatorCode: string
): string {
  if (value == null) return "--";

  // Percentage-unit indicators
  const pctPatterns = [
    "CPI_YOY", "GDP_GROWTH", "CURRENT_ACCOUNT_GDP", "GOVT_DEBT_GDP",
    "UNEMPLOYMENT", "TRADE_OPENNESS", "POLICY_RATE",
    "DGS2", "DGS10",
  ];
  const pctPrefixes = ["UST_", "TIPS_", "BREAKEVEN_", "SPREAD_"];
  const isPct =
    pctPatterns.includes(indicatorCode) ||
    pctPrefixes.some((p) => indicatorCode.startsWith(p)) ||
    indicatorCode.endsWith("_SPREAD") ||
    indicatorCode.endsWith("_YOY");

  if (isPct) return `${value.toFixed(2)}%`;

  // USD-denominated prices
  const usdIndicators = [
    "GOLD", "OIL_WTI", "DCOILBRENTEU", "NATGAS_HH", "COPPER",
  ];
  const isUSD =
    usdIndicators.includes(indicatorCode) ||
    indicatorCode.endsWith("_FUTURES");

  if (isUSD) {
    return `$${value.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  // Months-of-imports
  if (indicatorCode === "RESERVES_MONTHS_IMPORTS") {
    return `${value.toFixed(1)} mo`;
  }

  // FX rates
  if (indicatorCode.startsWith("FX_")) {
    return value.toFixed(4);
  }

  // Default: plain number with auto precision
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
  }
  return value.toFixed(2);
}

/**
 * Score color on a green (low risk) to red (high risk) scale.
 * Score is 0-1 where higher = more risk.
 */
export function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground";
  const s = score * 100;
  if (s >= 70) return "text-red-600 dark:text-red-400";
  if (s >= 50) return "text-amber-600 dark:text-amber-400";
  if (s >= 30) return "text-yellow-600 dark:text-yellow-400";
  return "text-green-600 dark:text-green-400";
}
