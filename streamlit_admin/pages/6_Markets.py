"""Markets page -- Treasury yields, spreads, commodities, FX."""

from __future__ import annotations

import datetime
import math

import altair as alt
import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Markets", layout="wide")
st.title("Markets Data")

# =====================================================================
# Shared utilities
# =====================================================================

# Time scale options for all time series charts
TIME_SCALES: list[tuple[str, int | None]] = [
    ("1M", 30),
    ("3M", 90),
    ("6M", 180),
    ("YTD", None),  # special: computed from Jan 1
    ("1Y", 365),
    ("3Y", 1095),
    ("5Y", 1825),
    ("All", None),
]


def _nice_step(data_range: float) -> float:
    """Pick a 'nice' rounding step based on the magnitude of the data range.

    Goal: axis bounds should land on clean numbers that look good as labels.
    Examples:
      range ~0.5-5 (yields, spreads): step 0.25
      range ~5-20 (VIX, natgas): step 1
      range ~20-100 (oil): step 5
      range ~100-500 (ETFs): step 25
      range ~500-2000: step 50
      range ~2000+: step 100
    """
    if data_range <= 0:
        return 0.5
    magnitude = 10 ** math.floor(math.log10(data_range))
    normalized = data_range / magnitude
    if normalized <= 2:
        return magnitude * 0.25
    if normalized <= 5:
        return magnitude * 0.5
    return magnitude


def _axis_bounds(values: list[float]) -> tuple[float, float]:
    """Compute clean y-axis bounds with proportional padding.

    Algorithm:
    1. 10% of range as padding on each side (minimum: one nice_step)
    2. Round down to the nearest nice_step for bottom
    3. Round up to the nearest nice_step for top

    Handles flat data (range=0) by using +/- 5% of the value.
    """
    if not values:
        return 0.0, 1.0

    v_min = min(values)
    v_max = max(values)
    data_range = v_max - v_min

    if data_range == 0:
        # Flat line -- create artificial range
        margin = abs(v_min) * 0.05 if v_min != 0 else 1.0
        return v_min - margin, v_max + margin

    step = _nice_step(data_range)
    padding = max(data_range * 0.10, step)

    y_min = math.floor((v_min - padding) / step) * step
    y_max = math.ceil((v_max + padding) / step) * step

    return y_min, y_max


def _filter_by_timescale(
    df: pd.DataFrame,
    date_col: str,
    scale_label: str,
    scale_days: int | None,
) -> pd.DataFrame:
    """Filter a DataFrame by the selected time scale."""
    if scale_label == "All":
        return df
    if scale_label == "YTD":
        jan1 = pd.Timestamp(datetime.date.today().year, 1, 1)
        return df[df[date_col] >= jan1]
    if scale_days is not None:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=scale_days)
        return df[df[date_col] >= cutoff]
    return df


def _date_axis_format(scale_label: str) -> str:
    """Pick a date axis format string based on the selected time scale.

    Short ranges show day-level detail, longer ranges show quarter/year.
    """
    if scale_label in ("1M",):
        return "%b %d"  # "Apr 10"
    if scale_label in ("3M", "6M", "YTD"):
        return "%b '%y"  # "Apr '26"
    if scale_label in ("1Y",):
        return "%b '%y"  # "Apr '26"
    # 3Y, 5Y, All
    return "%b '%y"  # "Apr '26"


def _date_axis_tick_count(scale_label: str) -> int | str:
    """Pick an appropriate number of axis ticks for the time scale."""
    if scale_label == "1M":
        return 8  # ~every 4 days
    if scale_label == "3M":
        return 6  # ~every 2 weeks
    if scale_label in ("6M", "YTD"):
        return 6
    if scale_label == "1Y":
        return 12  # monthly
    if scale_label == "3Y":
        return 12  # quarterly
    # 5Y, All
    return 10


