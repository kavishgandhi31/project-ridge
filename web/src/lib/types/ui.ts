import type { AlertTier } from "./enums";
import type { AlertRecord, Country, ScoreResult } from "./api";

/** Country enriched with its latest score and alert tier for the home grid. */
export interface CountryWithScore extends Country {
  score: ScoreResult | null;
  alert: AlertRecord | null;
}

/** The four scoring dimensions in display order. */
export const DIMENSION_ORDER = [
  "growth_momentum",
  "external_balance",
  "monetary_stance",
  "risk_sentiment",
] as const;

export const DIMENSION_LABELS: Record<string, string> = {
  growth_momentum: "Growth Momentum",
  external_balance: "External Balance",
  monetary_stance: "Monetary Stance",
  risk_sentiment: "Risk Sentiment",
};

export const TIER_SEVERITY: Record<AlertTier, number> = {
  watch: 0,
  alert: 1,
  escalate: 2,
};
