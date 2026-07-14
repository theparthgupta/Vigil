/* ============================================================
   Vigil - frontend logic
   ============================================================ */

const $ = (sel) => document.querySelector(sel);

let currentCase = null;
let agentDecision = null;
let lastReport = "";
let lastCaseId = null;   // case_id of the investigation on screen (for reviews)

// ---- Dashboard stats band (Phase 10B) ----
function animateNum(el, target, suffix = "") {
  const start = parseFloat(el.dataset.val || "0");
  const t0 = performance.now();
  const dur = 600;
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / dur);
    const v = start + (target - start) * (1 - Math.pow(1 - p, 3));
    el.textContent = (suffix === "%" ? v.toFixed(1) : Math.round(v)) + suffix;
    if (p < 1) requestAnimationFrame(tick);
    else el.dataset.val = target;
  };
  requestAnimationFrame(tick);
}

async function loadStats() {
  try {
    const res = await fetch("/dashboard/stats");
    if (!res.ok) return;
    const s = await res.json();
    if (!s.total_cases) return;              // nothing screened yet - keep band hidden
    $("#statsBand").classList.remove("hidden");
    animateNum($("#st-total"), s.total_cases);
    animateNum($("#st-flagged"), s.flagged);
    animateNum($("#st-review"), s.in_review);
    animateNum($("#st-str"), s.str_filed);
    animateNum($("#st-noise"), s.noise_reduction_pct, "%");
    $("#st-spend").textContent = "₹" + (s.llm_spend_inr || 0).toFixed(2);
    $("#st-spend").title = `Avg ₹${(s.avg_cost_per_investigation_inr || 0).toFixed(2)} per LLM investigation (${s.investigated_with_llm || 0} runs)`;
    $("#st-saved").textContent = "₹" + (s.est_saved_by_triage_inr || 0).toFixed(2);
    $("#st-saved").title = `${s.auto_dismissed} auto-dismissed cases × avg investigation cost - LLM runs the triage layers avoided`;
    // The feedback loop: falling agreement = time to re-tune the threshold/fusion.
    if (s.reviews_recorded > 0) {
      $("#st-agree").textContent = s.agent_agreement_pct.toFixed(0) + "%";
      $("#st-agree").title = `${s.review_approvals} of ${s.reviews_recorded} human reviews approved the agent's decision (${s.review_overrides} override${s.review_overrides === 1 ? "" : "s"})`;
    } else {
      $("#st-agree").textContent = "-";
      $("#st-agree").title = "No human reviews recorded yet";
    }
  } catch { /* dashboard is a nicety - never block the app on it */ }
}

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
// The pipeline steps are driven by REAL Server-Sent Events from the agent
// (see investigate()), so the UI shows exactly what the agent is doing.
function startLoadingAnimation() {
  $("#loadingOverlay").classList.remove("hidden");
  $("#liveStatus").textContent = "Initializing…";
  document.querySelectorAll("#pipeline li").forEach((li) => li.classList.remove("active", "done"));
}

function stopLoadingAnimation() {
  document.querySelectorAll("#pipeline li").forEach((li) => { li.classList.remove("active"); li.classList.add("done"); });
  $("#loadingOverlay").classList.add("hidden");
}

function setStageActive(stage) {
  const li = document.querySelector(`#pipeline li[data-stage="${stage}"]`);
  if (li) li.classList.add("active");
}
function setStageDone(stage) {
  const li = document.querySelector(`#pipeline li[data-stage="${stage}"]`);
  if (li) { li.classList.remove("active"); li.classList.add("done"); }
}

// ---- Investigate (streams per-node progress via SSE) ----
async function runInvestigation(caseObj, detectionResult = null) {
  if (!caseObj) return;
  startLoadingAnimation();
  try {
    // If the case came from the batch queue it already went through /detect;
    // pass that detection_result so the agent skips redundant tool calls (Phase 8E gate).
    const body = detectionResult ? { ...caseObj, detection_result: detectionResult } : caseObj;
    const res = await fetch("/investigate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok || !res.body) throw new Error("HTTP " + res.status);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop();                       // keep any partial frame
      for (const frame of frames) {
        if (!frame.trim()) continue;
        const ev = (frame.match(/^event: (.*)$/m) || [])[1]?.trim() || "message";
        const dataLine = (frame.match(/^data: (.*)$/m) || [])[1];
        if (!dataLine) continue;
        const data = JSON.parse(dataLine);
        if (ev === "status") {
          setStageActive(data.stage);
          $("#liveStatus").textContent = data.message;
        } else if (ev === "node") {
          setStageDone(data.node);
          $("#liveStatus").textContent = data.message;
        } else if (ev === "done") {
          result = data;
        }
      }
    }

    stopLoadingAnimation();
    if (result) { renderResult(result); loadStats(); }
    else showToast("No result received from the agent", true);
  } catch (e) {
    stopLoadingAnimation();
    showToast("Investigation failed: " + e.message, true);
  }
}

// Render the STR markdown as a clean formatted document (no raw asterisks).
function renderReportMarkdown(md) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const lines = md.replace(/\r/g, "").split("\n");
  let html = "", listOpen = false, firstHeading = true;
  const closeList = () => { if (listOpen) { html += "</ul>"; listOpen = false; } };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) { closeList(); continue; }

    const headingMatch = line.match(/^\*\*(.+?)\*\*:?\s*$/);
    if (headingMatch && !line.trim().startsWith("-")) {
      closeList();
      const text = headingMatch[1];
      if (firstHeading) { html += `<div class="rd-title">${esc(text)}</div>`; firstHeading = false; }
      else { html += `<div class="rd-h">${esc(text)}</div>`; }
      continue;
    }

    if (/^\s*-\s+/.test(raw)) {
      if (!listOpen) { html += '<ul class="rd-list">'; listOpen = true; }
      const sub = /^\s{2,}-\s+/.test(raw) ? " rd-sub" : "";
      html += `<li class="${sub.trim()}">${inline(raw.replace(/^\s*-\s+/, ""))}</li>`;
      continue;
    }

    closeList();
    html += `<p class="rd-p">${inline(line)}</p>`;
  }
  closeList();
  return html;
}

