/* ============================================================
   Vigil — frontend logic
   ============================================================ */

const $ = (sel) => document.querySelector(sel);

// ---- Finance / fincrime / AML / KYC facts (rotated during investigation) ----
const FACTS = [
  "The UN estimates 2–5% of global GDP — up to <b>$2 trillion</b> — is laundered every year.",
  "In India, any cash transaction of <b>₹10 lakh or more</b> must be reported to FIU-IND as a CTR.",
  "Under PMLA Rules 2005, Rule 8(2), a Suspicious Transaction Report must be filed <b>“promptly”</b> — not on a fixed 7-day clock.",
  "<b>Structuring</b> (a.k.a. smurfing) splits a large sum into smaller deposits to slip under reporting thresholds.",
  "The <b>FATF</b> sets the global AML standard through its 40 Recommendations, adopted by 200+ jurisdictions.",
  "<b>Layering</b> is the money-laundering stage where illicit funds are moved rapidly to obscure their origin.",
  "A <b>PEP</b> — Politically Exposed Person — triggers mandatory Enhanced Due Diligence under RBI KYC norms.",
  "India’s <b>FIU-IND</b> received over 25 lakh STRs in a recent year — humans can’t triage that volume alone.",
  "<b>KYC</b> (Know Your Customer) is the first line of defence: verify identity before money moves.",
  "Trade-based money laundering hides value in <b>over- and under-invoiced</b> shipments of real goods.",
  "‘<b>Placement</b>’ is the riskiest laundering stage — getting dirty cash into the financial system.",
  "Sanctions screening must catch not just exact names but <b>aliases and fuzzy matches</b>.",
  "A single missed sanctions hit can mean <b>multi-million-dollar fines</b> and criminal liability.",
  "The PMLA, 2002 is India’s principal anti-money-laundering statute — enforced by the <b>Enforcement Directorate</b>.",
  "<b>Rapid pass-through</b>: a large credit followed by many quick debits to new payees is a classic red flag.",
  "Most AML alerts are <b>false positives</b> — the hard part is precision, not just catching everything.",
  "Beneficial-ownership opacity via shell companies is the <b>#1 enabler</b> of cross-border laundering.",
  "RBI requires banks to risk-categorise every customer as <b>low, medium, or high</b> risk.",
];

const PIPELINE_STAGES = ["planner", "investigator", "reasoner", "reporter"];

let currentCase = null;
let factTimer = null;
let stageTimer = null;
let agentDecision = null;

// ---- Theme ----
function initTheme() {
  const saved = localStorage.getItem("vigil-theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);
}
$("#themeToggle").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("vigil-theme", next);
});

// ---- Helpers ----
const lakh = (n) => "₹" + (n / 1e5).toFixed(2) + "L";
const inr = (n) => "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ---- Load a sample case ----
async function loadSample() {
  $("#resultPanel").classList.add("hidden");
  $("#resultPanel").innerHTML = "";
  $("#investigateBtn").disabled = true;
  $("#caseBody").innerHTML = `<div class="skeleton-grid"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>`;
  try {
    const res = await fetch("/sample");
    if (!res.ok) throw new Error("HTTP " + res.status);
    currentCase = await res.json();
    renderCase(currentCase);
    $("#investigateBtn").disabled = false;
  } catch (e) {
    $("#caseBody").innerHTML = `<p style="color:var(--danger)">Could not load a sample case (${esc(e.message)}). Is the API running?</p>`;
  }
}

