/**
 * TypeScript types matching the Ridge FastAPI response DTOs.
 *
 * Keep in sync with api/src/ridge/domain/ and api/src/ridge/api/routes/.
 */

import type {
  AlertTier,
  Frequency,
  PipelineStatus,
  RunType,
  TemplateName,
} from "./enums";

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
