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
