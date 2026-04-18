/**
 * Human-readable labels for canonical indicator codes.
 *
 * Single source of truth for displaying indicator names across
 * the dashboard. Codes come from source_indicators.yaml.
 *
 * To change a label, edit this file only.
 */

const INDICATOR_LABELS: Record<string, string> = {
  // Macro fundamentals
  CPI_YOY: "Inflation (CPI YoY)",
  GDP_GROWTH: "GDP Growth",
  CURRENT_ACCOUNT_GDP: "Current Account (% GDP)",
  RESERVES_MONTHS_IMPORTS: "Reserves (Months of Imports)",
  GOVT_DEBT_GDP: "Government Debt (% GDP)",
  UNEMPLOYMENT: "Unemployment Rate",
  TRADE_OPENNESS: "Trade Openness (% GDP)",
  POLICY_RATE: "Policy Rate",
  CPI_INDEX: "CPI Index",
  LENDING_RATE: "Lending Rate",

  // External
  FX_USD: "FX Rate (vs USD)",
  FX_RATE: "FX Rate",
  FX_RESERVES_TOTAL: "FX Reserves (Total)",
  FX_RESERVES_EX_GOLD: "FX Reserves (ex Gold)",
  FX_RESERVES_MONTHLY: "FX Reserves (Total, Monthly)",
  CURRENT_ACCOUNT_USD: "Current Account (USD)",
  FINANCIAL_ACCOUNT_USD: "Financial Account (USD)",
  TRADE_BALANCE_USD: "Trade Balance (USD)",

  // Equity & market
  EQUITY_INDEX: "Equity Index",
  SP500: "S&P 500",
  EM_EQUITY_ETF: "EM Equity ETF",
  EM_BOND_ETF: "EM Bond ETF",
  VIXCLS: "VIX",

  // US Treasuries
  DGS2: "US 2Y Yield",
  DGS10: "US 10Y Yield",
  T10Y2Y: "US 2s10s Curve",
  UST_1M: "US 1M Yield",
  UST_3M: "US 3M Yield",
  UST_6M: "US 6M Yield",
  UST_1Y: "US 1Y Yield",
  UST_3Y: "US 3Y Yield",
  UST_5Y: "US 5Y Yield",
  UST_7Y: "US 7Y Yield",
  UST_20Y: "US 20Y Yield",
  UST_30Y: "US 30Y Yield",

  // TIPS & breakevens
  TIPS_5Y: "TIPS 5Y Real Yield",
  TIPS_7Y: "TIPS 7Y Real Yield",
  TIPS_10Y: "TIPS 10Y Real Yield",
  TIPS_20Y: "TIPS 20Y Real Yield",
  TIPS_30Y: "TIPS 30Y Real Yield",
  BREAKEVEN_5Y: "5Y Breakeven Inflation",
  BREAKEVEN_10Y: "10Y Breakeven Inflation",

  // Credit
  BAMLH0A0HYM2: "US HY Spread",
  BAMLEMCBPIOAS: "EM Corp Bond Spread",
  NFCI: "Financial Conditions Index",
  DTWEXBGS: "USD Trade-Weighted Index",
  CREDIT_GAP: "Credit-to-GDP Gap",

  // Commodities (spot)
  GOLD: "Gold (Spot)",
  OIL_WTI: "WTI Crude Oil",
  DCOILBRENTEU: "Brent Crude Oil",
  NATGAS_HH: "Natural Gas (Henry Hub)",
  COPPER: "Copper",

  // Commodities (futures)
  GOLD_FUTURES: "Gold Futures",
  SILVER_FUTURES: "Silver Futures",
  OIL_WTI_FUTURES: "WTI Crude Futures",
  OIL_BRENT_FUTURES: "Brent Crude Futures",
  NATGAS_FUTURES: "Natural Gas Futures",
  COPPER_FUTURES: "Copper Futures",
  WHEAT_FUTURES: "Wheat Futures",
  CORN_FUTURES: "Corn Futures",
  SOYBEAN_FUTURES: "Soybean Futures",

  // OECD leading indicators
  CLI: "Composite Leading Indicator",
  BCI: "Business Confidence",
  CCI: "Consumer Confidence",

  // BIS
  INDPROD: "Industrial Production",
  PROPERTY_PRICE: "Property Price Index",
  REER: "Real Effective Exchange Rate",

  // News/events
  tone: "News Tone",
  volume: "News Volume",
  headline: "Headlines",
};

/**
 * Get a human-readable label for an indicator code.
 * Falls back to a cleaned-up version of the code itself.
 */
export function getIndicatorLabel(code: string): string {
  const label = INDICATOR_LABELS[code];
  if (label) return label;

  // Fallback: convert UPPER_SNAKE_CASE to Title Case
  return code
    .split("_")
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(" ");
}