function renderResult(data) {
  agentDecision = data.decision;
  lastCaseId = data.case_id || null;
  const esc8 = data.decision === "ESCALATE";
  const pct = Math.round((data.confidence || 0) * 100);
  const circ = 2 * Math.PI * 26;
  const offset = circ * (1 - (data.confidence || 0));
  lastReport = data.report || "";

  const steps = (data.investigation_steps || []).map((s) => {
    const m = s.match(/^([^:]+):\s*(.*)$/);
    return m ? `<li><b>${esc(m[1])}</b>: ${esc(m[2])}</li>` : `<li>${esc(s)}</li>`;
  }).join("");

  const verdictText = esc8 ? "ESCALATE · File STR" : "DISMISS · No STR warranted";
  const subText = esc8
    ? "Suspicious activity identified. Recommend filing a Suspicious Transaction Report with FIU-IND."
    : "No reportable suspicion found. Activity consistent with the customer profile.";

  const icon = esc8
    ? `<svg viewBox="0 0 24 24" fill="none"><path d="M12 9v4M12 17h.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>`
    : `<svg viewBox="0 0 24 24" fill="none"><path d="M20 6 9 17l-5-5" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

  const typChip = (esc8 && data.detected_typology)
    ? `<span class="typ-chip">typology: ${esc(data.detected_typology)}</span>` : "";
  const costChip = data.tokens_used
    ? `<span class="typ-chip cost-chip" title="${data.tokens_used.toLocaleString()} tokens · gpt-4o-mini, deterministic price math">cost: ₹${(data.cost_inr || 0).toFixed(2)} · ${(data.latency_seconds || 0).toFixed(0)}s</span>` : "";

  $("#resultPanel").innerHTML = `
    <div class="banner ${esc8 ? "escalate" : "dismiss"}">
      <div class="banner-row">
        <div class="banner-icon">${icon}</div>
        <div class="banner-main">
          <div class="banner-verdict">${verdictText}</div>
          <div class="banner-sub">${subText}</div>
          ${typChip}${costChip}
        </div>
        <div class="conf-ring">
          <svg width="64" height="64">
            <circle class="track" cx="32" cy="32" r="26" fill="none" stroke-width="5"/>
            <circle class="fill" cx="32" cy="32" r="26" fill="none" stroke-width="5"
              stroke-dasharray="${circ}" stroke-dashoffset="${circ}" id="confFill"/>
          </svg>
          <div class="conf-val">${pct}%</div>
          <div class="conf-cap">confidence</div>
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
        <div class="rh-left">
          <svg viewBox="0 0 24 24" fill="none"><path d="M14 3v5h5M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-5z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>
          <div>
            <h3>Suspicious Transaction Report</h3>
            <div class="rh-sub">FIU-IND · PMLA 2002</div>
          </div>
        </div>
        <button class="copy-btn" id="copyBtn"><svg viewBox="0 0 24 24" fill="none"><rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" stroke-width="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10" stroke="currentColor" stroke-width="2"/></svg> Copy</button>
      </div>
      <div class="report-doc" id="reportBody">${renderReportMarkdown(data.report || "")}</div>
    </div>

    <div class="card reviewer-card">
      <div class="reviewer">
        <h3>Reviewer action</h3>
        <p class="hint">The agent assists; the compliance officer decides. Record your action below.</p>
        <div class="seg" id="reviewSeg">
          <button class="active" data-act="approve">Approve agent decision</button>
          <button class="override" data-act="override">Override → ${esc8 ? "DISMISS" : "ESCALATE"}</button>
        </div>
        <input id="reviewerName" class="rev-input" type="text" placeholder="Reviewer name - e.g. R. Mehta, MLRO" />
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
    await navigator.clipboard.writeText(lastReport);
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
  $("#recordBtn").addEventListener("click", async () => {
    const reviewer = $("#reviewerName").value.trim();
    if (!reviewer) { showToast("Reviewer name is required for the audit trail", true); return; }
    if (!lastCaseId) { showToast("No case to review", true); return; }
    try {
      const res = await fetch(`/cases/${encodeURIComponent(lastCaseId)}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, action, rationale: $("#reviewNote").value.trim() }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "HTTP " + res.status);
      const label = body.final_status === "str_filed" ? "STR FILED" : "DISMISSED";
      showToast(`Review recorded by ${reviewer} → case ${label}. Logged to audit trail.`);
      $("#recordBtn").disabled = true;
      loadStats();
    } catch (e) {
      showToast("Could not record review: " + e.message, true);
    }
  });
}

// ============================================================
//  Custom case mode
// ============================================================
let mode = "sample";

// Every form value is a valid enum value in data/schema.py (BusinessType,
// Channel, Direction), so values pass through directly with no mapping.
const CHANNELS = ["UPI", "NEFT", "RTGS", "cash", "IMPS"];

const randHex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");
const randDigits = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 10)).join("");

function txnRow(p = {}) {
  const row = document.createElement("div");
  row.className = "ctxn-row";
  row.innerHTML = `
    <input class="ct-date" type="date" value="${p.date || ""}" />
    <input class="ct-amount" type="number" min="0" step="1000" placeholder="0" value="${p.amount || ""}" />
    <select class="ct-direction">
      <option value="credit"${p.direction === "credit" ? " selected" : ""}>Credit</option>
      <option value="debit"${p.direction === "debit" ? " selected" : ""}>Debit</option>
    </select>
    <select class="ct-channel">${CHANNELS.map((c) => `<option${p.channel === c ? " selected" : ""}>${c}</option>`).join("")}</select>
    <input class="ct-cp" type="text" placeholder="Counterparty name" value="${p.cp ? esc(p.cp) : ""}" />
    <button type="button" class="ctxn-remove" title="Remove transaction">&times;</button>`;
  row.querySelector(".ctxn-remove").addEventListener("click", () => {
    if (document.querySelectorAll("#ctxn-rows .ctxn-row").length <= 1) {
      showToast("At least one transaction is required", true);
      return;
    }
    row.remove();
  });
  return row;
}

function addTxnRow(p) { $("#ctxn-rows").appendChild(txnRow(p)); }

// Pre-fill with a realistic structuring example so the format is obvious.
function seedCustomForm() {
  $("#cf-name").value = "Sharma Textiles";
  $("#cf-btype").value = "sme";
  $("#cf-turnover").value = "45";
  $("#cf-flags").value = "1";
  $("#cf-opened").value = "2021-06-15";
  $("#ctxn-rows").innerHTML = "";
  addTxnRow({ date: "2024-03-05", amount: 920000, direction: "credit", channel: "cash", cp: "Cash Deposit - Mumbai Andheri Branch" });
  addTxnRow({ date: "2024-03-14", amount: 880000, direction: "credit", channel: "cash", cp: "Cash Deposit - Pune Kothrud Branch" });
  addTxnRow({ date: "2024-03-22", amount: 950000, direction: "credit", channel: "cash", cp: "Cash Deposit - Delhi CP Branch" });
}

// Validate the form and build a schema-valid Case JSON, or null on error.
function buildCustomCase() {
  const name = $("#cf-name").value.trim();
  if (!name) { showToast("Customer name is required", true); return null; }

  const rows = [...document.querySelectorAll("#ctxn-rows .ctxn-row")];
  if (rows.length < 1) { showToast("Add at least one transaction", true); return null; }

  const cid = "cust_custom_" + randHex(6);
  const transactions = [];
  for (const row of rows) {
    const date = row.querySelector(".ct-date").value;
    const amount = parseFloat(row.querySelector(".ct-amount").value);
    const cp = row.querySelector(".ct-cp").value.trim();
    if (!date || !(amount > 0) || !cp) {
      showToast("Each transaction needs a date, an amount and a counterparty", true);
      return null;
    }
    transactions.push({
      id: "txn_" + randHex(8),
      customer_id: cid,
      amount_inr: amount,
      timestamp: date + "T00:00:00",
      counterparty_name: cp,
      counterparty_account: randDigits(14),
      direction: row.querySelector(".ct-direction").value,
      channel: row.querySelector(".ct-channel").value,
    });
  }

  const opened = $("#cf-opened").value || "2020-01-01";
  return {
    case_id: "case_custom_" + Date.now().toString(36),
    customer: {
      id: cid,
      name,
      business_type: $("#cf-btype").value,
      account_open_date: opened + "T00:00:00",
      stated_monthly_turnover_inr: (parseFloat($("#cf-turnover").value) || 0) * 1e5,
      prior_flags: parseInt($("#cf-flags").value, 10) || 0,
    },
    transactions,
    // No ground truth for a user-submitted case; the agent decides.
    // "custom" is an explicit Label sentinel (data/schema.py).
    ground_truth_label: "custom",
    typology: null,
    notes: "User-submitted custom case.",
  };
}

function setMode(m) {
  mode = m;
  document.querySelectorAll("#caseTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.mode === m));
  $("#sampleMode").classList.toggle("hidden", m !== "sample");
  $("#customMode").classList.toggle("hidden", m !== "custom");
  $("#batchMode").classList.toggle("hidden", m !== "batch");
  $("#historyMode").classList.toggle("hidden", m !== "history");
  $("#resultPanel").classList.add("hidden");
  // Batch/history modes have their own actions; hide the shared investigate button.
  $("#investigateBtn").classList.toggle("hidden", m === "batch" || m === "history");
  $("#investigateBtn").disabled = m === "sample" ? !currentCase : false;
  if (m === "history") loadHistory();
  if (m === "batch" && !parsedCases && $("#batchResults").classList.contains("hidden")) restoreBatch();
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

// ============================================================
//  Batch triage mode
// ============================================================
let parsedCases = null;
let batchQueue = [];

const typoLabel = (t) => (t || "-").replace(/_/g, " ");
const riskTier = (s) => (s >= 0.85 ? "red" : s >= 0.70 ? "orange" : "yellow");

// Four mini-bars showing what each detection layer contributed (explainability).
const _LAYERS = [
  ["typology",   "T", "Typology rules"],
  ["graph",      "G", "Graph analysis"],
  ["behavioral", "B", "Behavioral baseline"],
  ["anomaly",    "A", "ML anomaly"],
];
function layerBars(ls) {
  if (!ls) return "-";
  return `<div class="layers">` + _LAYERS.map(([key, tag, name]) => {
    const v = ls[key] || 0;
    const h = Math.max(8, Math.round(v * 100));
    return `<div class="layer" title="${name}: ${v.toFixed(2)}">
      <div class="layer-track"><span class="layer-fill lf-${key}" style="height:${h}%"></span></div>
      <span class="layer-tag">${tag}</span>
    </div>`;
  }).join("") + `</div>`;
}

async function handleCsvFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    showToast("Please upload a .csv file", true);
    return;
  }
  $("#batchWarn").classList.add("hidden");
  $("#batchPreview").classList.add("hidden");
  $("#batchResults").classList.add("hidden");
  $("#runBatchBtn").disabled = true;
  parsedCases = null;

  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/parse-csv", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.detail || "Parse failed (HTTP " + res.status + ")", true);
      return;
    }
    if ((data.warnings || []).length) {
      $("#batchWarn").innerHTML =
        `<b>${data.warnings.length} row(s) skipped:</b><ul>` +
        data.warnings.map((w) => `<li>${esc(w)}</li>`).join("") + "</ul>";
      $("#batchWarn").classList.remove("hidden");
    }
    if (!data.customer_count) {
      showToast("No valid cases found in the CSV", true);
      return;
    }
    parsedCases = data.cases;
    renderBatchPreview(data);
    $("#runBatchBtn").disabled = false;
  } catch (e) {
    showToast("Upload failed: " + e.message, true);
  }
}

function renderBatchPreview(data) {
  const rows = data.cases.map((c) =>
    `<tr><td>${esc(c.customer.name)}</td><td class="num">${c.transactions.length}</td><td>${esc(c.customer.business_type)}</td></tr>`
  ).join("");
  $("#batchPreview").innerHTML = `
    <div class="bp-summary">Parsed <b>${data.customer_count}</b> customers · <b>${data.total_transaction_count}</b> transactions</div>
    <details class="bp-details">
      <summary>Preview customers</summary>
      <table class="bp-table"><thead><tr><th>Customer</th><th class="num">Txns</th><th>Business type</th></tr></thead><tbody>${rows}</tbody></table>
    </details>`;
  $("#batchPreview").classList.remove("hidden");
}

async function runBatch() {
  if (!parsedCases) return;
  $("#runBatchBtn").disabled = true;
  $("#batchResults").classList.remove("hidden");
  $("#batchResults").innerHTML = `<div class="batch-spin"><span class="spinner"></span>Screening ${parsedCases.length} cases…</div>`;
  try {
    const res = await fetch("/triage-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cases: parsedCases }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    renderBatchResults(await res.json());
  } catch (e) {
    $("#batchResults").innerHTML = `<p style="color:var(--danger)">Triage failed: ${esc(e.message)}</p>`;
  } finally {
    $("#runBatchBtn").disabled = false;
  }
}

function renderBatchResults(data) {
  batchQueue = data.triage_queue || [];
  const dismissed = data.dismissed_cases || [];

  const queueRows = batchQueue.map((r, i) => {
    const tier = riskTier(r.risk_score);
    const pct = Math.round(r.risk_score * 100);
    const top = (r.typology_flags && r.typology_flags[0]) ? r.typology_flags[0].typology : "-";
    return `<tr class="q-row" data-i="${i}" title="Click to see why this case scored ${r.risk_score.toFixed(2)}">
      <td><div class="risk"><svg class="q-chev" viewBox="0 0 24 24" width="14" height="14" fill="none"><path d="m9 6 6 6-6 6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg><div class="risk-bar"><span class="risk-fill ${tier}" style="width:${pct}%"></span></div><span class="risk-num ${tier}">${r.risk_score.toFixed(2)}</span></div></td>
      <td>${esc(r.customer_name)}</td>
      <td><span class="typ-pill ${tier}">${esc(typoLabel(top))}</span></td>
      <td>${layerBars(r.layer_scores)}</td>
      <td><button class="btn btn-ghost btn-row-inv" data-i="${i}">Investigate →</button></td>
    </tr>`;
  }).join("");

  const dismRows = dismissed.map((d) =>
    `<li><span>${esc(d.customer_name)}</span><span class="num">${d.risk_score.toFixed(2)}</span></li>`
  ).join("");

  $("#batchResults").innerHTML = `
    <div class="batch-banner">
      Processed <b>${data.total_cases}</b> cases · <b class="hi">${data.flagged_for_investigation}</b> flagged for investigation ·
      <b>${data.auto_dismissed}</b> auto-dismissed · <b class="hi">${data.false_positive_reduction_pct}%</b> noise reduction
    </div>
    ${batchQueue.length
      ? `<table class="queue"><thead><tr><th>Risk score</th><th>Customer</th><th>Top typology</th><th>Layer signals</th><th></th></tr></thead><tbody>${queueRows}</tbody></table>`
      : `<p class="muted">No cases cleared the triage threshold.</p>`}
    ${dismissed.length
      ? `<details class="dismissed"><summary>Auto-dismissed (${dismissed.length} cases)</summary><ul class="dism-list">${dismRows}</ul></details>`
      : ""}`;

  $("#batchResults").querySelectorAll(".btn-row-inv").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      investigateFromQueue(parseInt(b.dataset.i, 10));
    })
  );
  $("#batchResults").querySelectorAll(".q-row").forEach((row) =>
    row.addEventListener("click", () => toggleExplainRow(parseInt(row.dataset.i, 10), row))
  );
  loadStats();
}

async function investigateFromQueue(i) {
  const row = batchQueue[i];
  if (!row) return;
  let caseObj = (parsedCases || []).find((c) => c.case_id === row.case_id);
  if (!caseObj) {
    // Restored batch (page was refreshed): pull the persisted payload instead.
    try {
      const res = await fetch(`/cases/${encodeURIComponent(row.case_id)}`);
      if (!res.ok) throw new Error("HTTP " + res.status);
      caseObj = (await res.json()).payload;
    } catch (e) {
      showToast("Case not found in parsed batch or store", true);
      return;
    }
  }
  // Reuse the detection already computed during the batch (Phase 8E gate).
  const detectionResult = {
    typology_flags: row.typology_flags,
    graph_analysis: row.graph_analysis,
    behavioral_analysis: row.behavioral_analysis,
    anomaly_analysis: row.anomaly_analysis,
    risk_score: row.risk_score,
    above_threshold: row.above_threshold,
  };
  runInvestigation(caseObj, detectionResult);
}

// ============================================================
//  Explainability visuals (Phase 12) - all arithmetic is done
//  server-side (monitor/scorer.explain_scores); this only renders.
// ============================================================

// "Why this score" waterfall: signed per-feature contributions from the
// learned fusion. Red bars push toward ESCALATE, blue pull toward DISMISS.
function renderWaterfall(exp) {
  if (!exp || !exp.items) return "";
  const rows = [{ label: "Baseline (intercept)", contribution: exp.intercept, base: true }]
    .concat(exp.items);
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.contribution)), 0.1);

  const W = 460, ROW = 30, PAD_L = 168, PAD_R = 52, TOP = 26;
  const zero = PAD_L + (W - PAD_L - PAD_R) / 2;
  const half = (W - PAD_L - PAD_R) / 2 - 4;
  const H = TOP + rows.length * ROW + 46;

  const bars = rows.map((r, i) => {
    const y = TOP + i * ROW;
    const w = Math.max(2, Math.abs(r.contribution) / maxAbs * half);
    const pos = r.contribution >= 0;
    const x = pos ? zero : zero - w;
    // 4px rounded data-end, square at the zero baseline
    const rx = pos
      ? `M${x},${y} h${Math.max(0, w - 4)} a4,4 0 0 1 4,4 v8 a4,4 0 0 1 -4,4 h-${Math.max(0, w - 4)} z`
      : `M${x + w},${y} h-${Math.max(0, w - 4)} a4,4 0 0 0 -4,4 v8 a4,4 0 0 0 4,4 h${Math.max(0, w - 4)} z`;
    const fill = r.base ? "var(--text-dim)" : pos ? "var(--danger)" : "var(--info)";
    let tipX = pos ? x + w + 6 : x - 6;
    let anchor = pos ? "start" : "end";
    let inBar = false;
    // A long leftward bar would push its tip label into the row-label gutter -
    // measure, and move the value inside the bar instead of colliding.
    if (!pos && tipX < PAD_L + 34) { tipX = x + 8; anchor = "start"; inBar = true; }
    if (pos && tipX > W - 8) { tipX = x + w - 8; anchor = "end"; inBar = true; }
    const val = (r.contribution >= 0 ? "+" : "") + r.contribution.toFixed(2);
    const detail = r.base ? `Baseline ${val}`
      : `${r.label}: value ${r.value} × weight ${r.weight >= 0 ? "+" : ""}${r.weight} = ${val}`;
    return `<g class="wf-row">
      <title>${esc(detail)}</title>
      <rect x="0" y="${y - 6}" width="${W}" height="${ROW}" fill="transparent"/>
      <text x="${PAD_L - 10}" y="${y + 12}" text-anchor="end" class="wf-label">${esc(r.label)}</text>
      <path d="${rx}" fill="${fill}" opacity="${r.base ? 0.55 : 0.9}"/>
      <text x="${tipX}" y="${y + 12}" text-anchor="${anchor}" class="wf-val${inBar ? " in-bar" : ""}">${val}</text>
    </g>`;
  }).join("");

  const fy = TOP + rows.length * ROW + 14;
  const pct = Math.round(exp.risk_score * 100);
  const finalNote = exp.sanctions_override
    ? `sanctions hit → overridden to 1.00`
    : (exp.mode === "learned_fusion" ? `σ(sum) = ${exp.risk_score.toFixed(2)}` : `weighted sum = ${exp.risk_score.toFixed(2)}`);

  return `
  <div class="wf-wrap">
    <div class="explain-head">
      <span class="explain-title">Why this score</span>
      <span class="wf-legend">
        <span class="wf-key"><span class="wf-swatch raises"></span>raises risk</span>
        <span class="wf-key"><span class="wf-swatch lowers"></span>lowers risk</span>
      </span>
    </div>
    <svg viewBox="0 0 ${W} ${H}" class="wf-svg" role="img" aria-label="Score contribution breakdown">
      <line x1="${zero}" y1="${TOP - 10}" x2="${zero}" y2="${fy - 8}" class="wf-axis"/>
      ${bars}
      <g>
        <line x1="${PAD_L - 10}" y1="${fy - 4}" x2="${W - 8}" y2="${fy - 4}" class="wf-axis"/>
        <text x="${PAD_L - 10}" y="${fy + 16}" text-anchor="end" class="wf-label">Risk score</text>
        <circle cx="${zero}" cy="${fy + 11}" r="6" fill="var(--gold)" stroke="var(--surface)" stroke-width="2"/>
        <text x="${zero + 12}" y="${fy + 16}" class="wf-final">${(exp.risk_score).toFixed(2)} (${pct}%)</text>
        <text x="${W - 8}" y="${fy + 16}" text-anchor="end" class="wf-note">${esc(finalNote)}</text>
      </g>
    </svg>
  </div>`;
}

// Toggleable per-row explain panel in the triage queue.
async function toggleExplainRow(i, btnRow) {
  const existing = document.getElementById(`explain-${i}`);
  if (existing) { existing.remove(); btnRow.classList.remove("expanded"); return; }
  const r = batchQueue[i];
  if (!r) return;
  const tr = document.createElement("tr");
  tr.id = `explain-${i}`;
  tr.className = "explain-tr";
  const td = document.createElement("td");
  td.colSpan = 5;
  td.innerHTML = `<div class="explain-panel">${renderWaterfall(r.score_explanation)}
    <div class="txg-slot" id="txg-${i}"><div class="muted" style="padding:20px">Loading money flow…</div></div></div>`;
  tr.appendChild(td);
  btnRow.after(tr);
  btnRow.classList.add("expanded");
  renderTxnGraphInto(`txg-${i}`, r);
}

// ---- Force-directed money-flow graph (vanilla SVG, no deps) ----
// Nodes: the customer (gold) + counterparties (sized by volume). Red = part of
// a detected pattern (ring / layering chain / fan-out / high centrality).

function _flaggedNodeSet(ga) {
  const s = new Set();
  if (!ga) return s;
  (ga.structuring_ring?.cycles_found || []).flat().forEach((n) => s.add(n));
  (ga.layering_chain?.chains || []).forEach((c) => (c.path || []).forEach((n) => s.add(n)));
  (ga.fan_out?.evidence?.new_recipients || []).forEach((n) => s.add(n));
  (ga.centrality?.high_centrality_nodes || []).forEach((d) => s.add(d.node));
  s.delete("SELF");
  return s;
}

function buildGraphData(caseObj, ga, maxNodes = 22) {
  const agg = {};   // counterparty -> {in, out}
  for (const t of caseObj.transactions) {
    const cp = t.counterparty_name;
    agg[cp] = agg[cp] || { in: 0, out: 0 };
    if (t.direction === "credit") agg[cp].in += t.amount_inr;
    else agg[cp].out += t.amount_inr;
  }
  const flagged = _flaggedNodeSet(ga);
  const ranked = Object.entries(agg)
    .sort((a, b) => (flagged.has(b[0]) - flagged.has(a[0]))
      || (b[1].in + b[1].out) - (a[1].in + a[1].out));
  const kept = ranked.slice(0, maxNodes);
  return {
    nodes: kept.map(([name, v]) => ({ name, vol: v.in + v.out, in: v.in, out: v.out,
                                      flagged: flagged.has(name) })),
    hidden: ranked.length - kept.length,
  };
}

function renderTxnGraphInto(slotId, row) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  const caseObj = (parsedCases || []).find((c) => c.case_id === row.case_id);
  const draw = (co) => { slot.innerHTML = renderTxnGraph(co, row.graph_analysis); };
  if (caseObj) { draw(caseObj); return; }
  fetch(`/cases/${encodeURIComponent(row.case_id)}`)
    .then((r) => r.json())
    .then((d) => draw(d.payload))
    .catch(() => { slot.innerHTML = `<p class="muted">Money-flow view unavailable.</p>`; });
}

function renderTxnGraph(caseObj, ga) {
  const { nodes, hidden } = buildGraphData(caseObj, ga);
  if (!nodes.length) return `<p class="muted">No transactions to draw.</p>`;
  const W = 460, H = 330, CX = W / 2, CY = H / 2;

  // Deterministic force layout: SELF pinned center; counterparties repel each
  // other, spring toward their ring position, and settle in ~220 iterations.
  const N = nodes.length;
  nodes.forEach((n, i) => {
    const a = (i / N) * 2 * Math.PI;
    n.x = CX + Math.cos(a) * 120; n.y = CY + Math.sin(a) * 110;
  });
  for (let it = 0; it < 220; it++) {
    for (let i = 0; i < N; i++) {
      let fx = 0, fy = 0;
      for (let j = 0; j < N; j++) {
        if (i === j) continue;
        const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
        const d2 = Math.max(dx * dx + dy * dy, 40);
        fx += (dx / d2) * 1800; fy += (dy / d2) * 1800;
      }
      // spring to SELF at preferred radius
      const dx = nodes[i].x - CX, dy = nodes[i].y - CY;
      const d = Math.max(Math.hypot(dx, dy), 1);
      const pref = 105 + (i % 3) * 22;
      fx -= (dx / d) * (d - pref) * 0.05; fy -= (dy / d) * (d - pref) * 0.05;
      nodes[i].x += Math.max(-6, Math.min(6, fx));
      nodes[i].y += Math.max(-6, Math.min(6, fy));
      nodes[i].x = Math.max(26, Math.min(W - 26, nodes[i].x));
      nodes[i].y = Math.max(26, Math.min(H - 26, nodes[i].y));
    }
  }

  const maxVol = Math.max(...nodes.map((n) => n.vol));
  const rOf = (v) => 5 + Math.sqrt(v / maxVol) * 7;

  const edges = nodes.map((n) => {
    const parts = [];
    const r = rOf(n.vol);
    if (n.in > 0) parts.push(_edge(n.x, n.y, CX, CY, r, 15, n.in, maxVol, n.flagged, `${n.name} → customer: ${inr(n.in)}`));
    if (n.out > 0) parts.push(_edge(CX, CY, n.x, n.y, 15, r, n.out, maxVol, n.flagged, `customer → ${n.name}: ${inr(n.out)}`));
    return parts.join("");
  }).join("");

  const topNames = new Set(nodes.slice(0, 3).map((n) => n.name));
  const circles = nodes.map((n) => {
    const r = rOf(n.vol);
    const short = n.name.length > 18 ? n.name.slice(0, 17) + "…" : n.name;
    const lx = Math.max(58, Math.min(W - 58, n.x));   // keep labels inside the frame
    const label = (n.flagged || topNames.has(n.name))
      ? `<text x="${lx}" y="${n.y - r - 5}" text-anchor="middle" class="txg-label${n.flagged ? " bad" : ""}">${esc(short)}</text>` : "";
    return `<g class="txg-node">
      <title>${esc(n.name)} - in ${inr(n.in)} · out ${inr(n.out)}${n.flagged ? " · part of a detected pattern" : ""}</title>
      <circle cx="${n.x}" cy="${n.y}" r="${Math.max(12, r)}" fill="transparent"/>
      <circle cx="${n.x}" cy="${n.y}" r="${r}" class="${n.flagged ? "txg-cp flagged" : "txg-cp"}"/>
      ${label}</g>`;
  }).join("");

  return `
  <div class="explain-head">
    <span class="explain-title">Money flow</span>
    <span class="wf-legend">
      <span class="wf-key"><span class="wf-swatch self"></span>customer</span>
      <span class="wf-key"><span class="wf-swatch flaggedn"></span>detected pattern</span>
    </span>
  </div>
  <svg viewBox="0 0 ${W} ${H}" class="txg-svg" role="img" aria-label="Transaction network">
    <defs>
      <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
        <path d="M0,0 L8,4 L0,8 z" fill="var(--text-dim)"/>
      </marker>
      <marker id="arrbad" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">
        <path d="M0,0 L8,4 L0,8 z" fill="var(--danger)"/>
      </marker>
    </defs>
    ${edges}
    ${circles}
    <g class="txg-node"><title>${esc(caseObj.customer.name)}</title>
      <circle cx="${CX}" cy="${CY}" r="15" class="txg-self"/>
      <text x="${CX}" y="${CY + 30}" text-anchor="middle" class="txg-label self">${esc(caseObj.customer.name)}</text>
    </g>
    ${hidden > 0 ? `<text x="${W - 8}" y="${H - 8}" text-anchor="end" class="wf-note">+${hidden} smaller counterparties not shown</text>` : ""}
  </svg>`;
}

function _edge(x1, y1, x2, y2, r1, r2, amt, maxVol, bad, tip) {
  const dx = x2 - x1, dy = y2 - y1, d = Math.max(Math.hypot(dx, dy), 1);
  const sx = x1 + (dx / d) * (r1 + 2), sy = y1 + (dy / d) * (r1 + 2);
  const ex = x2 - (dx / d) * (r2 + 5), ey = y2 - (dy / d) * (r2 + 5);
  const mx = (sx + ex) / 2 - dy / d * 14, my = (sy + ey) / 2 + dx / d * 14;
  const w = Math.max(1.2, Math.sqrt(amt / maxVol) * 3.2);
  return `<g class="txg-edge"><title>${esc(tip)}</title>
    <path d="M${sx},${sy} Q${mx},${my} ${ex},${ey}" fill="none"
      stroke="${bad ? "var(--danger)" : "var(--text-dim)"}" stroke-opacity="${bad ? 0.75 : 0.4}"
      stroke-width="${w}" marker-end="url(#${bad ? "arrbad" : "arr"})"/></g>`;
}

// Restore the last server-side batch (survives a page refresh).
async function restoreBatch() {
  try {
    const res = await fetch("/triage-queue");
    const data = await res.json();
    if (data.total_cases) {
      $("#batchResults").classList.remove("hidden");
      renderBatchResults(data);
      showToast("Restored the last batch from the server");
    }
  } catch { /* no cached batch - nothing to restore */ }
}

// ============================================================
//  Case history (Phase 10B)
// ============================================================
const STATUS_META = {
  flagged:        { label: "Flagged",        cls: "s-flagged" },
  in_review:      { label: "In review",      cls: "s-review" },
  str_filed:      { label: "STR filed",      cls: "s-str" },
  dismissed:      { label: "Dismissed",      cls: "s-dismissed" },
  auto_dismissed: { label: "Auto-dismissed", cls: "s-auto" },
};
let histFilter = "";

async function loadHistory() {
  const url = histFilter ? `/cases?status=${histFilter}&limit=100` : "/cases?limit=100";
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    renderHistory((await res.json()).cases);
  } catch (e) {
    $("#historyBody").innerHTML = `<p style="color:var(--danger)">Could not load history: ${esc(e.message)}</p>`;
  }
}

function renderHistory(cases) {
  if (!cases.length) {
    $("#historyBody").innerHTML = `<p class="muted">No cases here yet. Run a batch triage or investigate a case - everything is persisted.</p>`;
    return;
  }
  const rows = cases.map((c) => {
    const sm = STATUS_META[c.status] || { label: c.status, cls: "" };
    const risk = c.risk_score != null ? c.risk_score.toFixed(2) : "-";
    const tier = c.risk_score != null ? riskTier(c.risk_score) : "";
    const conf = c.agent_confidence != null ? Math.round(c.agent_confidence * 100) + "%" : "";
    const decision = c.agent_decision ? `${c.agent_decision} ${conf}` : "-";
    const act = c.status === "flagged"
      ? `<button class="btn btn-ghost btn-row-inv" data-cid="${esc(c.case_id)}">Investigate →</button>` : "";
    return `<tr class="h-row" data-cid="${esc(c.case_id)}" title="Click for full case detail">
      <td><span class="status-chip ${sm.cls}">${sm.label}</span></td>
      <td>${esc(c.customer_name)}</td>
      <td><span class="risk-num ${tier}">${risk}</span></td>
      <td>${esc(typoLabel(c.top_typology))}</td>
      <td class="hist-dec">${esc(decision)}</td>
      <td class="hist-date">${esc(c.updated_at.slice(0, 16).replace("T", " "))}</td>
      <td>${act}</td>
    </tr>`;
  }).join("");
  $("#historyBody").innerHTML = `
    <table class="queue hist-table">
      <thead><tr><th>Status</th><th>Customer</th><th>Risk</th><th>Typology</th><th>Agent decision</th><th>Updated</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  $("#historyBody").querySelectorAll(".btn-row-inv").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); investigateFromHistory(b.dataset.cid); }));
  $("#historyBody").querySelectorAll(".h-row").forEach((row) =>
    row.addEventListener("click", () => openCaseDrawer(row.dataset.cid)));
}

