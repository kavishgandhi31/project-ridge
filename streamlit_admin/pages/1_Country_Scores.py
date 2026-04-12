"""Country Scores page -- composite scores and dimension breakdown."""

import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Country Scores", layout="wide")
st.title("Country Scores")

# Fetch countries for selector
try:
    countries = httpx.get(f"{API_BASE}/countries", timeout=10).json()
except Exception as e:
    st.error(f"Cannot reach API: {e}")
    st.stop()

country_options = {c["iso3"]: f"{c['name']} ({c['iso3']})" for c in countries}

# Controls
col1, col2 = st.columns([2, 1])
with col1:
    selected_country = st.selectbox(
        "Country",
        options=["All", *country_options.keys()],
        format_func=lambda x: "All countries" if x == "All" else country_options.get(x, x),
    )
with col2:
    limit = st.slider("Max results", 10, 200, 50)

# Fetch scores
params: dict[str, object] = {"limit": limit}
if selected_country != "All":
    params["country_iso3"] = selected_country

try:
    scores = httpx.get(f"{API_BASE}/scores", params=params, timeout=30).json()
except Exception as e:
    st.error(f"Error fetching scores: {e}")
    st.stop()

if not scores:
    st.info("No score results found. Run the scoring pipeline first.")
    st.stop()

# Summary table
st.subheader(f"Score Results ({len(scores)} rows)")

rows = []
for s in scores:
    row = {
        "Country": s["country_iso3"],
        "Composite": s["composite"],
        "Coverage": f"{s['coverage_fraction']:.0%}" if s["coverage_fraction"] else "N/A",
        "Scored At": s["scored_at"][:19],
    }
    for dim_key in ("growth_momentum", "external_balance", "monetary_stance", "risk_sentiment"):
        dim = s.get("dimensions", {}).get(dim_key)
        if dim and dim.get("value") is not None:
            row[dim_key.replace("_", " ").title()] = round(dim["value"], 2)
        else:
            row[dim_key.replace("_", " ").title()] = None
    rows.append(row)

df = pd.DataFrame(rows)

# Color-code composites
st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
)

# Detail view for selected country
if selected_country != "All" and scores:
    st.subheader(f"Detail: {country_options.get(selected_country, selected_country)}")
    latest = scores[0]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Composite", f"{latest['composite']:+.2f}" if latest["composite"] else "N/A")
    with col2:
        st.metric("Coverage", f"{latest['coverage_fraction']:.0%}")
    with col3:
        news = latest.get("news_heat")
        if news:
            st.metric("News Heat", f"{news['sigma']:+.1f} sigma")
        else:
            st.metric("News Heat", "Normal")

    st.markdown("**Dimension Scores:**")
    for dim_key, label in [
        ("growth_momentum", "Growth Momentum"),
        ("external_balance", "External Balance"),
        ("monetary_stance", "Monetary Stance"),
        ("risk_sentiment", "Risk Sentiment"),
    ]:
        dim = latest.get("dimensions", {}).get(dim_key)
        if dim and dim.get("value") is not None:
            st.write(
                f"- **{label}**: {dim['value']:+.2f} "
                f"({dim['n_series_used']} series, {dim['n_concepts']} concepts)"
            )
        else:
            st.write(f"- **{label}**: N/A")
