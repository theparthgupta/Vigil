"""
Synthetic AML case generator for Vigil.

Produces 200 deterministic cases (seed=42) across 4 typologies:
  - structuring (50): cash deposits just below ₹10L CTR threshold
  - sanctions_hit (50): counterparty on hardcoded fake sanctions list
  - rapid_passthrough (50): large credit → many debits to new payees within 72h
  - clean (50): realistic SMB/retail activity

Output:
  data/cases_train.json   — 160 cases (40 per typology)
  data/cases_holdout.json — 40 cases  (10 per typology, NEVER used for tuning)
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Allow running as: python data/generator.py from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.schema import (
    BusinessType,
    Case,
    Channel,
    CustomerProfile,
    Direction,
    Label,
    TransactionRecord,
    Typology,
)

SEED = 42
_rng = random.Random(SEED)

# ── Hardcoded fake sanctions list (20 names, flagged "on OpenSanctions" for testing) ──
SANCTIONED_NAMES: list[str] = [
    "Dawood Merchant",
    "Khalid Al-Rashidi",
    "Viktor Petrov",
    "Mehmet Yildirim Ozcan",
    "Farooq Ibrahim Siddiqui",
    "Sergei Volkov",
    "Hassan Al-Farouqi",
    "Chen Wei Guang",
    "Mohammad Aziz Karimov",
    "Yusuf Bello Adeyemi",
    "Reza Tehrani Moghaddam",
    "Abdul Majid Haqqani",
    "Nikolai Gromov",
    "Tariq Mahmood Chaudhry",
    "Ali Hassan Mousa",
    "Dmitri Sorokin",
    "Bashir Ahmad Zahed",
    "Liang Xiaoming",
    "Omar Sheikh Qureshi",
    "Pavlo Kovalenko",
]

_FIRST_NAMES = [
    "Rajesh",
    "Suresh",
    "Mukesh",
    "Ramesh",
    "Mahesh",
    "Dinesh",
    "Priya",
    "Sunita",
    "Anita",
    "Kavita",
    "Geeta",
    "Meena",
    "Amit",
    "Sumit",
    "Rohit",
    "Mohit",
    "Ankit",
    "Vikas",
    "Pooja",
    "Neha",
    "Asha",
    "Rekha",
    "Sita",
    "Radha",
    "Harish",
    "Girish",
    "Manish",
    "Naresh",
    "Paresh",
    "Yogesh",
    "Arun",
    "Varun",
    "Tarun",
    "Kiran",
    "Milan",
    "Nitin",
    "Deepa",
    "Seema",
    "Reema",
    "Nisha",
    "Usha",
    "Sudha",
    "Ajay",
    "Vijay",
    "Sanjay",
    "Manoj",
    "Saroj",
    "Pankaj",
]

_LAST_NAMES = [
    "Sharma",
    "Verma",
    "Gupta",
    "Agarwal",
    "Singh",
    "Kumar",
    "Patel",
    "Shah",
    "Mehta",
    "Joshi",
    "Mishra",
    "Tiwari",
    "Pandey",
    "Shukla",
    "Dubey",
    "Yadav",
    "Chauhan",
    "Thakur",
    "Reddy",
    "Rao",
    "Nair",
    "Pillai",
    "Menon",
    "Iyer",
    "Banerjee",
    "Chatterjee",
    "Mukherjee",
    "Bose",
    "Das",
    "Sen",
    "Desai",
    "Jain",
    "Choudhury",
    "Saxena",
    "Srivastava",
    "Kapoor",
]

# 20 distinct city-branches for structuring cases (each deposit = different branch)
_CITY_BRANCHES = [
    "Mumbai-Andheri",
    "Delhi-Connaught Place",
    "Bangalore-Koramangala",
    "Chennai-T Nagar",
    "Hyderabad-Banjara Hills",
    "Pune-Kothrud",
    "Ahmedabad-CG Road",
    "Kolkata-Park Street",
    "Jaipur-MI Road",
    "Lucknow-Hazratganj",
    "Chandigarh-Sector 17",
    "Surat-Ring Road",
    "Nagpur-Dharampeth",
    "Indore-Vijay Nagar",
    "Bhopal-MP Nagar",
    "Kochi-MG Road",
    "Coimbatore-RS Puram",
    "Visakhapatnam-Dwaraka",
    "Patna-Fraser Road",
    "Ranchi-Main Road",
]

# Recurring payees used in clean cases (utility bills, salaries, suppliers, etc.)
_REGULAR_PAYEES = [
    "City Power Supply Co",
    "Municipal Water Board",
    "Office Depot India",
    "Gati Courier Services",
    "Reliance Retail Ltd",
    "D-Mart Wholesale",
    "BSNL Telecom",
    "LIC Premium Portal",
    "Employee Salary Pool",
    "Raw Materials Supplier",
    "Tata Communications",
    "GST Payment Portal",
    "Rent – Commercial Premises",
    "Security Services Pvt Ltd",
    "Housekeeping Crew",
    "Professional Tax Dept",
    "EPF Contribution",
    "Cloud Services (AWS)",
    "Newspaper & Stationery",
    "Internet Provider",
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _rand_name() -> str:
    return f"{_rng.choice(_FIRST_NAMES)} {_rng.choice(_LAST_NAMES)}"


def _rand_account() -> str:
    return "".join(str(_rng.randint(0, 9)) for _ in range(14))


def _rand_business_name(btype: BusinessType) -> str:
    suffixes = {
        BusinessType.retail: ["Traders", "General Store", "Mart", "Emporium"],
        BusinessType.sme: ["Enterprises", "Industries", "Works", "Pvt Ltd"],
        BusinessType.individual: [""],
        BusinessType.real_estate: ["Properties", "Realtors", "Builders & Developers"],
        BusinessType.hospitality: ["Hotels", "Resorts", "Caterers"],
        BusinessType.logistics: ["Logistics", "Cargo Services", "Transport"],
        BusinessType.textile: ["Textiles", "Fabrics", "Garments"],
        BusinessType.jewelry: ["Jewellers", "Gems & Ornaments", "Gold House"],
    }
    last = _rng.choice(_LAST_NAMES)
    suffix = _rng.choice(suffixes[btype])
    return f"{last} {suffix}".strip() if suffix else _rand_name()


def _base_date() -> datetime:
    # Spread cases across 2024 so timestamps are realistic
    return datetime(2024, 1, 1) + timedelta(days=_rng.randint(0, 300))


def _make_customer(cid: str, btype: Optional[BusinessType] = None) -> CustomerProfile:
    btype = btype or _rng.choice(list(BusinessType))
    turnover = float(_rng.randint(5, 200) * 100_000)  # ₹5L – ₹2Cr
    return CustomerProfile(
        id=cid,
        name=_rand_business_name(btype),
        business_type=btype,
        account_open_date=datetime(2018, 1, 1) + timedelta(days=_rng.randint(0, 2000)),
        stated_monthly_turnover_inr=turnover,
        prior_flags=_rng.choices([0, 1, 2], weights=[80, 15, 5])[0],
    )


def _make_txn(
    cid: str,
    amount_inr: float,
    timestamp: datetime,
    counterparty_name: str,
    direction: Direction,
    channel: Channel,
    counterparty_account: Optional[str] = None,
) -> TransactionRecord:
    return TransactionRecord(
        id=f"txn_{_rng.getrandbits(32):08x}",
        customer_id=cid,
        amount_inr=round(amount_inr, 2),
        timestamp=timestamp,
        counterparty_name=counterparty_name,
        counterparty_account=counterparty_account or _rand_account(),
        direction=direction,
        channel=channel,
    )


def _split_total(total: float, n: int) -> list[float]:
    """Split total into n random positive parts summing to total."""
    cuts = sorted(_rng.random() for _ in range(n - 1))
    cuts = [0.0] + cuts + [1.0]
    return [total * (cuts[i + 1] - cuts[i]) for i in range(n)]


def _unique_payee(used: set[str]) -> str:
    for _ in range(100):
        name = _rand_name()
        if name not in used:
            used.add(name)
            return name
    # Fallback: append index to guarantee uniqueness
    name = f"{_rand_name()} {len(used)}"
    used.add(name)
    return name


# ── Typology generators ───────────────────────────────────────────────────────


def _gen_structuring(idx: int) -> Case:
    """
    ≥3 cash deposits between ₹8.5L–₹9.9L, each from a different branch,
    within 30 days. Total cash credits > ₹10L for the month.
    PMLA relevance: CTR threshold ₹10 lakh (Section 12, PMLA 2002).
    """
    cid = f"cust_str_{idx:03d}"
    customer = _make_customer(
        cid, _rng.choice([BusinessType.retail, BusinessType.sme, BusinessType.jewelry])
    )
    base = _base_date()
    n_deposits = _rng.randint(3, 6)
    branches = _rng.sample(_CITY_BRANCHES, n_deposits)

    txns: list[TransactionRecord] = []
    for branch in branches:
        amount = float(_rng.randint(850_000, 990_000))
        day_off = _rng.randint(0, 29)
        txns.append(
            _make_txn(
                cid,
                amount_inr=amount,
                timestamp=base + timedelta(days=day_off, hours=_rng.randint(9, 17)),
                counterparty_name=f"Cash Deposit – {branch} Branch",
                direction=Direction.credit,
                channel=Channel.cash,
            )
        )

    # Background noise: normal UPI/NEFT activity
    for _ in range(_rng.randint(3, 8)):
        txns.append(
            _make_txn(
                cid,
                amount_inr=float(_rng.randint(10_000, 200_000)),
                timestamp=base + timedelta(days=_rng.randint(0, 60), hours=_rng.randint(9, 18)),
                counterparty_name=_rand_name(),
                direction=_rng.choice([Direction.credit, Direction.debit]),
                channel=_rng.choice([Channel.upi, Channel.neft]),
            )
        )

    txns.sort(key=lambda t: t.timestamp)
    cash_total = sum(
        t.amount_inr for t in txns if t.direction == Direction.credit and t.channel == Channel.cash
    )
    return Case(
        case_id=f"case_str_{idx:03d}",
        customer=customer,
        transactions=txns,
        ground_truth_label=Label.suspicious,
        typology=Typology.structuring,
        notes=(
            f"{n_deposits} cash deposits totalling ₹{cash_total / 1e5:.1f}L "
            f"across {n_deposits} branches within 30 days. "
            f"Each deposit below ₹10L CTR threshold (PMLA s.12)."
        ),
    )


def _gen_sanctions_hit(idx: int) -> Case:
    """
    ≥1 transaction with a counterparty whose name appears on the
    hardcoded fake sanctions list (stand-in for OpenSanctions hits).
    PMLA relevance: Section 12A, PMLA 2002; RBI KYC Master Directions 2016.
    """
    cid = f"cust_san_{idx:03d}"
    customer = _make_customer(cid)
    base = _base_date()
    n_sanctioned = _rng.randint(1, 3)
    sanctioned = _rng.sample(SANCTIONED_NAMES, n_sanctioned)

    txns: list[TransactionRecord] = []
    for name in sanctioned:
        txns.append(
            _make_txn(
                cid,
                amount_inr=float(_rng.randint(50_000, 2_000_000)),
                timestamp=base + timedelta(days=_rng.randint(0, 30), hours=_rng.randint(9, 18)),
                counterparty_name=name,
                direction=_rng.choice([Direction.credit, Direction.debit]),
                channel=_rng.choice([Channel.neft, Channel.rtgs, Channel.upi]),
            )
        )

    for _ in range(_rng.randint(5, 15)):
        txns.append(
            _make_txn(
                cid,
                amount_inr=float(_rng.randint(5_000, 500_000)),
                timestamp=base + timedelta(days=_rng.randint(0, 60), hours=_rng.randint(9, 18)),
                counterparty_name=_rand_name(),
                direction=_rng.choice([Direction.credit, Direction.debit]),
                channel=_rng.choice([Channel.upi, Channel.neft, Channel.rtgs]),
            )
        )

    txns.sort(key=lambda t: t.timestamp)
    return Case(
        case_id=f"case_san_{idx:03d}",
        customer=customer,
        transactions=txns,
        ground_truth_label=Label.suspicious,
        typology=Typology.sanctions_hit,
        notes=f"Transaction(s) with sanctioned counterpart(ies): {', '.join(sanctioned)}.",
    )


def _gen_rapid_passthrough(idx: int) -> Case:
    """
    Large credit (₹15L–₹50L) followed within 72 hours by ≥5 debits
    to new payees totalling ≥80% of the credit. Classic layering pattern.
    PMLA relevance: Section 3 (money laundering offence), FATF Rec. 20.
    """
    cid = f"cust_rpt_{idx:03d}"
    customer = _make_customer(
        cid, _rng.choice([BusinessType.sme, BusinessType.logistics, BusinessType.real_estate])
    )
    base = _base_date()
    credit_amount = float(_rng.randint(1_500_000, 5_000_000))
    credit_ts = base + timedelta(hours=_rng.randint(9, 12))

    txns: list[TransactionRecord] = [
        _make_txn(
            cid,
            amount_inr=credit_amount,
            timestamp=credit_ts,
            counterparty_name=f"{_rng.choice(_LAST_NAMES)} {_rng.choice(['Ltd', 'Corp', 'Pvt Ltd'])}",
            direction=Direction.credit,
            channel=_rng.choice([Channel.rtgs, Channel.neft]),
        )
    ]

    n_debits = _rng.randint(5, 9)
    total_debit = credit_amount * _rng.uniform(0.80, 0.95)
    debit_amounts = _split_total(total_debit, n_debits)
    used_payees: set[str] = set()

    for amt in debit_amounts:
        payee = _unique_payee(used_payees)
        txns.append(
            _make_txn(
                cid,
                amount_inr=round(amt, 2),
                timestamp=credit_ts + timedelta(hours=_rng.uniform(0.5, 71.5)),
                counterparty_name=payee,
                direction=Direction.debit,
                channel=_rng.choice([Channel.upi, Channel.neft, Channel.rtgs]),
            )
        )

    txns.sort(key=lambda t: t.timestamp)
    return Case(
        case_id=f"case_rpt_{idx:03d}",
        customer=customer,
        transactions=txns,
        ground_truth_label=Label.suspicious,
        typology=Typology.rapid_passthrough,
        notes=(
            f"Credit of ₹{credit_amount / 1e5:.1f}L followed by {n_debits} debits "
            f"to new payees within 72h, totalling ₹{total_debit / 1e5:.1f}L "
            f"({total_debit / credit_amount * 100:.0f}% pass-through)."
        ),
    )


def _gen_clean(idx: int) -> Case:
    """
    Realistic SMB/retail activity: varied amounts, regular recurring payees,
    consistent with stated business type and monthly turnover.
    """
    cid = f"cust_cln_{idx:03d}"
    btype = _rng.choice(
        [
            BusinessType.retail,
            BusinessType.sme,
            BusinessType.individual,
            BusinessType.hospitality,
        ]
    )
    customer = _make_customer(cid, btype)
    base = _base_date()
    monthly = customer.stated_monthly_turnover_inr
    n_txns = _rng.randint(10, 25)
    regular_payees = _rng.sample(_REGULAR_PAYEES, _rng.randint(4, 8))

    txns: list[TransactionRecord] = []
    for _ in range(n_txns):
        is_income = _rng.random() < 0.35
        lo = max(int(monthly * 0.01), 1_000)
        hi = max(int(monthly * 0.15), lo + 1_000)
        amount = float(_rng.randint(lo, hi))
        counterparty = (
            _rng.choice([_rand_name(), f"{_rng.choice(_LAST_NAMES)} Pvt Ltd"])
            if is_income
            else _rng.choice(regular_payees)
        )
        txns.append(
            _make_txn(
                cid,
                amount_inr=amount,
                timestamp=base + timedelta(days=_rng.randint(0, 60), hours=_rng.randint(9, 18)),
                counterparty_name=counterparty,
                direction=Direction.credit if is_income else Direction.debit,
                channel=_rng.choice([Channel.upi, Channel.upi, Channel.neft, Channel.rtgs]),
            )
        )

    txns.sort(key=lambda t: t.timestamp)
    return Case(
        case_id=f"case_cln_{idx:03d}",
        customer=customer,
        transactions=txns,
        ground_truth_label=Label.clean,
        typology=None,
        notes=(
            f"Normal {btype.value} activity. {n_txns} txns over ~60 days. "
            f"Consistent with stated turnover ₹{monthly / 1e5:.1f}L/month."
        ),
    )


# ── Main generation + split ───────────────────────────────────────────────────


def generate_all() -> list[Case]:
    cases: list[Case] = []
    cases += [_gen_structuring(i) for i in range(50)]
    cases += [_gen_sanctions_hit(i) for i in range(50)]
    cases += [_gen_rapid_passthrough(i) for i in range(50)]
    cases += [_gen_clean(i) for i in range(50)]
    return cases


def split_cases(cases: list[Case]) -> tuple[list[Case], list[Case]]:
    """
    80/20 split stratified by typology.
    Each typology: 40 train, 10 holdout → 160 train, 40 holdout total.
    Ordering within typology is deterministic (generator order, seed=42).
    """
    typology_groups: dict[str, list[Case]] = {}
    for case in cases:
        key = case.typology.value if case.typology else "clean"
        typology_groups.setdefault(key, []).append(case)

    train, holdout = [], []
    for group in typology_groups.values():
        train.extend(group[:40])
        holdout.extend(group[40:])
    return train, holdout


def _serialize(cases: list[Case]) -> str:
    return json.dumps(
        [json.loads(c.model_dump_json()) for c in cases],
        indent=2,
        ensure_ascii=False,
    )


def print_summary(train: list[Case], holdout: list[Case]) -> None:
    def counts(cases: list[Case]) -> dict:
        by_typology: dict[str, int] = {}
        for c in cases:
            key = c.typology.value if c.typology else "clean"
            by_typology[key] = by_typology.get(key, 0) + 1
        susp = sum(1 for c in cases if c.ground_truth_label == Label.suspicious)
        return {"by_typology": by_typology, "suspicious": susp, "clean": len(cases) - susp}

    tr = counts(train)
    ho = counts(holdout)
    print("\n--- Vigil dataset summary ---")
    print(f"  Train  : {len(train)} cases")
    for k, v in tr["by_typology"].items():
        print(f"    {k:<22} {v}")
    print(f"    suspicious / clean  : {tr['suspicious']} / {tr['clean']}")
    print(f"  Holdout: {len(holdout)} cases  (LOCKED - do not tune on this)")
    for k, v in ho["by_typology"].items():
        print(f"    {k:<22} {v}")
    print(f"    suspicious / clean  : {ho['suspicious']} / {ho['clean']}")
    print("-------------------------------\n")


def eyeball(cases: list[Case], n: int = 10) -> None:
    """Print one representative case per typology for manual inspection."""
    seen: set[str] = set()
    printed = 0
    print("\n--- Eyeball: 1 sample per typology ---")
    for c in cases:
        key = c.typology.value if c.typology else "clean"
        if key not in seen:
            seen.add(key)
            print(f"\n[{key.upper()}] {c.case_id}")
            print(f"  Customer   : {c.customer.name} ({c.customer.business_type.value})")
            print(f"  Label      : {c.ground_truth_label.value}")
            print(f"  Txns       : {len(c.transactions)}")
            print(f"  Notes      : {c.notes}")
            print("  Sample txns:")
            for t in c.transactions[:3]:
                print(
                    f"    {t.timestamp.date()} | {t.direction.value:<6} | "
                    f"₹{t.amount_inr:>12,.0f} | {t.channel.value:<4} | {t.counterparty_name}"
                )
            printed += 1
        if printed >= n:
            break
    print("\n-------------------------------\n")


if __name__ == "__main__":
    # Force UTF-8 on Windows terminals that default to cp1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    out_dir = Path(__file__).parent
    out_dir.mkdir(exist_ok=True)

    print("Generating 200 synthetic AML cases (seed=42)...")
    all_cases = generate_all()

    train, holdout = split_cases(all_cases)

    (out_dir / "cases_train.json").write_text(_serialize(train), encoding="utf-8")
    (out_dir / "cases_holdout.json").write_text(_serialize(holdout), encoding="utf-8")

    print(f"Written: data/cases_train.json   ({len(train)} cases)")
    print(f"Written: data/cases_holdout.json ({len(holdout)} cases)")

    print_summary(train, holdout)
    eyeball(all_cases)
