"""
Streamlit reviewer UI for Prahari (Phase 6).

A compliance officer loads a flagged case, runs the agent, and reviews the
decision, the agent's audit trail, and the generated STR — then approves or
overrides. Human-in-the-loop by design.

Run (API must be up first):
    uvicorn api.main:app --reload         # terminal 1
    streamlit run app/main.py             # terminal 2
"""

from __future__ import annotations

import os

import pandas as pd
import requests
import streamlit as st

API_BASE = os.getenv("PRAHARI_API", "http://localhost:8000")

st.set_page_config(page_title="Prahari — AML Investigation", page_icon="🛡️", layout="wide")


# ── Data helpers ──────────────────────────────────────────────────────────────

def fetch_sample() -> dict | None:
    try:
        r = requests.get(f"{API_BASE}/sample", timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        st.error(f"Could not reach API at {API_BASE} (/sample): {exc}")
        return None


def investigate(case: dict) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}/investigate", json=case, timeout=180)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        st.error(f"Investigation request failed: {exc}")
        return None


def _lakh(amount: float) -> str:
    return f"₹{amount / 1e5:.2f}L"


# ── Session state ─────────────────────────────────────────────────────────────

if "case" not in st.session_state:
    st.session_state.case = fetch_sample()
if "result" not in st.session_state:
    st.session_state.result = None


# ── Header ────────────────────────────────────────────────────────────────────

st.title("🛡️ Prahari — AML Investigation")
st.caption(
    "Autonomous compliance analyst for Indian financial institutions · "
    "PMLA 2002 · RBI KYC Master Directions · FIU-IND STR format"
)

top_l, top_r = st.columns([1, 1])
with top_l:
    if st.button("🔄 Load another sample case", use_container_width=True):
        st.session_state.case = fetch_sample()
        st.session_state.result = None
with top_r:
    if st.button("🔍 Investigate", type="primary", use_container_width=True,
                 disabled=st.session_state.case is None):
        with st.spinner("Agent investigating — planning, gathering evidence, "
                        "reasoning against regulation, drafting STR…"):
            st.session_state.result = investigate(st.session_state.case)

case = st.session_state.case
result = st.session_state.result

if case is None:
    st.warning("No case loaded. Start the API (`uvicorn api.main:app --reload`) and reload.")
    st.stop()


# ── Case details ──────────────────────────────────────────────────────────────

st.subheader("Case under review")
cust = case["customer"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Case ID", case["case_id"])
c2.metric("Customer", cust["name"])
c3.metric("Business type", cust["business_type"])
c4.metric("Prior flags", cust["prior_flags"])

c5, c6, c7 = st.columns(3)
c5.metric("Stated monthly turnover", _lakh(cust["stated_monthly_turnover_inr"]))
c6.metric("Transactions", len(case["transactions"]))
c7.metric("Account opened", cust["account_open_date"][:10])

with st.expander(f"Transactions ({len(case['transactions'])})", expanded=False):
    df = pd.DataFrame(case["transactions"])
    df = df[["timestamp", "direction", "channel", "amount_inr",
             "counterparty_name"]].copy()
    df["timestamp"] = df["timestamp"].str[:10]
    df["amount_inr"] = df["amount_inr"].map(lambda a: f"₹{a:,.0f}")
    df.columns = ["Date", "Direction", "Channel", "Amount", "Counterparty"]
    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()


# ── Result ────────────────────────────────────────────────────────────────────

if result is None:
    st.info("Click **Investigate** to run the agent on this case.")
    st.stop()

decision = result["decision"]
confidence = result["confidence"]

# 1. Decision banner
if decision == "ESCALATE":
    st.error(f"### 🚩 ESCALATE — file STR  ·  confidence {confidence:.0%}"
             + (f"  ·  typology: {result['detected_typology']}"
                if result["detected_typology"] else ""))
elif decision == "DISMISS":
    st.success(f"### ✅ DISMISS — no STR warranted  ·  confidence {confidence:.0%}")
else:
    st.warning(f"### Decision: {decision}")

st.caption(f"Agent latency: {result['latency_seconds']}s")

# 2. Investigation steps (audit trail)
with st.expander("🧭 Investigation steps (agent audit trail)", expanded=False):
    for i, step in enumerate(result["investigation_steps"], 1):
        st.markdown(f"**{i}.** {step}")

# 3. Full STR report
st.subheader("📄 Suspicious Transaction Report (STR)")
st.code(result["report"], language="markdown")

st.divider()


# ── Human-in-the-loop: approve / override ─────────────────────────────────────

st.subheader("Reviewer action")
st.caption("The agent assists; the compliance officer decides. Record your action below.")

review_col, note_col = st.columns([1, 2])
with review_col:
    action = st.radio(
        "Decision",
        options=["Approve agent decision", f"Override → {('DISMISS' if decision=='ESCALATE' else 'ESCALATE')}"],
        index=0,
    )
with note_col:
    note = st.text_area("Reviewer note (optional)", placeholder="Rationale for your decision…")

if st.button("💾 Record review", type="primary"):
    if action.startswith("Approve"):
        final = decision
        st.success(f"Recorded: reviewer **approved** the agent decision ({final}).")
    else:
        final = "DISMISS" if decision == "ESCALATE" else "ESCALATE"
        st.warning(f"Recorded: reviewer **overrode** the agent → **{final}**.")
    if note.strip():
        st.caption(f"Note: {note.strip()}")
