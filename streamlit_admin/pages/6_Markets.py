"""Markets page -- Treasury yields, spreads, commodities, FX."""

import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Markets", layout="wide")
st.title("Markets Data")

# --- Nominal Treasury yield curve (consistent category) ---
# All maturities use nominal yields only. No mixing with TIPS/breakevens.
NOMINAL_YIELDS = [
    ("UST_1M", "1 Month"),
    ("UST_3M", "3 Month"),
    ("UST_6M", "6 Month"),
    ("UST_1Y", "1 Year"),
    ("DGS2", "2 Year"),
    ("UST_3Y", "3 Year"),
    ("UST_5Y", "5 Year"),
    ("UST_7Y", "7 Year"),
    ("DGS10", "10 Year"),
    ("UST_20Y", "20 Year"),
    ("UST_30Y", "30 Year"),
]

# Lookup: display name -> indicator code (for spread comparator)
_NOMINAL_CODE_BY_LABEL = {label: code for code, label in NOMINAL_YIELDS}
_NOMINAL_LABEL_BY_CODE = {code: label for code, label in NOMINAL_YIELDS}

COMMODITY_ITEMS = [
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

_COMMODITY_LABEL_BY_CODE = {code: label for code, label in COMMODITY_ITEMS}

RISK_ITEMS = [
    ("SP500", "S&P 500"),
    ("EM_EQUITY_ETF", "EM Equity (EEM)"),
    ("EM_BOND_ETF", "EM Bonds (EMB)"),
    ("VIXCLS", "VIX"),
    ("BAMLH0A0HYM2", "High Yield Spread"),
    ("BAMLEMCBPIOAS", "EM Corporate Spread"),
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
        if isinstance(data, list):
            return data  # type: ignore[no-any-return]
        return []
    except Exception:
        return []


# =====================================================================
# US Treasury Yield Curve (Nominal)
# =====================================================================
st.header("US Treasury Yield Curve")

curve_data: dict[str, float | None] = {}
for code, label in NOMINAL_YIELDS:
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

# =====================================================================
# Spread Comparator -- pick any two nominal maturities
# =====================================================================
st.header("Spread Comparator")
st.caption("Long end minus short end. All nominal yields (no TIPS mixing).")

maturity_labels = [label for _, label in NOMINAL_YIELDS]

col1, col2 = st.columns(2)
with col1:
    long_label = st.selectbox("Long end", maturity_labels, index=maturity_labels.index("10 Year"))
with col2:
    short_label = st.selectbox("Short end", maturity_labels, index=maturity_labels.index("2 Year"))

if long_label == short_label:
    st.warning("Select two different maturities.")
else:
    long_code = _NOMINAL_CODE_BY_LABEL[long_label]
    short_code = _NOMINAL_CODE_BY_LABEL[short_label]

    long_obs = fetch_indicator(long_code, limit=500)
    short_obs = fetch_indicator(short_code, limit=500)

    if long_obs and short_obs:
        # Build date-matched spread
        long_by_date = {o["date"]: o["value"] for o in long_obs}
        short_by_date = {o["date"]: o["value"] for o in short_obs}
        common_dates = sorted(set(long_by_date) & set(short_by_date))

        if common_dates:
            spread_rows = [
                {
                    "date": d,
                    "spread": float(long_by_date[d]) - float(short_by_date[d]),  # type: ignore[arg-type]
                }
                for d in common_dates
            ]
            spread_df = pd.DataFrame(spread_rows)
            spread_df["date"] = pd.to_datetime(spread_df["date"])

            latest_spread = spread_rows[-1]["spread"]
            st.metric(
                f"{long_label} - {short_label}",
                f"{latest_spread:+.3f}%",
            )
            st.line_chart(spread_df, x="date", y="spread")
        else:
            st.info("No overlapping dates between the two maturities.")
    else:
        st.info("No yield data available. Run the FRED ingest first.")

# =====================================================================
# Commodities
# =====================================================================
st.header("Commodities")

commodity_latest: dict[str, float | None] = {}
for code, label in COMMODITY_ITEMS:
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

# Commodity Tracker
st.subheader("Commodity Tracker")
commodity_labels = [label for _, label in COMMODITY_ITEMS]
selected_commodity_label = st.selectbox("Select commodity", commodity_labels)
if selected_commodity_label:
    selected_code = next(code for code, name in COMMODITY_ITEMS if name == selected_commodity_label)
    comm_obs = fetch_indicator(selected_code, limit=500)
    if comm_obs:
        df = pd.DataFrame(comm_obs)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        st.line_chart(df, x="date", y="value")
    else:
        st.info(f"No data for {selected_commodity_label}")

# =====================================================================
# Global Risk Signals
# =====================================================================
st.header("Global Risk Signals")

risk_latest: dict[str, float | None] = {}
for code, label in RISK_ITEMS:
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
