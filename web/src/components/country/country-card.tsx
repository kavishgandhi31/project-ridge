/**
 * Country card for the home grid.
 *
 * Adapts to density mode:
 * - Overview: score gauge + tier badge + country name
 * - Analyst: + dimension bars + scored_at timestamp
 * - Research: + coverage fraction + news heat + series counts
 */

"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ScoreGauge } from "@/components/country/score-gauge";
import { DimensionBars } from "@/components/country/dimension-bars";
import { useDensity } from "@/lib/density";
import { formatPercent, formatRelativeTime, tierBgColor } from "@/lib/format";
import type { CountryWithScore } from "@/lib/types";
import { cn } from "@/lib/utils";

interface CountryCardProps {
  country: CountryWithScore;
}

export function CountryCard({ country }: CountryCardProps) {
  const { showAtLeast } = useDensity();
  const { score, alert } = country;
  const tier = alert?.effective_tier;

  return (
    <Link href={`/countries/${country.iso3}`}>
      <Card className="group hover:shadow-md transition-shadow cursor-pointer h-full">
        <CardContent className="p-4">
          {/* Header row: name + tier badge */}
          <div className="flex items-start justify-between gap-2 mb-3">
            <div className="min-w-0">
              <h3 className="font-semibold text-sm truncate group-hover:text-primary transition-colors">
                {country.name}
              </h3>
              <span className="text-xs text-muted-foreground font-mono">
                {country.iso3}
              </span>
            </div>
            {tier && (
              <Badge
                variant="secondary"
                className={cn("text-[10px] shrink-0", tierBgColor(tier))}
              >
                {tier.toUpperCase()}
              </Badge>
            )}
          </div>

          {/* Score gauge */}
          <div className="flex items-center gap-3">
            <ScoreGauge score={score?.composite ?? null} size={56} />
            <div className="flex-1 min-w-0">
              {showAtLeast("analyst") && score?.dimensions && (
                <DimensionBars dimensions={score.dimensions} />
              )}
              {!showAtLeast("analyst") && score?.composite != null && (
                <p className="text-xs text-muted-foreground">
                  Risk score
                </p>
              )}
            </div>
          </div>

          {/* Research details */}
          {showAtLeast("analyst") && score && (
            <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
              <span>Coverage: {formatPercent(score.coverage_fraction)}</span>
              <span>{formatRelativeTime(score.scored_at)}</span>
            </div>
          )}

          {showAtLeast("research") && score?.news_heat && (
            <div className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">
              News heat: {score.news_heat.sigma.toFixed(1)} sigma
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
