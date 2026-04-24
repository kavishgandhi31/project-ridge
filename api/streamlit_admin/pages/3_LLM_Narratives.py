"""LLM Narratives page -- generated narratives with citation tracking."""

import json
import re

import httpx
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="LLM Narratives", layout="wide")
st.title("LLM Narratives")

# Fetch countries
try:
    countries = httpx.get(f"{API_BASE}/countries", timeout=10).json()
except Exception as e:
    st.error(f"Cannot reach API: {e}")
    st.stop()

country_options = {c["iso3"]: f"{c['name']} ({c['iso3']})" for c in countries}

# Controls
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    selected_country = st.selectbox(
        "Country",
        options=["All", *country_options.keys()],
        format_func=lambda x: "All countries" if x == "All" else country_options.get(x, x),
    )
with col2:
    template_filter = st.selectbox("Template", ["All", "country_narrative", "alert_rationale"])
with col3:
    limit = st.slider("Max results", 5, 50, 20)

params: dict[str, object] = {"limit": limit}
if selected_country != "All":
    params["country_iso3"] = selected_country
if template_filter != "All":
    params["template_name"] = template_filter

try:
    narratives = httpx.get(f"{API_BASE}/narratives", params=params, timeout=30).json()
except Exception as e:
    st.error(f"Error fetching narratives: {e}")
    st.stop()

if not narratives:
    st.info("No LLM narratives found. Run the LLM pipeline stage first.")
    st.stop()

st.subheader(f"Narratives ({len(narratives)} results)")

for n in narratives:
    with st.expander(
        f"{n['country_iso3']} | {n['template_name']} | "
        f"grounding: {n['grounding_score']:.0%} | "
        f"{n['provider_id']}/{n['model_id']} | "
        f"{n['generated_at'][:19]}"
    ):
        # Grounding metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            score = n["grounding_score"]
            st.metric(
                "Grounding Score",
                f"{score:.0%}",
                delta="OK" if score >= 0.8 else "LOW",
                delta_color="normal" if score >= 0.8 else "inverse",
            )
        with col2:
            st.metric("Citations Used", len(n.get("citations_used", [])))
        with col3:
            st.metric("Citations Available", n.get("citations_available_count", 0))
        with col4:
            ungrounded = n.get("ungrounded_claims", [])
            st.metric("Ungrounded Claims", len(ungrounded))

        # Try to parse content as JSON and render nicely
        try:
            parsed = json.loads(n["content"])

            if "headline" in parsed:
                st.markdown(f"**Headline:** {parsed['headline']}")
            if "narrative" in parsed:
                # Highlight citation markers [N] in the narrative
                text = parsed["narrative"]
                highlighted = re.sub(
                    r"\[(\d+)\]",
                    r"**[\1]**",
                    text,
                )
                st.markdown(highlighted)
            if "key_risks" in parsed:
                st.markdown("**Key Risks:**")
                for risk in parsed["key_risks"]:
                    st.markdown(f"- {risk}")
            if "outlook" in parsed:
                st.markdown(f"**Outlook:** {parsed['outlook']}")

            # Alert rationale fields
            if "signal_drivers" in parsed:
                st.markdown("**Signal Drivers:**")
                for driver in parsed["signal_drivers"]:
                    st.markdown(f"- {driver}")
            if "contagion_risk" in parsed:
                st.markdown(f"**Contagion Risk:** {parsed['contagion_risk']}")
            if "recommended_actions" in parsed:
                st.markdown("**Recommended Actions:**")
                for action in parsed["recommended_actions"]:
                    st.markdown(f"- {action}")
            if "confidence_level" in parsed:
                st.markdown(
                    f"**Confidence:** {parsed['confidence_level']} "
                    f"-- {parsed.get('confidence_justification', '')}"
                )
        except (json.JSONDecodeError, KeyError):
            # Fallback: show raw content
            st.code(n["content"], language="json")

        # Citation details
        citations = n.get("citations_used", [])
        if citations:
            st.markdown("**Citations:**")
            for c in citations:
                st.markdown(
                    f"- [{c['ref_number']}] {c['indicator_code']} "
                    f"({c['country_iso3']}, {c['date']}): {c['value']}"
                )

        # Ungrounded claims
        if ungrounded:
            st.warning(f"Ungrounded claims: {', '.join(str(u) for u in ungrounded)}")

        # Provider metadata
        st.caption(
            f"Provider: {n['provider_id']} | Model: {n['model_id']} | "
            f"Tokens: {n['tokens_in']} in / {n['tokens_out']} out | "
            f"Latency: {n['latency_ms']}ms"
        )
