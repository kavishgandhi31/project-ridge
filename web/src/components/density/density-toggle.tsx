/**
 * Density mode toggle.
 *
 * Three modes: Overview / Analyst / Research.
 * Sits in the top nav bar. Uses plain buttons instead of ToggleGroup
 * for simplicity and full control over single-select behavior.
 */

"use client";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDensity } from "@/lib/density";
import { cn } from "@/lib/utils";
import type { DensityMode } from "@/lib/types";
import { LayoutList, Table2, BookOpen, type LucideIcon } from "lucide-react";

const MODES: { value: DensityMode; label: string; icon: LucideIcon; tip: string }[] = [
  {
    value: "overview",
    label: "Overview",
    icon: LayoutList,
    tip: "Executive summary -- scores, tiers, headlines",
  },
  {
    value: "analyst",
    label: "Analyst",
    icon: Table2,
    tip: "Full working view -- dimensions, charts, narratives",
  },
  {
    value: "research",
    label: "Research",
    icon: BookOpen,
    tip: "Everything -- raw data, citation tables, metadata",
  },
];

export function DensityToggle() {
  const { density, setDensity } = useDensity();

  return (
    <div className="flex items-center gap-0.5 rounded-lg bg-muted p-0.5">
      {MODES.map(({ value, label, icon: Icon, tip }) => (
        <Tooltip key={value}>
          <TooltipTrigger
            onClick={() => setDensity(value)}
            aria-label={label}
            aria-pressed={density === value}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
              density === value
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{label}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <p>{tip}</p>
          </TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
