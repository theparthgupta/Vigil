from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class BusinessType(str, Enum):
    retail = "retail"
    sme = "sme"
    individual = "individual"
    real_estate = "real_estate"
    hospitality = "hospitality"
    logistics = "logistics"
    textile = "textile"
    jewelry = "jewelry"
    restaurant = "restaurant"  # user-facing custom-case option
    other = "other"  # user-facing custom-case option


class Direction(str, Enum):
    credit = "credit"
    debit = "debit"


class Channel(str, Enum):
    upi = "UPI"
    neft = "NEFT"
    rtgs = "RTGS"
    cash = "cash"
    imps = "IMPS"


class Label(str, Enum):
    suspicious = "suspicious"
    clean = "clean"
    custom = "custom"  # user-submitted case: no ground-truth label


class Typology(str, Enum):
    structuring = "structuring"
    sanctions_hit = "sanctions_hit"
    rapid_passthrough = "rapid_passthrough"


class TransactionRecord(BaseModel):
    id: str
    customer_id: str
    amount_inr: float
    timestamp: datetime
    counterparty_name: str
    counterparty_account: str
    direction: Direction
    channel: Channel


class CustomerProfile(BaseModel):
    id: str
    name: str
    business_type: BusinessType
    account_open_date: datetime
    stated_monthly_turnover_inr: float
    prior_flags: int


class Case(BaseModel):
    case_id: str
    customer: CustomerProfile
    transactions: list[TransactionRecord]
    ground_truth_label: Label
    typology: Optional[Typology]
    notes: str
