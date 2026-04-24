"""Score History page -- track composite scores over time per country."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Score History", layout="wide")
st.title("Score History")

CSV_PATH = Path("logs/score_history.csv")

if not CSV_PATH.exists():
    st.info(
        "No score history yet. Run the pipeline at least once to generate "
        "logs/score_history.csv."
    )
    st.stop()

df = pd.read_csv(CSV_PATH)
df["run_date"] = pd.to_datetime(df["run_date"])

if df.empty:
    st.info("Score history file is empty.")
    st.stop()

# Summary
st.subheader("Overview")
n_runs = df["run_id"].nunique()
n_countries = df["country_iso3"].nunique()
date_range = f"{df['run_date'].min().date()} to {df['run_date'].max().date()}"
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Pipeline Runs", n_runs)
with col2:
    st.metric("Countries", n_countries)
with col3:
    st.metric("Date Range", date_range)

# Latest scores table
st.subheader("Latest Scores")
latest_run = df[df["run_id"] == df.iloc[-1]["run_id"]].copy()
latest_run = latest_run.sort_values("composite", ascending=True)
st.dataframe(
    latest_run[
        [
            "country_iso3",
            "composite",
            "coverage",
            "growth_momentum",
            "external_balance",
            "monetary_stance",
            "risk_sentiment",
        ]
    ].rename(
        columns={
            "country_iso3": "Country",
            "composite": "Composite",
            "coverage": "Coverage",
            "growth_momentum": "Growth",
            "external_balance": "External",
            "monetary_stance": "Monetary",
            "risk_sentiment": "Risk Sent.",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

# Composite trend chart
st.subheader("Composite Score Trend")
countries = sorted(df["country_iso3"].unique())
selected = st.multiselect(
    "Select countries",
    countries,
    default=countries[:5],
)

if selected:
    filtered = df[df["country_iso3"].isin(selected)].copy()
    if len(filtered["run_date"].unique()) > 1:
        import altair as alt

        chart = (
            alt.Chart(filtered)
            .mark_line(point=True)
            .encode(
                x=alt.X("run_date:T", title="Run Date"),
                y=alt.Y("composite:Q", title="Composite Score"),
                color=alt.Color("country_iso3:N", title="Country"),
                tooltip=[
                    alt.Tooltip("country_iso3:N", title="Country"),
                    alt.Tooltip("run_date:T", title="Date"),
                    alt.Tooltip("composite:Q", format="+.3f", title="Composite"),
                ],
            )
            .properties(height=400)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Need at least 2 runs to show a trend. Check back after the next pipeline run.")

# Dimension breakdown for selected country
st.subheader("Dimension Breakdown")
single_country = st.selectbox("Country detail", countries)
if single_country:
    country_df = df[df["country_iso3"] == single_country].copy()
    country_df = country_df.sort_values("run_date")

    if not country_df.empty:
        latest = country_df.iloc[-1]
        cols = st.columns(5)
        with cols[0]:
            v = latest["composite"]
            st.metric("Composite", f"{v:+.3f}" if pd.notna(v) else "N/A")
        with cols[1]:
            v = latest["growth_momentum"]
            st.metric("Growth", f"{v:+.3f}" if pd.notna(v) else "N/A")
        with cols[2]:
            v = latest["external_balance"]
            st.metric("External", f"{v:+.3f}" if pd.notna(v) else "N/A")
        with cols[3]:
            v = latest["monetary_stance"]
            st.metric("Monetary", f"{v:+.3f}" if pd.notna(v) else "N/A")
        with cols[4]:
            v = latest["risk_sentiment"]
            st.metric("Risk Sent.", f"{v:+.3f}" if pd.notna(v) else "N/A")

# Raw data
with st.expander("Raw score history"):
    st.dataframe(
        df.sort_values(["run_date", "country_iso3"], ascending=[False, True]), hide_index=True
    )
