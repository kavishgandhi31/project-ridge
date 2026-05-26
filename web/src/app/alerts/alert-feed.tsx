/**
 * Alert feed page showing all active alerts sorted by severity.
 *
 * Groups by tier (ESCALATE, ALERT, WATCH) with expandable detail cards.
 */

"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useAlerts, useCountries } from "@/lib/api/hooks";
import { useDensity } from "@/lib/density";
import { formatRelativeTime, formatScore, tierBgColor } from "@/lib/format";
import type { AlertRecord, AlertTier } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ChevronRight, TrendingUp, Zap, Eye } from "lucide-react";

const TIER_CONFIG: Record<AlertTier, { icon: typeof Zap; label: string }> = {
  escalate: { icon: Zap, label: "Escalate" },
  alert: { icon: TrendingUp, label: "Alert" },
  watch: { icon: Eye, label: "Watch" },
};

const TIER_ORDER: AlertTier[] = ["escalate", "alert", "watch"];

export function AlertFeed() {
  const { data: alerts, isLoading } = useAlerts({ limit: 500 });
  const { data: countries } = useCountries();
  const { showAtLeast } = useDensity();
  const [expandedTier, setExpandedTier] = useState<AlertTier | null>(null);

  const countryNames = new Map(countries?.map((c) => [c.iso3, c.name]) ?? []);

  // Group alerts by effective tier
  const grouped = new Map<AlertTier, AlertRecord[]>();
  if (alerts) {
    for (const a of alerts) {
      if (a.effective_tier) {
        const list = grouped.get(a.effective_tier) ?? [];
        list.push(a);
        grouped.set(a.effective_tier, list);
      }
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-muted animate-pulse" />
        ))}
      </div>
    );
  }

  if (!alerts || alerts.length === 0) {
    return (
      <p className="text-center text-sm text-muted-foreground py-12">
        No active alerts.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {TIER_ORDER.map((tier) => {
        const items = grouped.get(tier);
        if (!items || items.length === 0) return null;
        const { icon: Icon, label } = TIER_CONFIG[tier];
        const isExpanded = expandedTier === tier;

        return (
          <div key={tier} className="space-y-2">
            {/* Tier header */}
            <button
              type="button"
              onClick={() => setExpandedTier(isExpanded ? null : tier)}
              className="flex items-center gap-2 w-full text-left"
            >
              <Icon className={cn("h-4 w-4", tierBgColor(tier).split(" ")[0].replace("bg-", "text-"))} />
              <span className="font-semibold text-sm">{label}</span>
              <Badge variant="secondary" className={cn("text-xs", tierBgColor(tier))}>
                {items.length}
              </Badge>
              <ChevronRight
                className={cn(
                  "h-4 w-4 ml-auto transition-transform text-muted-foreground",
                  isExpanded && "rotate-90"
                )}
              />
            </button>

            {/* Alert cards */}
            <div className="space-y-2">
              {(isExpanded ? items : items.slice(0, 5)).map((alert) => (
                <AlertCard
                  key={`${alert.country_iso3}-${alert.run_id}`}
                  alert={alert}
                  countryName={countryNames.get(alert.country_iso3) ?? alert.country_iso3}
                  showDetail={showAtLeast("analyst")}
                />
              ))}
              {!isExpanded && items.length > 5 && (
                <button
                  type="button"
                  onClick={() => setExpandedTier(tier)}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors ml-6"
                >
                  Show {items.length - 5} more...
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AlertCard({
  alert,
  countryName,
  showDetail,
}: {
  alert: AlertRecord;
  countryName: string;
  showDetail: boolean;
}) {
  return (
    <Link href={`/countries/${alert.country_iso3}`}>
      <Card className="hover:shadow-sm transition-shadow">
        <CardContent className="p-3 flex items-center gap-4">
          {/* Country */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm truncate">{countryName}</span>
              <span className="text-xs text-muted-foreground font-mono">
                {alert.country_iso3}
              </span>
            </div>
            {showDetail && (
              <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
                <span>Score: {formatScore(alert.composite)}</span>
                {alert.streak_length > 1 && (
                  <span>Streak: {alert.streak_length} runs</span>
                )}
                {alert.velocity != null && (
                  <span>Velocity: {alert.velocity.toFixed(3)}</span>
                )}
              </div>
            )}
          </div>

          {/* Modifiers */}
          {showDetail && alert.modifiers_applied.length > 0 && (
            <div className="hidden sm:flex gap-1">
              {alert.modifiers_applied.map((m) => (
                <Badge key={m} variant="outline" className="text-[10px]">
                  {m}
                </Badge>
              ))}
            </div>
          )}

          {/* Tier badge */}
          <Badge
            variant="secondary"
            className={cn("text-[10px] shrink-0", tierBgColor(alert.effective_tier))}
          >
            {alert.effective_tier?.toUpperCase()}
          </Badge>

          {/* Timestamp */}
          <span className="text-[11px] text-muted-foreground whitespace-nowrap">
            {formatRelativeTime(alert.evaluated_at)}
          </span>
        </CardContent>
      </Card>
    </Link>
  );
}
