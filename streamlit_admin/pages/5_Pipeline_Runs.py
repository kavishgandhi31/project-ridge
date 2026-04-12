"""Pipeline Runs page -- execution history and stage tracking."""

import httpx
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="Pipeline Runs", layout="wide")
st.title("Pipeline Runs")

limit = st.slider("Max runs", 5, 100, 20)

try:
    runs = httpx.get(f"{API_BASE}/pipeline/runs", params={"limit": limit}, timeout=30).json()
except Exception as e:
    st.error(f"Error fetching pipeline runs: {e}")
    st.stop()

if not runs:
    st.info("No pipeline runs found. Execute a pipeline run first.")
    st.stop()

# Summary
st.subheader(f"Recent Runs ({len(runs)} results)")

rows = []
for r in runs:
    rows.append(
        {
            "Run ID": r["run_id"][:12] + "...",
            "Type": r["run_type"],
            "Status": r["status"],
            "Started": str(r.get("started_at", ""))[:19],
            "Completed": str(r.get("completed_at", ""))[:19] if r.get("completed_at") else "-",
            "Stages": " -> ".join(r.get("stages_completed", [])) or "-",
            "Scored": r.get("n_countries_scored", 0),
            "Escalate": r.get("n_escalate", 0),
            "Alert": r.get("n_alert", 0),
            "Watch": r.get("n_watch", 0),
            "Error": r.get("error_message") or "-",
        }
    )

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

# Detail view
st.subheader("Run Detail")
run_ids = [r["run_id"] for r in runs]
selected_run = st.selectbox("Select run", run_ids, format_func=lambda x: x[:20] + "...")

if selected_run:
    try:
        detail = httpx.get(f"{API_BASE}/pipeline/runs/{selected_run}", timeout=10).json()
    except Exception as e:
        st.error(f"Error fetching run detail: {e}")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Status", detail["status"])
    with col2:
        st.metric("Countries Scored", detail["n_countries_scored"])
    with col3:
        st.metric("ESCALATE", detail["n_escalate"])
    with col4:
        st.metric("ALERT", detail["n_alert"])

    st.markdown(f"**Type:** {detail['run_type']}")
    st.markdown(f"**Started:** {detail['started_at']}")
    st.markdown(f"**Completed:** {detail.get('completed_at') or 'In progress'}")
    st.markdown(f"**Stages:** {' -> '.join(detail.get('stages_completed', []))}")

    if detail.get("error_message"):
        st.error(f"Error: {detail['error_message']}")