function renderCase(c) {
  const cu = c.customer;
  const txns = c.transactions;
  const rows = txns.map((t) => `
    <tr>
      <td>${esc(t.timestamp.slice(0, 10))}</td>
      <td><span class="tag ${t.direction}">${esc(t.direction)}</span></td>
      <td>${esc(t.channel)}</td>
      <td class="amt">${inr(t.amount_inr)}</td>
      <td>${esc(t.counterparty_name)}</td>
    </tr>`).join("");

  $("#caseBody").innerHTML = `
    <div class="metrics">
      <div class="metric"><div class="metric-label">Case ID</div><div class="metric-value mono">${esc(c.case_id)}</div></div>
      <div class="metric wide"><div class="metric-label">Customer</div><div class="metric-value">${esc(cu.name)}</div></div>
      <div class="metric"><div class="metric-label">Prior flags</div><div class="metric-value">${cu.prior_flags}</div></div>
      <div class="metric"><div class="metric-label">Business type</div><div class="metric-value">${esc(cu.business_type)}</div></div>
      <div class="metric"><div class="metric-label">Monthly turnover</div><div class="metric-value mono">${lakh(cu.stated_monthly_turnover_inr)}</div></div>
      <div class="metric"><div class="metric-label">Transactions</div><div class="metric-value">${txns.length}</div></div>
      <div class="metric"><div class="metric-label">Account opened</div><div class="metric-value mono">${esc(cu.account_open_date.slice(0,10))}</div></div>
    </div>
    <button class="txn-toggle" id="txnToggle">
      <span>View ${txns.length} transactions</span>
      <svg class="chev" viewBox="0 0 24 24" fill="none" width="16" height="16"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <div class="txn-wrap" id="txnWrap">
      <table class="txns">
        <thead><tr><th>Date</th><th>Direction</th><th>Channel</th><th style="text-align:right">Amount</th><th>Counterparty</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  $("#txnToggle").addEventListener("click", () => {
    $("#txnToggle").classList.toggle("open");
    $("#txnWrap").classList.toggle("open");
  });
}

// ---- Loading experience ----
function startLoadingAnimation() {
  $("#loadingOverlay").classList.remove("hidden");
  // facts
  let fi = Math.floor(Math.random() * FACTS.length);
  const factEl = $("#factText");
  factEl.innerHTML = FACTS[fi];
  factTimer = setInterval(() => {
    factEl.classList.add("fading");
    setTimeout(() => {
      fi = (fi + 1) % FACTS.length;
      factEl.innerHTML = FACTS[fi];
      factEl.classList.remove("fading");
    }, 400);
  }, 4200);

  // pipeline stages advance on a timer (cosmetic; holds at reporter until response)
  const items = [...document.querySelectorAll("#pipeline li")];
  items.forEach((li) => li.classList.remove("active", "done"));
  let si = 0;
  items[0].classList.add("active");
  stageTimer = setInterval(() => {
    if (si < items.length - 1) {
      items[si].classList.remove("active");
      items[si].classList.add("done");
      si++;
      items[si].classList.add("active");
    }
  }, 5500);
}

function stopLoadingAnimation() {
  clearInterval(factTimer);
  clearInterval(stageTimer);
  document.querySelectorAll("#pipeline li").forEach((li) => { li.classList.remove("active"); li.classList.add("done"); });
  $("#loadingOverlay").classList.add("hidden");
}

// ---- Investigate ----
async function investigate() {
  if (!currentCase) return;
  startLoadingAnimation();
  const started = performance.now();
  try {
    const res = await fetch("/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentCase),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    // ensure the animation is visible for at least a beat
    const elapsed = performance.now() - started;
    if (elapsed < 1800) await new Promise((r) => setTimeout(r, 1800 - elapsed));
    stopLoadingAnimation();
    renderResult(data);
  } catch (e) {
    stopLoadingAnimation();
    showToast("Investigation failed: " + e.message, true);
  }
}

function renderResult(data) {
  agentDecision = data.decision;
  const esc8 = data.decision === "ESCALATE";
  const pct = Math.round((data.confidence || 0) * 100);
  const circ = 2 * Math.PI * 32;
  const offset = circ * (1 - (data.confidence || 0));

  const steps = (data.investigation_steps || []).map((s) => {
    const m = s.match(/^([^:]+):\s*(.*)$/);
    return m ? `<li><b>${esc(m[1])}</b> — ${esc(m[2])}</li>` : `<li>${esc(s)}</li>`;
  }).join("");

  const verdictText = esc8 ? "ESCALATE — file STR" : "DISMISS — no STR warranted";
  const subText = esc8
    ? "Suspicious activity identified. Recommend filing a Suspicious Transaction Report with FIU-IND."
    : "No reportable suspicion found. Activity consistent with the customer profile.";

  const icon = esc8
    ? `<svg viewBox="0 0 24 24" fill="none"><path d="M12 9v4M12 17h.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>`
    : `<svg viewBox="0 0 24 24" fill="none"><path d="M20 6 9 17l-5-5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

  const typChip = (esc8 && data.detected_typology)
    ? `<span class="typ-chip">typology: ${esc(data.detected_typology)}</span>` : "";

  $("#resultPanel").innerHTML = `
    <div class="banner ${esc8 ? "escalate" : "dismiss"}">
      <div class="banner-row">
        <div class="banner-icon">${icon}</div>
        <div class="banner-main">
          <div class="banner-verdict">${verdictText}</div>
          <div class="banner-sub">${subText}</div>
          ${typChip}
        </div>
        <div class="conf-ring">
          <svg width="76" height="76">
            <circle class="track" cx="38" cy="38" r="32" fill="none" stroke-width="6"/>
            <circle class="fill" cx="38" cy="38" r="32" fill="none" stroke-width="6"
              stroke-dasharray="${circ}" stroke-dashoffset="${circ}" id="confFill"/>
          </svg>
          <div class="conf-val">${pct}%</div>
        </div>
      </div>
    </div>

    <div class="card open" id="auditCard">
      <div class="card-head" data-card="auditCard">
        <h3><svg viewBox="0 0 24 24" fill="none" width="17" height="17"><path d="M9 5H5v14h14v-4M14 4h6v6M20 4l-9 9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg> Investigation steps</h3>
        <svg class="chev" viewBox="0 0 24 24" fill="none" width="18" height="18"><path d="m6 9 6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
      <div class="card-body"><div class="card-inner"><ul class="timeline">${steps}</ul></div></div>
    </div>

    <div class="card">
      <div class="report-head">
        <h3><svg viewBox="0 0 24 24" fill="none" width="17" height="17"><path d="M14 3v5h5M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-5z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg> Suspicious Transaction Report</h3>
        <button class="copy-btn" id="copyBtn"><svg viewBox="0 0 24 24" fill="none"><rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10" stroke="currentColor" stroke-width="2"/></svg> Copy</button>
      </div>
      <div class="report-body" id="reportBody">${esc(data.report)}</div>
    </div>

    <div class="card reviewer-card">
      <div class="reviewer">
        <h3>Reviewer action</h3>
        <p class="hint">The agent assists; the compliance officer decides. Record your action below.</p>
        <div class="seg" id="reviewSeg">
          <button class="active" data-act="approve">Approve agent decision</button>
          <button class="override" data-act="override">Override → ${esc8 ? "DISMISS" : "ESCALATE"}</button>
        </div>
        <textarea class="note" id="reviewNote" placeholder="Rationale for your decision (optional)…"></textarea>
        <button class="btn btn-primary" id="recordBtn" style="width:auto">Record review</button>
      </div>
    </div>`;

  $("#resultPanel").classList.remove("hidden");
  // animate confidence ring + count
  requestAnimationFrame(() => { setTimeout(() => { $("#confFill").style.strokeDashoffset = offset; }, 100); });
  $("#resultPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  wireResult(esc8);
}

function wireResult(esc8) {
  $('[data-card="auditCard"]').addEventListener("click", () => $("#auditCard").classList.toggle("open"));
  $("#copyBtn").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("#reportBody").innerText);
    showToast("STR report copied to clipboard");
  });
  let action = "approve";
  $("#reviewSeg").querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      $("#reviewSeg").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      action = b.dataset.act;
    });
  });
  $("#recordBtn").addEventListener("click", () => {
    if (action === "approve") {
      showToast(`Recorded: reviewer approved the agent decision (${agentDecision}).`);
    } else {
      const overridden = esc8 ? "DISMISS" : "ESCALATE";
      showToast(`Recorded: reviewer overrode the agent → ${overridden}.`, true);
    }
  });
}

// ---- Toast ----
function showToast(msg, warn = false) {
  const t = $("#toast");
  t.className = "toast" + (warn ? " warn" : "");
  t.innerHTML = `<span class="tdot"></span>${esc(msg)}`;
  t.classList.remove("hidden");
  requestAnimationFrame(() => t.classList.add("show"));
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.classList.add("hidden"), 400);
  }, 3200);
}

// ---- Init ----
initTheme();
$("#loadSample").addEventListener("click", loadSample);
$("#investigateBtn").addEventListener("click", investigate);
loadSample();
