"""Markets page -- Treasury yields, spreads, commodities, FX."""

import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Markets", layout="wide")
st.title("Markets Data")

# --- Treasury Yield Curve ---
st.header("US Treasury Yield Curve")

TREASURY_CODES = [
    ("UST_1M", "1M"),
    ("UST_3M", "3M"),
    ("UST_6M", "6M"),
    ("UST_1Y", "1Y"),
    ("DGS2", "2Y"),
    ("UST_3Y", "3Y"),
    ("UST_5Y", "5Y"),
    ("UST_7Y", "7Y"),
    ("DGS10", "10Y"),
    ("UST_20Y", "20Y"),
    ("UST_30Y", "30Y"),
]


@st.cache_data(ttl=300)
def fetch_indicator(indicator_code: str, limit: int = 500) -> list[dict[str, object]]:
    """Fetch observations for one indicator."""
    try:
        resp = httpx.get(
            f"{API_BASE}/observations",
            params={"indicator_code": indicator_code, "country_iso3": "USA", "limit": limit},
            timeout=30,
        )
        data = resp.json()
        # Guard: API may return a dict (error) instead of a list
        if isinstance(data, list):
            return data  # type: ignore[no-any-return]
        return []
    except Exception:
        return []


# Latest yield curve snapshot
curve_data: dict[str, float | None] = {}
for code, label in TREASURY_CODES:
    obs = fetch_indicator(code, limit=1)
    if obs:
        curve_data[label] = obs[0]["value"]  # type: ignore[assignment]
    else:
        curve_data[label] = None

if any(v is not None for v in curve_data.values()):
    curve_df = pd.DataFrame(
        [{"Maturity": k, "Yield (%)": v} for k, v in curve_data.items() if v is not None]
    )
    st.line_chart(curve_df, x="Maturity", y="Yield (%)")

    # Table with all maturities
    st.dataframe(
        pd.DataFrame(
            [
                {"Maturity": k, "Yield (%)": f"{v:.3f}" if v else "N/A"}
                for k, v in curve_data.items()
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No Treasury yield data. Run the FRED ingest pipeline first.")

# --- Spreads ---
st.header("Yield Spreads")

SPREAD_CODES = [
    ("SPREAD_10Y_2Y", "10Y-2Y"),
    ("SPREAD_10Y_3M", "10Y-3M"),
    ("SPREAD_30Y_10Y", "30Y-10Y"),
    ("SPREAD_5Y_2Y", "5Y-2Y"),
    ("T10Y2Y", "2s10s (FRED)"),
]

spread_latest: dict[str, float | None] = {}
for code, label in SPREAD_CODES:
    obs = fetch_indicator(code, limit=1)
    if obs:
        spread_latest[label] = obs[0]["value"]  # type: ignore[assignment]
    else:
        spread_latest[label] = None

if any(v is not None for v in spread_latest.values()):
    cols = st.columns(len(spread_latest))
    for col, (label, value) in zip(cols, spread_latest.items(), strict=True):
        with col:
            if value is not None:
                st.metric(label, f"{value:+.3f}%")
            else:
                st.metric(label, "N/A")
else:
    st.info("No spread data. Run ingest + spread builder first.")

# --- Spread time series ---
selected_spread = st.selectbox("Spread history", [code for code, _ in SPREAD_CODES])
if selected_spread:
    spread_obs = fetch_indicator(selected_spread, limit=500)
    if spread_obs:
        df = pd.DataFrame(spread_obs)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        st.line_chart(df, x="date", y="value")
    else:
        st.info(f"No data for {selected_spread}")

# --- Commodities ---
st.header("Commodities")

COMMODITY_CODES = [
    ("GOLD_FUTURES", "Gold"),
    ("SILVER_FUTURES", "Silver"),
    ("OIL_WTI_FUTURES", "WTI Crude"),
    ("OIL_BRENT_FUTURES", "Brent Crude"),
    ("NATGAS_FUTURES", "Natural Gas"),
    ("COPPER_FUTURES", "Copper"),
    ("WHEAT_FUTURES", "Wheat"),
    ("CORN_FUTURES", "Corn"),
    ("SOYBEAN_FUTURES", "Soybeans"),
]

commodity_latest: dict[str, float | None] = {}
for code, label in COMMODITY_CODES:
    obs = fetch_indicator(code, limit=1)
    if obs:
        commodity_latest[label] = obs[0]["value"]  # type: ignore[assignment]
    else:
        commodity_latest[label] = None

if any(v is not None for v in commodity_latest.values()):
    cols = st.columns(3)
    for i, (label, value) in enumerate(commodity_latest.items()):
        with cols[i % 3]:
            if value is not None:
                st.metric(label, f"${value:,.2f}")
            else:
                st.metric(label, "N/A")
else:
    st.info("No commodity data. Run the yfinance ingest first.")

# --- Commodity chart ---
selected_commodity = st.selectbox("Commodity history", [code for code, _ in COMMODITY_CODES])
if selected_commodity:
    comm_obs = fetch_indicator(selected_commodity, limit=500)
    if comm_obs:
        df = pd.DataFrame(comm_obs)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        st.line_chart(df, x="date", y="value")

# --- Global Equity & EM ---
st.header("Global Risk Signals")

RISK_CODES = [
    ("SP500", "S&P 500"),
    ("EM_EQUITY_ETF", "EM Equity (EEM)"),
    ("EM_BOND_ETF", "EM Bonds (EMB)"),
    ("VIXCLS", "VIX"),
    ("BAMLH0A0HYM2", "HY Spread"),
    ("BAMLEMCBPIOAS", "EM Corp Spread"),
]

risk_latest: dict[str, float | None] = {}
for code, label in RISK_CODES:
    obs = fetch_indicator(code, limit=1)
    if obs:
        risk_latest[label] = obs[0]["value"]  # type: ignore[assignment]
    else:
        risk_latest[label] = None

if any(v is not None for v in risk_latest.values()):
    cols = st.columns(3)
    for i, (label, value) in enumerate(risk_latest.items()):
        with cols[i % 3]:
            if value is not None:
                if "Spread" in label:
                    st.metric(label, f"{value:.2f}%")
                elif label == "VIX":
                    st.metric(label, f"{value:.1f}")
                else:
                    st.metric(label, f"{value:,.2f}")
            else:
                st.metric(label, "N/A")
else:
    st.info("No risk signal data.")