// ---- Case drawer: full detail for any persisted case (Phase 12) ----

function closeDrawer() {
  $("#caseDrawer").classList.remove("open");
  $("#drawerBackdrop").classList.remove("show");
  setTimeout(() => {
    $("#caseDrawer").classList.add("hidden");
    $("#drawerBackdrop").classList.add("hidden");
  }, 250);
}

async function openCaseDrawer(caseId) {
  const drawer = $("#caseDrawer");
  const backdrop = $("#drawerBackdrop");
  drawer.classList.remove("hidden");
  backdrop.classList.remove("hidden");
  requestAnimationFrame(() => { drawer.classList.add("open"); backdrop.classList.add("show"); });
  drawer.innerHTML = `<div class="drawer-body"><p class="muted" style="padding:30px">Loading case…</p></div>`;

  try {
    const detail = await (await fetch(`/cases/${encodeURIComponent(caseId)}`)).json();
    // Fresh sub-second monitor pass for the explainability visuals (no LLM).
    const det = await (await fetch("/detect", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(detail.payload),
    })).json();

    const sm = STATUS_META[detail.status] || { label: detail.status, cls: "" };
    const tier = det.risk_score != null ? riskTier(det.risk_score) : "";
    const reviews = (detail.reviews || []).map((r) => `
      <li><b>${esc(r.reviewer)}</b> ${r.action === "approve" ? "approved the agent decision" : "overrode the agent"}
        → <span class="status-chip ${(STATUS_META[r.final_status] || {}).cls || ""}">${esc((STATUS_META[r.final_status] || { label: r.final_status }).label)}</span>
        <span class="hist-date">${esc(r.created_at.slice(0, 16).replace("T", " "))}</span>
        ${r.rationale ? `<div class="rev-rationale">"${esc(r.rationale)}"</div>` : ""}</li>`).join("");

    drawer.innerHTML = `
      <div class="drawer-body">
        <div class="drawer-head">
          <div>
            <div class="drawer-title">${esc(detail.customer_name)}</div>
            <div class="drawer-sub mono">${esc(detail.case_id)}</div>
          </div>
          <div class="drawer-head-right">
            <span class="status-chip ${sm.cls}">${sm.label}</span>
            <button class="icon-btn" id="drawerClose" aria-label="Close">✕</button>
          </div>
        </div>
        <div class="drawer-risk">
          <span class="risk-num ${tier}" style="font-size:26px">${det.risk_score.toFixed(2)}</span>
          <span class="muted">monitor risk score · ${esc(det.recommended_action)}</span>
        </div>
        ${renderWaterfall(det.score_explanation)}
        <div class="txg-slot">${renderTxnGraph(detail.payload, det.graph_analysis)}</div>
        ${detail.report ? `<div class="drawer-section"><div class="explain-title">Agent report (${esc(detail.agent_decision || "")}${detail.agent_confidence != null ? ", " + Math.round(detail.agent_confidence * 100) + "%" : ""})</div><div class="report-doc drawer-report">${renderReportMarkdown(detail.report)}</div></div>` : ""}
        ${reviews ? `<div class="drawer-section"><div class="explain-title">Review audit trail</div><ul class="rev-list">${reviews}</ul></div>` : ""}
      </div>`;
    $("#drawerClose").addEventListener("click", closeDrawer);
  } catch (e) {
    drawer.innerHTML = `<div class="drawer-body"><p style="color:var(--danger);padding:30px">Could not load case: ${esc(e.message)}</p></div>`;
  }
}

