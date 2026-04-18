/**
 * TypeScript types matching the Hornet FastAPI response DTOs.
 *
 * These are the shapes returned by the API at localhost:8000.
 * Keep in sync with src/hornet/domain/ and src/hornet/api/routes/.
 */

// --- Enums ---

export type AlertTier = "WATCH" | "ALERT" | "ESCALATE";

export type DensityMode = "overview" | "analyst" | "research";

export type Frequency =
  | "daily"
  | "weekly"
  | "monthly"
  | "quarterly"
  | "annual"
  | "forecast";

export type PipelineStatus = "running" | "completed" | "failed";

export type RunType = "daily" | "manual" | "backfill";

export type TemplateName = "country_narrative" | "alert_rationale";

// --- API Response Types ---

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  database: "ok" | "unreachable";
  error?: string;
}

export interface Country {
  iso3: string;
  iso2: string;
  name: string;
  region: string | null;
  income_group: string | null;
}

export interface DimensionScore {
  dimension: string;
  value: number | null;
  n_series_used: number;
  n_concepts: number;
}

export interface NewsHeat {
  sigma: number;
  volume_ratio: number;
}

export interface ScoreResult {
  country_iso3: string;
  run_id: string;
  scored_at: string;
  composite: number | null;
  coverage_fraction: number;
  dimensions: Record<string, DimensionScore>;
  news_heat: NewsHeat | null;
}

export interface AlertRecord {
  country_iso3: string;
  run_id: string;
  evaluated_at: string;
  composite: number | null;
  coverage_fraction: number;
  raw_tier: AlertTier | null;
  effective_tier: AlertTier | null;
  streak_length: number;
  velocity: number | null;
  modifiers_applied: string[];
}

export interface QualityIssue {
  check_name: string;
  severity: string;
  country_iso3: string | null;
  indicator_code: string | null;
  source_id: string | null;
  run_id: string;
  detected_at: string;
  message: string;
  detail: Record<string, unknown> | null;
}

export interface PipelineRun {
  run_id: string;
  run_type: RunType;
  started_at: string;
  completed_at: string | null;
  status: PipelineStatus;
  stages_completed: string[];
  n_countries_scored: number;
  n_escalate: number;
  n_alert: number;
  n_watch: number;
  error_message: string | null;
}

export interface CitationDetail {
  ref_number: number;
  country_iso3: string;
  indicator_code: string;
  source_id: string;
  date: string;
  value: number;
  vintage: string;
  display_label: string;
}

export interface Narrative {
  response_id: string;
  run_id: string;
  country_iso3: string;
  template_name: TemplateName;
  task_type: string;
  provider_id: string;
  model_id: string;
  content: string;
  citations_used: CitationDetail[];
  citations_available_count: number;
  ungrounded_claims: string[];
  grounding_score: number;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  generated_at: string;
}

export interface Observation {
  country_iso3: string;
  indicator_code: string;
  source_id: string;
  date: string;
  value: number;
  frequency: Frequency;
  vintage: string;
}

// --- Derived / UI types ---

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
  WATCH: 0,
  ALERT: 1,
  ESCALATE: 2,
};
