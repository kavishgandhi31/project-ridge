/**
 * TanStack Query hooks for client-side data fetching.
 *
 * These wrap the API client functions with caching, deduplication,
 * and background refetch. Use in Client Components only.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import {
  fetchAlerts,
  fetchCountries,
  fetchHealth,
  fetchNarratives,
  fetchObservations,
  fetchPipelineRuns,
  fetchScores,
} from "./client";
import type { AlertTier, TemplateName } from "@/lib/types";

// Stale time: 30s for scores/alerts (changes with pipeline runs),
// 5min for countries (rarely changes).
const STALE_SHORT = 30_000;
const STALE_LONG = 5 * 60_000;

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    staleTime: STALE_SHORT,
    refetchInterval: 60_000,
  });
}

export function useCountries() {
  return useQuery({
    queryKey: ["countries"],
    queryFn: fetchCountries,
    staleTime: STALE_LONG,
  });
}

export function useScores(params?: {
  country_iso3?: string;
  run_id?: string;
  limit?: number;
}) {
  return useQuery({
    queryKey: ["scores", params],
    queryFn: () => fetchScores(params),
    staleTime: STALE_SHORT,
  });
}

export function useAlerts(params?: {
  country_iso3?: string;
  run_id?: string;
  effective_tier?: AlertTier;
  limit?: number;
}) {
  return useQuery({
    queryKey: ["alerts", params],
    queryFn: () => fetchAlerts(params),
    staleTime: STALE_SHORT,
  });
}

export function usePipelineRuns(params?: { limit?: number }) {
  return useQuery({
    queryKey: ["pipeline-runs", params],
    queryFn: () => fetchPipelineRuns(params),
    staleTime: STALE_SHORT,
  });
}

export function useNarratives(params?: {
  country_iso3?: string;
  run_id?: string;
  template_name?: TemplateName;
  limit?: number;
}) {
  return useQuery({
    queryKey: ["narratives", params],
    queryFn: () => fetchNarratives(params),
    staleTime: STALE_SHORT,
    enabled: params?.country_iso3 !== undefined,
  });
}

export function useObservations(params?: {
  country_iso3?: string;
  indicator_code?: string;
  source_id?: string;
  start_date?: string;
  limit?: number;
}) {
  return useQuery({
    queryKey: ["observations", params],
    queryFn: () => fetchObservations(params),
    staleTime: STALE_SHORT,
    enabled: params?.country_iso3 !== undefined,
  });
}
