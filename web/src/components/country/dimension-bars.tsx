/**
 * Horizontal bar chart showing the 4 scoring dimensions.
 *
 * Each bar is 0-100 with color coding. Shows in Analyst+ density.
 */

"use client";

import type { DimensionScore } from "@/lib/types";
import { DIMENSION_LABELS, DIMENSION_ORDER } from "@/lib/types";
import { cn } from "@/lib/utils";

interface DimensionBarsProps {
  dimensions: Record<string, DimensionScore>;
  className?: string;
}

function barColor(value: number): string {
  const s = value * 100;
  if (s >= 70) return "bg-red-500";
  if (s >= 50) return "bg-amber-500";
  if (s >= 30) return "bg-yellow-500";
  return "bg-green-500";
}

export function DimensionBars({ dimensions, className }: DimensionBarsProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {DIMENSION_ORDER.map((key) => {
        const dim = dimensions[key];
        if (!dim) return null;
        const value = dim.value;
        const display = value != null ? Math.round(value * 100) : null;

        return (
          <div key={key} className="flex items-center gap-2">
            <span className="w-28 text-xs text-muted-foreground truncate">
              {DIMENSION_LABELS[key] ?? key}
            </span>
            <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
              {value != null && (
                <div
                  className={cn("h-full rounded-full transition-all duration-500", barColor(value))}
                  style={{ width: `${Math.max(value * 100, 2)}%` }}
                />
              )}
            </div>
            <span className="w-8 text-xs font-mono text-right tabular-nums">
              {display ?? "--"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
