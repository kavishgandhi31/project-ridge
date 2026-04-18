"""Quality Issues page -- data quality flags and staleness."""

import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Quality Issues", layout="wide")
st.title("Quality Issues")

# Controls
col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    check_filter = st.selectbox(
        "Check",
        [
            "All",
            "outlier",
            "flatline",
            "revision",
            "staleness",
            "structural_break",
            "cross_source",
            "backfill",
            "audit",
        ],
    )
with col2:
    country_filter = st.text_input("Country ISO3 (optional)")
with col3:
    limit = st.slider("Max results", 10, 500, 100)

params: dict[str, object] = {"limit": limit}
if check_filter != "All":
    params["check_name"] = check_filter
if country_filter:
    params["country_iso3"] = country_filter.upper()

try:
    issues = httpx.get(f"{API_BASE}/quality/issues", params=params, timeout=30).json()
except Exception as e:
    st.error(f"Error fetching quality issues: {e}")
    st.stop()

if not issues:
    st.success("No quality issues found -- data looks clean!")
    st.stop()

# Severity counts
severity_counts: dict[str, int] = {}
for i in issues:
    sev = i.get("severity", "unknown")
    severity_counts[sev] = severity_counts.get(sev, 0) + 1

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Critical", severity_counts.get("critical", 0))
with col2:
    st.metric("Warning", severity_counts.get("warning", 0))
with col3:
    st.metric("Info", severity_counts.get("info", 0))

# Table
st.subheader(f"Issues ({len(issues)} results)")
rows = []
for i in issues:
    rows.append(
        {
            "Severity": i.get("severity", "?"),
            "Check": i.get("check_name", "?"),
            "Country": i.get("country_iso3") or "global",
            "Indicator": i.get("indicator_code") or "-",
            "Source": i.get("source_id") or "-",
            "Message": i.get("message", ""),
            "Detected": str(i.get("detected_at", ""))[:19],
        }
    )

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)