def _time_series_chart(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    *,
    title: str = "",
    y_unit: str = "",
    y_format: str = ".2f",
    height: int = 350,
    scale_key: str = "default",
) -> None:
    """Render a time series chart with time scale selector and dynamic y-axis."""
    # Time scale selector
    scale_options = [label for label, _ in TIME_SCALES]
    selected_scale = st.radio(
        "Time scale",
        scale_options,
        index=scale_options.index("1Y"),
        horizontal=True,
        key=f"ts_{scale_key}",
    )
    scale_days = dict(TIME_SCALES).get(selected_scale)

    filtered = _filter_by_timescale(df, date_col, selected_scale, scale_days)
    if filtered.empty:
        st.info("No data for the selected time range.")
        return

    values = filtered[value_col].dropna().tolist()
    if not values:
        st.info("No data for the selected time range.")
        return

    y_min, y_max = _axis_bounds(values)
    y_title = f"{title} ({y_unit})" if y_unit else (title or value_col)
    date_fmt = _date_axis_format(selected_scale)
    tick_count = _date_axis_tick_count(selected_scale)

    chart = (
        alt.Chart(filtered)
        .mark_line()
        .encode(
            x=alt.X(
                f"{date_col}:T",
                title="",
                axis=alt.Axis(format=date_fmt, tickCount=tick_count, grid=True),
            ),
            y=alt.Y(
                f"{value_col}:Q",
                scale=alt.Scale(domain=[y_min, y_max]),
                title=y_title,
            ),
            tooltip=[
                alt.Tooltip(f"{date_col}:T", title="Date", format="%Y-%m-%d"),
                alt.Tooltip(f"{value_col}:Q", format=y_format, title=title or value_col),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)


def _maturity_sort_key(label: str) -> float:
    """Convert a maturity label to a numeric value in years for sorting."""
    parts = label.strip().split()
    if len(parts) < 2:
        return 999.0
    try:
        num = float(parts[0])
    except ValueError:
        return 999.0
    unit = parts[1].lower()
    if unit.startswith("month"):
        return num / 12.0
    if unit.startswith("year"):
        return num
    if unit.startswith("week"):
        return num / 52.0
    if unit.startswith("day"):
        return num / 365.0
    return num


@st.cache_data(ttl=300)
def fetch_indicator(indicator_code: str, limit: int = 2000) -> list[dict[str, object]]:
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


# Data definitions
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
_NOMINAL_CODE_BY_LABEL = {label: code for code, label in NOMINAL_YIELDS}

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

RISK_ITEMS = [
    ("SP500", "S&P 500"),
    ("EM_EQUITY_ETF", "EM Equity (EEM)"),
    ("EM_BOND_ETF", "EM Bonds (EMB)"),
    ("VIXCLS", "VIX"),
    ("BAMLH0A0HYM2", "High Yield Spread"),
    ("BAMLEMCBPIOAS", "EM Corporate Spread"),
]


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
    curve_rows = [{"Maturity": k, "Yield (%)": v} for k, v in curve_data.items() if v is not None]
    curve_rows.sort(key=lambda r: _maturity_sort_key(str(r["Maturity"])))
    curve_df = pd.DataFrame(curve_rows)
    sorted_labels = [str(r["Maturity"]) for r in curve_rows]

    yields = [float(r["Yield (%)"]) for r in curve_rows]
    y_min, y_max = _axis_bounds(yields)

    chart = (
        alt.Chart(curve_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("Maturity:N", sort=sorted_labels, title="Maturity"),
            y=alt.Y("Yield (%):Q", scale=alt.Scale(domain=[y_min, y_max]), title="Yield (%)"),
            tooltip=["Maturity", alt.Tooltip("Yield (%):Q", format=".3f")],
        )
        .properties(height=350)
    )
    st.altair_chart(chart, use_container_width=True)

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
# Spread Comparator
# =====================================================================
st.header("Spread Comparator")
st.caption("Always computes longer maturity minus shorter maturity. All nominal yields.")

maturity_labels = [label for _, label in NOMINAL_YIELDS]

col1, col2 = st.columns(2)
with col1:
    maturity_a = st.selectbox("Maturity A", maturity_labels, index=maturity_labels.index("10 Year"))
with col2:
    maturity_b = st.selectbox("Maturity B", maturity_labels, index=maturity_labels.index("2 Year"))

if maturity_a == maturity_b:
    st.warning("Select two different maturities.")
else:
    if _maturity_sort_key(maturity_a) >= _maturity_sort_key(maturity_b):
        long_label, short_label = maturity_a, maturity_b
    else:
        long_label, short_label = maturity_b, maturity_a

    long_code = _NOMINAL_CODE_BY_LABEL[long_label]
    short_code = _NOMINAL_CODE_BY_LABEL[short_label]

    long_obs = fetch_indicator(long_code, limit=2000)
    short_obs = fetch_indicator(short_code, limit=2000)

    if long_obs and short_obs:
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
            st.metric(f"{long_label} - {short_label}", f"{latest_spread:+.3f}%")

            _time_series_chart(
                spread_df,
                "date",
                "spread",
                title=f"{long_label} - {short_label}",
                y_unit="%",
                y_format="+.3f",
                scale_key="spread",
            )
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
    comm_obs = fetch_indicator(selected_code, limit=2000)
    if comm_obs:
        df = pd.DataFrame(comm_obs)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        _time_series_chart(
            df,
            "date",
            "value",
            title=selected_commodity_label,
            y_unit="USD",
            y_format=",.2f",
            scale_key=f"commodity_{selected_code}",
        )
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