async function investigateFromHistory(caseId) {
  try {
    const res = await fetch(`/cases/${encodeURIComponent(caseId)}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const detail = await res.json();
    runInvestigation(detail.payload);
  } catch (e) {
    showToast("Could not load case: " + e.message, true);
  }
}

function wireBatch() {
  const dz = $("#dropZone");
  $("#browseCsv").addEventListener("click", () => $("#csvInput").click());
  $("#csvInput").addEventListener("change", (e) => handleCsvFile(e.target.files[0]));
  dz.addEventListener("click", (e) => { if (e.target.id !== "browseCsv") $("#csvInput").click(); });
  ["dragenter", "dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => handleCsvFile(e.dataTransfer.files[0]));
  $("#runBatchBtn").addEventListener("click", runBatch);
}

// ---- Init ----
initTheme();
wireBatch();
loadStats();
$("#drawerBackdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("#caseDrawer").classList.contains("open")) closeDrawer();
});
$("#refreshHistory").addEventListener("click", loadHistory);
$("#histFilters").querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => {
    $("#histFilters").querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
    c.classList.add("active");
    histFilter = c.dataset.status;
    loadHistory();
  })
);
$("#loadSample").addEventListener("click", loadSample);

document.querySelectorAll("#caseTabs .tab").forEach((t) =>
  t.addEventListener("click", () => setMode(t.dataset.mode))
);
$("#addTxn").addEventListener("click", () => addTxnRow());

$("#investigateBtn").addEventListener("click", () => {
  if (mode === "custom") {
    const c = buildCustomCase();
    if (c) runInvestigation(c);
  } else if (currentCase) {
    runInvestigation(currentCase);
  }
});

seedCustomForm();
loadSample();
