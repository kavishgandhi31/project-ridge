/**
 * Circular score gauge showing composite risk score (0-100).
 *
 * Uses SVG arc. Color shifts green -> amber -> red as risk increases.
 */

"use client";

import { cn } from "@/lib/utils";

interface ScoreGaugeProps {
  score: number | null;
  size?: number;
  className?: string;
}

function scoreColorHex(score: number): string {
  if (score >= 70) return "#dc2626"; // red-600
  if (score >= 50) return "#d97706"; // amber-600
  if (score >= 30) return "#ca8a04"; // yellow-600
  return "#16a34a"; // green-600
}

export function ScoreGauge({ score, size = 64, className }: ScoreGaugeProps) {
  const displayScore = score != null ? Math.round(score * 100) : null;
  const fraction = score ?? 0;
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference * (1 - fraction);
  const color = displayScore != null ? scoreColorHex(displayScore) : "#a1a1aa";

  return (
    <div className={cn("relative inline-flex items-center justify-center", className)}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={4}
          className="text-muted"
        />
        {/* Score arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          className="transition-all duration-500"
        />
      </svg>
      <span
        className="absolute text-sm font-semibold tabular-nums"
        style={{ color }}
      >
        {displayScore ?? "--"}
      </span>
    </div>
  );
}
