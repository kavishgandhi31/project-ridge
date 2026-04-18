/**
 * Country dashboard -- the core page of Hornet.
 *
 * Density-aware:
 * - Overview: score gauge, tier, headline from narrative
 * - Analyst: + dimension breakdown, indicator charts, full narrative with citations
 * - Research: + observation table, citation metadata, grounding score
 *
 * Ask panel visible at all densities (compact in Overview, full in Analyst+).
 */

"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScoreGauge } from "@/components/country/score-gauge";
import { DimensionBars } from "@/components/country/dimension-bars";
import { TimeSeriesChart } from "@/components/charts/time-series-chart";
import { NarrativeBlock } from "@/components/narrative/narrative-block";
import { AskPanel } from "@/components/ask/ask-panel";
import { useCountries, useScores, useAlerts, useNarratives, useObservations } from "@/lib/api/hooks";
import { useDensity } from "@/lib/density";
import { formatScore, formatPercent, formatRegion, formatRelativeTime, tierBgColor, tierColor } from "@/lib/format";
import { getIndicatorLabel } from "@/lib/indicator-labels";
import type { Observation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ArrowLeft } from "lucide-react";

interface CountryDashboardProps {
  iso3: string;
}

export function CountryDashboard({ iso3 }: CountryDashboardProps) {
  const { showAtLeast, density } = useDensity();

  const { data: countries } = useCountries();
  const { data: scores } = useScores({ country_iso3: iso3, limit: 10 });
  const { data: alerts } = useAlerts({ country_iso3: iso3, limit: 10 });
  const { data: narratives } = useNarratives({ country_iso3: iso3, limit: 5 });
  const { data: observations } = useObservations({
    country_iso3: iso3,
    limit: 500,
  });

  const country = countries?.find((c) => c.iso3 === iso3);
  const latestScore = scores?.[0] ?? null;
  const latestAlert = alerts?.[0] ?? null;
  const latestNarrative = narratives?.find(
    (n) => n.template_name === "country_narrative"
  ) ?? null;
  const latestRationale = narratives?.find(
    (n) => n.template_name === "alert_rationale"
  ) ?? null;

  const tier = latestAlert?.effective_tier;

  // Group observations by indicator for charts -- exclude forecasts
  const indicatorGroups = new Map<string, Observation[]>();
  if (observations) {
    for (const obs of observations) {
      if (obs.frequency === "forecast") continue;
      const existing = indicatorGroups.get(obs.indicator_code) ?? [];
      existing.push(obs);
      indicatorGroups.set(obs.indicator_code, existing);
    }
  }

  // Pick key indicators for chart display (top 6 by data count)
  const chartIndicators = [...indicatorGroups.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 6);

  const CHART_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"];

  return (
    <div className="container mx-auto px-4 py-6 space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/" className="hover:text-foreground transition-colors inline-flex items-center gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Dashboard
        </Link>
        <span>/</span>
        <span className="text-foreground font-medium">
          {country?.name ?? iso3}
        </span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {country?.name ?? iso3}
          </h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground">
            {country?.region && <span>{formatRegion(country.region)}</span>}
            {country?.income_group && (
              <>
                <span className="text-border">|</span>
                <span>{country.income_group}</span>
              </>
            )}
          </div>
        </div>
        {tier && (
          <Badge
            variant="secondary"
            className={cn("text-sm px-3 py-1", tierBgColor(tier))}
          >
            {tier}
          </Badge>
        )}
      </div>

      {/* Score overview row */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Score card */}
        <Card className="md:col-span-4">
          <CardContent className="p-6 flex items-center gap-6">
            <ScoreGauge score={latestScore?.composite ?? null} size={80} />
            <div className="space-y-1">
              <div className="text-2xl font-semibold tabular-nums">
                {formatScore(latestScore?.composite)}
              </div>
              <div className="text-xs text-muted-foreground">Composite Risk Score</div>
              {latestScore && (
                <div className="text-xs text-muted-foreground">
                  Coverage: {formatPercent(latestScore.coverage_fraction)}
                </div>
              )}
              {latestScore && (
                <div className="text-xs text-muted-foreground">
                  {formatRelativeTime(latestScore.scored_at)}
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Dimensions card -- Analyst+ */}
        {showAtLeast("analyst") && latestScore?.dimensions && (
          <Card className="md:col-span-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Dimensions</CardTitle>
            </CardHeader>
            <CardContent className="pb-4">
              <DimensionBars dimensions={latestScore.dimensions} />
            </CardContent>
          </Card>
        )}

        {/* Alert info card -- Analyst+ */}
        {showAtLeast("analyst") && latestAlert && (
          <Card className="md:col-span-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Alert Status</CardTitle>
            </CardHeader>
            <CardContent className="pb-4 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Effective Tier</span>
                <span className={cn("font-semibold", tierColor(tier))}>
                  {tier ?? "None"}
                </span>
              </div>
              {latestAlert.raw_tier !== latestAlert.effective_tier && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Raw Tier</span>
                  <span>{latestAlert.raw_tier ?? "None"}</span>
                </div>
              )}
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Streak</span>
                <span className="tabular-nums">{latestAlert.streak_length} runs</span>
              </div>
              {latestAlert.velocity != null && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Velocity</span>
                  <span className="tabular-nums">{latestAlert.velocity.toFixed(3)}</span>
                </div>
              )}
              {latestAlert.modifiers_applied.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {latestAlert.modifiers_applied.map((m) => (
                    <Badge key={m} variant="outline" className="text-[10px]">
                      {m}
                    </Badge>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Narrative + Ask panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Narrative */}
        <div className="lg:col-span-2 space-y-4">
          {latestNarrative && (
            <NarrativeBlock narrative={latestNarrative} density={density} />
          )}
          {showAtLeast("analyst") && latestRationale && tier === "ESCALATE" && (
            <>
              <Separator />
              <NarrativeBlock
                narrative={latestRationale}
                density={density}
                title="Escalation Rationale"
              />
            </>
          )}
        </div>

        {/* Ask panel */}
        <div className="lg:col-span-1">
          <AskPanel countryIso3={iso3} countryName={country?.name ?? iso3} />
        </div>
      </div>

      {/* Indicator charts -- Analyst+ */}
      {showAtLeast("analyst") && chartIndicators.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Key Indicators</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue={chartIndicators[0]?.[0]}>
              <TabsList>
                {chartIndicators.map(([code]) => (
                  <TabsTrigger key={code} value={code} className="text-xs">
                    {getIndicatorLabel(code)}
                  </TabsTrigger>
                ))}
              </TabsList>
              {chartIndicators.map(([code, obs], i) => (
                <TabsContent key={code} value={code}>
                  <TimeSeriesChart
                    observations={obs}
                    indicatorCode={code}
                    height={250}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                  />
                </TabsContent>
              ))}
            </Tabs>
          </CardContent>
        </Card>
      )}

    </div>
  );
}
