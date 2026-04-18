/**
 * Observations data table for Research density mode.
 *
 * Shows raw observation data with indicator codes, values, sources, dates.
 */

"use client";

import type { Observation } from "@/lib/types";
import { formatDate, formatObservationValue } from "@/lib/format";
import { getIndicatorLabel } from "@/lib/indicator-labels";

interface ObservationTableProps {
  observations: Observation[];
  className?: string;
}

export function ObservationTable({ observations, className }: ObservationTableProps) {
  if (observations.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        No observations available.
      </p>
    );
  }

  return (
    <div className={className}>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="px-3 py-2 text-left font-medium">Indicator</th>
              <th className="px-3 py-2 text-left font-medium">Source</th>
              <th className="px-3 py-2 text-right font-medium">Value</th>
              <th className="px-3 py-2 text-left font-medium">Date</th>
              <th className="px-3 py-2 text-left font-medium">Frequency</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((obs, i) => {
              const isForecast = obs.frequency === "forecast";
              return (
                <tr
                  key={`${obs.indicator_code}-${obs.date}-${i}`}
                  className={`border-b last:border-0 ${isForecast ? "opacity-60" : ""}`}
                >
                  <td className="px-3 py-1.5">{getIndicatorLabel(obs.indicator_code)}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">{obs.source_id}</td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums">
                    {formatObservationValue(obs.value, obs.indicator_code)}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">{formatDate(obs.date)}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {isForecast ? (
                      <span className="text-amber-600 dark:text-amber-400">forecast</span>
                    ) : (
                      obs.frequency
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
