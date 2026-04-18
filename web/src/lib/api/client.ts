/**
 * Typed API client for the Hornet FastAPI backend.
 *
 * All requests go through Next.js Route Handlers (/api/proxy/...)
 * so the FastAPI URL stays internal. Server-side fetches go direct.
 */

import type {
  AlertRecord,
  AlertTier,
  Country,
  HealthResponse,
  Narrative,
  Observation,
  PipelineRun,
  QualityIssue,
  ScoreResult,
  TemplateName,
} from "@/lib/types";

// Server-side: hit FastAPI directly. Client-side: hit Next.js proxy.
const BACKEND_URL =
  process.env.HORNET_API_URL ?? "http://127.0.0.1:8000";

function isServer(): boolean {
  return typeof window === "undefined";
}

function baseUrl(): string {
  return isServer() ? BACKEND_URL : "";
}

function apiPath(path: string): string {
  const prefix = isServer() ? "" : "/api/proxy";
  return `${baseUrl()}${prefix}${path}`;
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(apiPath(path), isServer() ? BACKEND_URL : window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.set(k, v);
      }
    }
  }

  const res = await fetch(url.toString(), {
    headers: { "Content-Type": "application/json" },
    // Short cache for server components; client uses TanStack Query
    next: isServer() ? { revalidate: 30 } : undefined,
  });

  if (!res.ok) {
    throw new Error(`API ${path} returned ${res.status}: ${await res.text()}`);
  }

  return res.json() as Promise<T>;
}

// --- Endpoint functions ---

export function fetchHealth(): Promise<HealthResponse> {
  return get<HealthResponse>("/health");
}

export function fetchCountries(): Promise<Country[]> {
  return get<Country[]>("/countries");
}

export function fetchScores(params?: {
  country_iso3?: string;
  run_id?: string;
  limit?: number;
}): Promise<ScoreResult[]> {
  const p: Record<string, string> = {};
  if (params?.country_iso3) p.country_iso3 = params.country_iso3;
  if (params?.run_id) p.run_id = params.run_id;
  if (params?.limit) p.limit = String(params.limit);
  return get<ScoreResult[]>("/scores", p);
}

export function fetchAlerts(params?: {
  country_iso3?: string;
  run_id?: string;
  effective_tier?: AlertTier;
  limit?: number;
}): Promise<AlertRecord[]> {
  const p: Record<string, string> = {};
  if (params?.country_iso3) p.country_iso3 = params.country_iso3;
  if (params?.run_id) p.run_id = params.run_id;
  if (params?.effective_tier) p.effective_tier = params.effective_tier;
  if (params?.limit) p.limit = String(params.limit);
  return get<AlertRecord[]>("/alerts", p);
}

export function fetchQualityIssues(params?: {
  run_id?: string;
  country_iso3?: string;
  check_name?: string;
  limit?: number;
}): Promise<QualityIssue[]> {
  const p: Record<string, string> = {};
  if (params?.run_id) p.run_id = params.run_id;
  if (params?.country_iso3) p.country_iso3 = params.country_iso3;
  if (params?.check_name) p.check_name = params.check_name;
  if (params?.limit) p.limit = String(params.limit);
  return get<QualityIssue[]>("/quality/issues", p);
}

export function fetchPipelineRuns(params?: {
  limit?: number;
}): Promise<PipelineRun[]> {
  const p: Record<string, string> = {};
  if (params?.limit) p.limit = String(params.limit);
  return get<PipelineRun[]>("/pipeline/runs", p);
}

export function fetchPipelineRun(runId: string): Promise<PipelineRun> {
  return get<PipelineRun>(`/pipeline/runs/${encodeURIComponent(runId)}`);
}

export function fetchNarratives(params?: {
  country_iso3?: string;
  run_id?: string;
  template_name?: TemplateName;
  limit?: number;
}): Promise<Narrative[]> {
  const p: Record<string, string> = {};
  if (params?.country_iso3) p.country_iso3 = params.country_iso3;
  if (params?.run_id) p.run_id = params.run_id;
  if (params?.template_name) p.template_name = params.template_name;
  if (params?.limit) p.limit = String(params.limit);
  return get<Narrative[]>("/narratives", p);
}

export function fetchObservations(params?: {
  country_iso3?: string;
  indicator_code?: string;
  source_id?: string;
  start_date?: string;
  limit?: number;
}): Promise<Observation[]> {
  const p: Record<string, string> = {};
  if (params?.country_iso3) p.country_iso3 = params.country_iso3;
  if (params?.indicator_code) p.indicator_code = params.indicator_code;
  if (params?.source_id) p.source_id = params.source_id;
  if (params?.start_date) p.start_date = params.start_date;
  if (params?.limit) p.limit = String(params.limit);
  return get<Observation[]>("/observations", p);
}
