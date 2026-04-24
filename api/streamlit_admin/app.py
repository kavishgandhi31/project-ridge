"""Ridge Admin Dashboard -- internal Streamlit app for visual validation.

NOT customer-facing. This is the Phase 7 admin/debug tool that reads
from the FastAPI API to validate all pipeline layers visually.

Launch:
    cd api
    # Start the API first:
    uv run uvicorn ridge.api.main:app --port 8000
    # Then start Streamlit:
    uv run streamlit run streamlit_admin/app.py --server.port 8502
"""

import httpx
import streamlit as st

st.set_page_config(
    page_title="Ridge Admin",
    page_icon="🐝",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = "http://localhost:8000"

st.sidebar.title("Ridge Admin")
st.sidebar.caption("Internal debug dashboard -- not customer-facing")

st.title("Ridge Admin Dashboard")
st.markdown(
    """
    **Pages:**
    - **Country Scores** -- composite scores and dimension breakdown
    - **Alert Dashboard** -- tier assignments grouped by severity
    - **LLM Narratives** -- generated narratives with citation tracking
    - **Quality Issues** -- data quality flags and staleness
    - **Pipeline Runs** -- execution history and stage tracking
    """
)

# Health check
try:
    resp = httpx.get(f"{API_BASE}/health", timeout=5)
    data = resp.json()
    if data.get("status") == "ok":
        st.success(f"API: healthy | DB: {data.get('database')} | v{data.get('version')}")
    else:
        st.warning(f"API: degraded | {data}")
except Exception as e:
    st.error(f"Cannot reach API at {API_BASE}: {e}")
    st.info("Start the API with: `uv run uvicorn ridge.api.main:app --port 8000`")
