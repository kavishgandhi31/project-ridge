/**
 * Generic time series line chart using Recharts.
 *
 * Renders observation data as a line chart with proper date axis.
 * Used on country dashboard for indicator history.
 */

"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { formatObservationValue } from "@/lib/format";
import type { Observation } from "@/lib/types";

interface TimeSeriesChartProps {
  observations: Observation[];
  /** Indicator code for unit formatting in tooltips and Y-axis. */
  indicatorCode?: string;
  height?: number;
  color?: string;
  className?: string;
}

export function TimeSeriesChart({
  observations,
  indicatorCode,
  height = 200,
  color = "#2563eb",
  className,
}: TimeSeriesChartProps) {
  const code = indicatorCode ?? observations[0]?.indicator_code ?? "";

  // Sort by date ascending, take latest vintage per date
  const data = [...observations]
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((obs) => ({
      date: obs.date,
      value: obs.value,
      label: new Date(obs.date).toLocaleDateString("en-US", {
        month: "short",
        year: "2-digit",
      }),
    }));

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted-foreground"
        style={{ height }}
      >
        No data available
      </div>
    );
  }

  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10 }}
            className="text-muted-foreground"
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10 }}
            className="text-muted-foreground"
            width={55}
            tickFormatter={(v) => formatObservationValue(v, code)}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid hsl(var(--border))",
              backgroundColor: "hsl(var(--popover))",
              color: "hsl(var(--popover-foreground))",
            }}
            formatter={(value) => [
              formatObservationValue(Number(value), code),
              code,
            ]}
            labelFormatter={(label) => String(label)}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
