# data/ — Synthetic AML Dataset

## Why synthetic data?

**Privacy:** Real transaction data from Indian banks is non-public and subject to
PMLA/RBI data localisation rules. Synthetic data lets us build, evaluate, and
share the project without touching real customer records.

**Reproducibility:** Fixed seed (42) means every run produces the exact same 200
cases. Anyone can clone the repo and reproduce the eval numbers identically.

**Eval validity:** A hand-crafted dataset with ground-truth labels lets us measure
precision / recall / F1 / FPR precisely. A real dataset would require expensive
human labelling and could not be shared publicly.

---

## Files

| File | Cases | Purpose |
|---|---|---|
| `schema.py` | — | Pydantic models (source of truth for all types) |
| `generator.py` | 200 | Deterministic generator; run to recreate the JSONs |
| `cases_train.json` | 160 | Training + prompt-tuning split |
| `cases_holdout.json` | 40 | **LOCKED** — only used in final evaluation |

---

## Schema

### `CustomerProfile`
| Field | Type | Notes |
|---|---|---|
| `id` | str | e.g. `cust_str_000` |
| `name` | str | Business or individual name |
| `business_type` | enum | retail / sme / individual / real_estate / hospitality / logistics / textile / jewelry |
| `account_open_date` | datetime | ISO 8601 |
| `stated_monthly_turnover_inr` | float | ₹ per month, self-declared |
| `prior_flags` | int | 0 = no prior flags, 1–2 = previously flagged |

### `TransactionRecord`
| Field | Type | Notes |
|---|---|---|
| `id` | str | e.g. `txn_a1b2c3d4` |
| `customer_id` | str | Foreign key to CustomerProfile.id |
| `amount_inr` | float | Rupees |
| `timestamp` | datetime | ISO 8601 |
| `counterparty_name` | str | Individual or business name |
| `counterparty_account` | str | 14-digit account number (synthetic) |
| `direction` | enum | credit / debit |
| `channel` | enum | UPI / NEFT / RTGS / cash |

### `Case`
| Field | Type | Notes |
|---|---|---|
| `case_id` | str | e.g. `case_str_000` |
| `customer` | CustomerProfile | Embedded object |
| `transactions` | list[TransactionRecord] | Sorted by timestamp |
| `ground_truth_label` | enum | **suspicious** / **clean** |
| `typology` | enum or null | structuring / sanctions_hit / rapid_passthrough / null (for clean) |
| `notes` | str | Human-readable explanation of why the label was assigned |

---

## Typologies

### structuring (50 cases)
**What it is:** Breaking a large transaction into multiple smaller ones to stay
below the Currency Transaction Report (CTR) threshold of ₹10 lakh.

**How generated:** ≥3 cash deposits of ₹8.5L–₹9.9L each, from different city
branches, within a 30-day window. Total cash credits > ₹10L for the month.

**PMLA reference:** Section 12, PMLA 2002 (reporting obligation for CTR);
FATF Recommendation 29 (structuring typology).

---

### sanctions_hit (50 cases)
**What it is:** A transaction where the counterparty name matches an entity
on a sanctions or PEP (Politically Exposed Person) list.

**How generated:** 1–3 transactions with a counterparty drawn from a hardcoded
list of 20 fake names (stand-in for an OpenSanctions hit). Background transactions
are normal.

**PMLA reference:** Section 12A, PMLA 2002; RBI KYC Master Directions 2016,
Chapter IV (enhanced due diligence for PEPs and high-risk entities).

---

### rapid_passthrough (50 cases)
**What it is:** A large inbound credit is rapidly distributed to multiple new
payees — a classic money-laundering layering technique.

**How generated:** One NEFT/RTGS credit of ₹15L–₹50L, followed within 72 hours
by ≥5 debits to new (previously unseen) payees, totalling ≥80% of the credit.

**PMLA reference:** Section 3, PMLA 2002 (layering as a constituent of the
money laundering offence); FATF South Asia Typology Report 2021.

---

### clean (50 cases)
**What it is:** Realistic SMB or retail activity with no suspicious indicators.

**How generated:** 10–25 transactions over 60 days. Amounts consistent with
stated monthly turnover. Payees drawn from a fixed set of recurring businesses
(utility bills, logistics, suppliers). No cash-heavy patterns, no sanctioned names,
no rapid fan-out.

---

## Split design

| Split | Total | Per typology | Suspicious | Clean |
|---|---|---|---|---|
| Train | 160 | 40 | 120 (75%) | 40 (25%) |
| Holdout | 40 | 10 | 30 (75%) | 10 (25%) |

**Imbalance note:** The dataset is 75% suspicious / 25% clean — not 50/50.
This reflects the fact that we have 3 suspicious typologies and 1 clean
typology (50 cases each). The 3:1 ratio means FPR on clean cases is the
critical metric to watch. A model that labels everything suspicious gets
75% accuracy but is useless — eval must report FPR explicitly.

**Holdout is locked:** Do not use `cases_holdout.json` during prompt engineering,
tool tuning, or RAG retrieval development. It is opened exactly once, for the
final evaluation reported in the README.

---

## Regenerating the dataset

```bash
python data/generator.py
```

Output is deterministic (seed=42). The same JSON files are produced on every run.
