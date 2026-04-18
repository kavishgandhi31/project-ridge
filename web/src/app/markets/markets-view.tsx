/**
 * Markets overview page.
 *
 * Shows US Treasury yield curve, commodity prices, and key market indices.
 * Fetches data from the observations endpoint filtered by source/indicator.
 */

"use client";

import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useObservations } from "@/lib/api/hooks";
import { formatDate } from "@/lib/format";
import type { Observation } from "@/lib/types";

// --- Yield curve ---

// Canonical codes: most use UST_* but DGS10 and DGS2 kept their
// FRED codes from Phase 1 (they were the original pilot indicators).
const MATURITY_ORDER = [
  "UST_1M", "UST_3M", "UST_6M", "UST_1Y", "DGS2", "UST_3Y",
  "UST_5Y", "UST_7Y", "DGS10", "UST_20Y", "UST_30Y",
];

const MATURITY_LABELS: Record<string, string> = {
  UST_1M: "1M", UST_3M: "3M", UST_6M: "6M", UST_1Y: "1Y", DGS2: "2Y",
  UST_3Y: "3Y", UST_5Y: "5Y", UST_7Y: "7Y", DGS10: "10Y", UST_20Y: "20Y", UST_30Y: "30Y",
};

// --- Commodities ---

// Unit metadata from source_indicators.yaml
interface CommodityMeta {
  label: string;
  unit: string;
  format: (v: number) => string;
}

const fmtUSD = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtUSDInt = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
const fmtUSD4 = (v: number) => `$${v.toFixed(4)}`;

const COMMODITY_META: Record<string, CommodityMeta> = {
  GOLD:              { label: "Gold (spot)",     unit: "$/oz",     format: fmtUSD },
  OIL_WTI:           { label: "WTI Crude",       unit: "$/bbl",    format: fmtUSD },
  DCOILBRENTEU:      { label: "Brent Crude",     unit: "$/bbl",    format: fmtUSD },
  NATGAS_HH:         { label: "Nat Gas (HH)",    unit: "$/MMBtu",  format: fmtUSD },
  COPPER:            { label: "Copper",           unit: "$/mt",     format: fmtUSDInt },
  GOLD_FUTURES:      { label: "Gold Fut.",        unit: "$/oz",     format: fmtUSD },
  SILVER_FUTURES:    { label: "Silver Fut.",      unit: "$/oz",     format: fmtUSD },
  OIL_WTI_FUTURES:   { label: "WTI Fut.",         unit: "$/bbl",    format: fmtUSD },
  OIL_BRENT_FUTURES: { label: "Brent Fut.",       unit: "$/bbl",    format: fmtUSD },
  NATGAS_FUTURES:    { label: "Nat Gas Fut.",     unit: "$/MMBtu",  format: fmtUSD },
  COPPER_FUTURES:    { label: "Copper Fut.",      unit: "$/lb",     format: fmtUSD4 },
  WHEAT_FUTURES:     { label: "Wheat Fut.",       unit: "$/bu",     format: fmtUSD },
  CORN_FUTURES:      { label: "Corn Fut.",        unit: "$/bu",     format: fmtUSD },
  SOYBEAN_FUTURES:   { label: "Soybean Fut.",     unit: "$/bu",     format: fmtUSD },
};

const COMMODITY_CODES = Object.keys(COMMODITY_META);

export function MarketsView() {
  // Fetch from both FRED (spot) and yfinance (futures/equities)
  const { data: fredObs } = useObservations({
    source_id: "fred",
    country_iso3: "USA",
    limit: 2000,
  });
  const { data: yfinObs } = useObservations({
    source_id: "yfinance",
    country_iso3: "USA",
    limit: 2000,
  });

  // Merge both sources
  const allObs = useMemo(() => {
    return [...(fredObs ?? []), ...(yfinObs ?? [])];
  }, [fredObs, yfinObs]);

  return (
    <div className="space-y-6">
      <YieldCurveCard observations={allObs} />
      <SpreadBuilderCard observations={allObs} />
      <TreasuryHistoryCard observations={allObs} />
      <CommodityCard observations={allObs} />
    </div>
  );
}

