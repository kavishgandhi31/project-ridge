"""Alert Dashboard page -- tier assignments grouped by severity."""

import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Alert Dashboard", layout="wide")
st.title("Alert Dashboard")

# Controls
col1, col2 = st.columns([2, 1])
with col1:
    tier_filter = st.selectbox("Tier", ["All", "ESCALATE", "ALERT", "WATCH"])
with col2:
    limit = st.slider("Max results", 10, 500, 100)

params: dict[str, object] = {"limit": limit}
if tier_filter != "All":
    params["effective_tier"] = tier_filter

try:
    alerts = httpx.get(f"{API_BASE}/alerts", params=params, timeout=30).json()
except Exception as e:
    st.error(f"Error fetching alerts: {e}")
    st.stop()

if not alerts:
    st.info("No alert records found. Run the alert pipeline first.")
    st.stop()

# Count by tier
tier_counts: dict[str, int] = {}
for a in alerts:
    tier = a.get("effective_tier", "none") or "none"
    tier_counts[tier] = tier_counts.get(tier, 0) + 1

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("ESCALATE", tier_counts.get("ESCALATE", 0))
with col2:
    st.metric("ALERT", tier_counts.get("ALERT", 0))
with col3:
    st.metric("WATCH", tier_counts.get("WATCH", 0))
with col4:
    st.metric("Total", len(alerts))

# Table
st.subheader("Alert Records")
rows = []
for a in alerts:
    rows.append(
        {
            "Country": a.get("country_iso3"),
            "Effective Tier": a.get("effective_tier") or "-",
            "Raw Tier": a.get("raw_tier") or "-",
            "Composite": a.get("composite"),
            "Coverage": f"{a['coverage_fraction']:.0%}" if a.get("coverage_fraction") else "-",
            "Streak": a.get("streak_length", 0),
            "Velocity": f"{a['velocity']:.2f}" if a.get("velocity") is not None else "-",
            "Modifiers": ", ".join(a.get("modifiers_applied", [])) or "-",
            "Evaluated": str(a.get("evaluated_at", ""))[:19],
        }
    )

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)
