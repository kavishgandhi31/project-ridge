/**
 * Country grid for the home page.
 *
 * Fetches countries, scores, and alerts via TanStack Query,
 * joins them client-side, and renders a filterable/sortable grid.
 */

"use client";

import { useMemo, useState } from "react";
import { useCountries, useScores, useAlerts } from "@/lib/api/hooks";
import { CountryCard } from "@/components/country/country-card";
import type { AlertTier, CountryWithScore } from "@/lib/types";
import { TIER_SEVERITY } from "@/lib/types";

type SortKey = "name" | "score" | "tier";

const TIER_FILTERS: { value: AlertTier | "ALL"; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "ESCALATE", label: "Escalate" },
  { value: "ALERT", label: "Alert" },
  { value: "WATCH", label: "Watch" },
];

export function CountryGrid() {
  const { data: countries, isLoading: loadingCountries } = useCountries();
  const { data: scores, isLoading: loadingScores } = useScores({ limit: 500 });
  const { data: alerts, isLoading: loadingAlerts } = useAlerts({ limit: 500 });

  const [search, setSearch] = useState("");
  const [tierFilter, setTierFilter] = useState<AlertTier | "ALL">("ALL");
  const [sortBy, setSortBy] = useState<SortKey>("score");

  const isLoading = loadingCountries || loadingScores || loadingAlerts;

  // Join countries with their latest scores and alerts
  const enriched: CountryWithScore[] = useMemo(() => {
    if (!countries) return [];

    // Build lookup maps: most recent score/alert per country
    const scoreMap = new Map<string, (typeof scores extends (infer T)[] | undefined ? T : never)>();
    if (scores) {
      for (const s of scores) {
        if (!scoreMap.has(s.country_iso3)) {
          scoreMap.set(s.country_iso3, s);
        }
      }
    }

    const alertMap = new Map<string, (typeof alerts extends (infer T)[] | undefined ? T : never)>();
    if (alerts) {
      for (const a of alerts) {
        if (!alertMap.has(a.country_iso3)) {
          alertMap.set(a.country_iso3, a);
        }
      }
    }

    return countries.map((c) => ({
      ...c,
      score: scoreMap.get(c.iso3) ?? null,
      alert: alertMap.get(c.iso3) ?? null,
    }));
  }, [countries, scores, alerts]);

  // Filter and sort
  const displayed = useMemo(() => {
    let result = enriched;

    // Text search
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          c.iso3.toLowerCase().includes(q) ||
          (c.region?.toLowerCase().includes(q) ?? false)
      );
    }

    // Tier filter
    if (tierFilter !== "ALL") {
      result = result.filter((c) => c.alert?.effective_tier === tierFilter);
    }

    // Sort
    result = [...result].sort((a, b) => {
      switch (sortBy) {
        case "name":
          return a.name.localeCompare(b.name);
        case "score": {
          const sa = a.score?.composite ?? -1;
          const sb = b.score?.composite ?? -1;
          return sb - sa; // Highest risk first
        }
        case "tier": {
          const ta = a.alert?.effective_tier
            ? TIER_SEVERITY[a.alert.effective_tier]
            : -1;
          const tb = b.alert?.effective_tier
            ? TIER_SEVERITY[b.alert.effective_tier]
            : -1;
          if (tb !== ta) return tb - ta;
          // Within same tier, sort by score
          return (b.score?.composite ?? 0) - (a.score?.composite ?? 0);
        }
        default:
          return 0;
      }
    });

    return result;
  }, [enriched, search, tierFilter, sortBy]);

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {Array.from({ length: 12 }).map((_, i) => (
          <div
            key={i}
            className="h-40 rounded-xl bg-muted animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <input
          type="text"
          placeholder="Search countries..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 w-64 rounded-md border bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />

        {/* Tier filter */}
        <div className="flex items-center gap-1 rounded-md bg-muted p-0.5">
          {TIER_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setTierFilter(value)}
              className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                tierFilter === value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Sort */}
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortKey)}
          className="h-9 rounded-md border bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value="score">Sort: Risk Score</option>
          <option value="tier">Sort: Alert Tier</option>
          <option value="name">Sort: Name</option>
        </select>

        {/* Count */}
        <span className="text-xs text-muted-foreground ml-auto">
          {displayed.length} countries
        </span>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {displayed.map((country) => (
          <CountryCard key={country.iso3} country={country} />
        ))}
      </div>

      {displayed.length === 0 && (
        <p className="text-center text-sm text-muted-foreground py-12">
          No countries match your filters.
        </p>
      )}
    </div>
  );
}