function YieldCurveCard({ observations }: { observations: Observation[] }) {
  const latestByIndicator = useMemo(() => {
    const map = new Map<string, Observation>();
    for (const obs of observations) {
      if (MATURITY_ORDER.includes(obs.indicator_code) && !map.has(obs.indicator_code)) {
        map.set(obs.indicator_code, obs);
      }
    }
    return map;
  }, [observations]);

  const curveData = MATURITY_ORDER
    .filter((code) => latestByIndicator.has(code))
    .map((code) => ({
      maturity: MATURITY_LABELS[code] ?? code,
      yield: latestByIndicator.get(code)!.value,
    }));

  const asOfDate = latestByIndicator.size > 0
    ? formatDate(latestByIndicator.values().next().value!.date)
    : "";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium flex items-center justify-between">
          <span>US Treasury Yield Curve</span>
          {asOfDate && <span className="text-xs text-muted-foreground font-normal">As of {asOfDate}</span>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {curveData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={curveData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="maturity" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} unit="%" width={50} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                  border: "1px solid hsl(var(--border))",
                  backgroundColor: "hsl(var(--popover))",
                  color: "hsl(var(--popover-foreground))",
                }}
                formatter={(value) => [`${Number(value).toFixed(2)}%`, "Yield"]}
              />
              <Line
                type="monotone"
                dataKey="yield"
                stroke="#2563eb"
                strokeWidth={2}
                dot={{ r: 4, fill: "#2563eb" }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-12">
            No Treasury data available. Ensure the pipeline has run with FRED sources.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function TreasuryHistoryCard({ observations }: { observations: Observation[] }) {
  const [selectedMaturity, setSelectedMaturity] = useState("DGS10" as string);

  const historyData = useMemo(() => {
    return observations
      .filter((obs) => obs.indicator_code === selectedMaturity)
      .sort((a, b) => a.date.localeCompare(b.date))
      .map((obs) => ({
        date: new Date(obs.date).toLocaleDateString("en-US", { month: "short", year: "2-digit" }),
        yield: obs.value,
      }));
  }, [observations, selectedMaturity]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Treasury Yield History</CardTitle>
          <select
            value={selectedMaturity}
            onChange={(e) => setSelectedMaturity(e.target.value)}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            {MATURITY_ORDER.map((code) => (
              <option key={code} value={code}>
                {MATURITY_LABELS[code] ?? code}
              </option>
            ))}
          </select>
        </div>
      </CardHeader>
      <CardContent>
        {historyData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={historyData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} domain={["auto", "auto"]} unit="%" width={50} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                  border: "1px solid hsl(var(--border))",
                  backgroundColor: "hsl(var(--popover))",
                  color: "hsl(var(--popover-foreground))",
                }}
                formatter={(value) => [`${Number(value).toFixed(2)}%`, "Yield"]}
              />
              <Line type="monotone" dataKey="yield" stroke="#2563eb" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-12">
            No data for {MATURITY_LABELS[selectedMaturity] ?? selectedMaturity}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function CommodityCard({ observations }: { observations: Observation[] }) {
  const latestByCommodity = useMemo(() => {
    const map = new Map<string, Observation>();
    for (const obs of observations) {
      if (COMMODITY_CODES.includes(obs.indicator_code) && !map.has(obs.indicator_code)) {
        map.set(obs.indicator_code, obs);
      }
    }
    return map;
  }, [observations]);

  const commodityData = COMMODITY_CODES
    .filter((code) => latestByCommodity.has(code))
    .map((code) => {
      const meta = COMMODITY_META[code];
      const obs = latestByCommodity.get(code)!;
      return {
        code,
        label: meta.label,
        unit: meta.unit,
        formatted: meta.format(obs.value),
        date: obs.date,
      };
    });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Commodity Prices</CardTitle>
      </CardHeader>
      <CardContent>
        {commodityData.length > 0 ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {commodityData.map((item) => (
              <div key={item.code} className="p-3 rounded-lg bg-muted/50">
                <div className="text-xs text-muted-foreground mb-1">{item.label}</div>
                <div className="text-lg font-semibold tabular-nums">
                  {item.formatted}
                </div>
                <div className="text-[10px] text-muted-foreground mt-0.5">
                  {item.unit} &middot; {formatDate(item.date)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-12">
            No commodity data available. These are fetched via FRED/yfinance sources.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function SpreadBuilderCard({ observations }: { observations: Observation[] }) {
  const [longCode, setLongCode] = useState("DGS10" as string);
  const [shortCode, setShortCode] = useState("DGS2" as string);

  // Build time series keyed by date for each maturity
  const seriesByCode = useMemo(() => {
    const map = new Map<string, Map<string, number>>();
    for (const code of MATURITY_ORDER) {
      map.set(code, new Map());
    }
    for (const obs of observations) {
      const dateMap = map.get(obs.indicator_code);
      if (dateMap && !dateMap.has(obs.date)) {
        dateMap.set(obs.date, obs.value);
      }
    }
    return map;
  }, [observations]);

  // Compute spread: long - short, only on dates where both exist
  const spreadData = useMemo(() => {
    const longSeries = seriesByCode.get(longCode);
    const shortSeries = seriesByCode.get(shortCode);
    if (!longSeries || !shortSeries) return [];

    const points: { date: string; spread: number; label: string }[] = [];
    for (const [date, longVal] of longSeries) {
      const shortVal = shortSeries.get(date);
      if (shortVal !== undefined) {
        points.push({
          date,
          spread: longVal - shortVal,
          label: new Date(date).toLocaleDateString("en-US", { month: "short", year: "2-digit" }),
        });
      }
    }
    return points.sort((a, b) => a.date.localeCompare(b.date));
  }, [seriesByCode, longCode, shortCode]);

  const longLabel = MATURITY_LABELS[longCode] ?? longCode;
  const shortLabel = MATURITY_LABELS[shortCode] ?? shortCode;
  const latestSpread = spreadData.length > 0 ? spreadData[spreadData.length - 1].spread : null;

  // Auto-sort: if user picks long < short on the curve, swap the labels
  // but always show the actual arithmetic (long - short)
  const isInverted = MATURITY_ORDER.indexOf(longCode) < MATURITY_ORDER.indexOf(shortCode);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <CardTitle className="text-sm font-medium">
            Yield Spread: {longLabel} - {shortLabel}
          </CardTitle>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground">Long</label>
              <select
                value={longCode}
                onChange={(e) => setLongCode(e.target.value)}
                className="h-8 rounded-md border bg-background px-2 text-xs"
              >
                {MATURITY_ORDER.map((code) => (
                  <option key={code} value={code}>
                    {MATURITY_LABELS[code] ?? code}
                  </option>
                ))}
              </select>
            </div>
            <span className="text-muted-foreground text-sm">-</span>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground">Short</label>
              <select
                value={shortCode}
                onChange={(e) => setShortCode(e.target.value)}
                className="h-8 rounded-md border bg-background px-2 text-xs"
              >
                {MATURITY_ORDER.map((code) => (
                  <option key={code} value={code}>
                    {MATURITY_LABELS[code] ?? code}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        {latestSpread !== null && (
          <div className="flex items-baseline gap-2 mt-1">
            <span className={`text-2xl font-semibold tabular-nums ${latestSpread < 0 ? "text-red-600 dark:text-red-400" : "text-foreground"}`}>
              {latestSpread >= 0 ? "+" : ""}{(latestSpread * 100).toFixed(0)} bps
            </span>
            <span className="text-xs text-muted-foreground">
              ({latestSpread >= 0 ? "+" : ""}{latestSpread.toFixed(2)}%)
            </span>
            {isInverted && (
              <span className="text-[10px] text-amber-600 dark:text-amber-400">
                Inverted curve selection
              </span>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent>
        {longCode === shortCode ? (
          <p className="text-sm text-muted-foreground text-center py-12">
            Select two different maturities to see the spread.
          </p>
        ) : spreadData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={spreadData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis
                tick={{ fontSize: 11 }}
                domain={["auto", "auto"]}
                unit="%"
                width={55}
              />
              {/* Zero line */}
              <CartesianGrid horizontal={false} vertical={false} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                  border: "1px solid hsl(var(--border))",
                  backgroundColor: "hsl(var(--popover))",
                  color: "hsl(var(--popover-foreground))",
                }}
                formatter={(value) => {
                  const v = Number(value);
                  const bps = (v * 100).toFixed(0);
                  return [`${v >= 0 ? "+" : ""}${v.toFixed(2)}% (${v >= 0 ? "+" : ""}${bps} bps)`, `${longLabel} - ${shortLabel}`];
                }}
              />
              <Line
                type="monotone"
                dataKey="spread"
                stroke={latestSpread !== null && latestSpread < 0 ? "#dc2626" : "#2563eb"}
                strokeWidth={1.5}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-12">
            No overlapping data for {longLabel} and {shortLabel}.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
