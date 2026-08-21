"""
models.py
=========
Typed data structures shared by every module in the AFH acquisition pipeline.

Design notes
------------
* Every field that the pipeline could not verify is Optional and defaults to
  None -- NOT to a guessed value. Downstream code must branch on None rather
  than silently underwriting a fabricated number.
* `provenance` fields record WHERE a value came from (regex parse, Claude
  extraction, manual override). This matters because listing-alert emails are
  low-fidelity sources and you should never sign an LOI on an unverified figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ListingSource(str, Enum):
    """Which alert provider the listing came from."""
    ZILLOW = "zillow"
    REDFIN = "redfin"
    REALTOR = "realtor"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class Provenance(str, Enum):
    """How confident we are in a parsed field."""
    REGEX = "regex_parse"          # deterministic pattern match on email body
    LLM = "llm_extraction"         # Claude read the email text
    MANUAL = "manual_entry"        # human typed it in
    DERIVED = "derived"            # computed from other fields
    MISSING = "missing"


class ScreenOutcome(str, Enum):
    PASS = "pass"
    FAIL_COUNTY = "fail_out_of_county"
    FAIL_BEDROOMS = "fail_bedroom_count"
    FAIL_MOTIVATION = "fail_no_seller_motivation"
    FAIL_PRICE = "fail_price_out_of_band"
    FAIL_INCOMPLETE = "fail_insufficient_data"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

@dataclass
class ListingAgent:
    """Contact details for the listing agent.

    IMPORTANT: Zillow / Redfin / Realtor.com saved-search alert emails almost
    never contain the agent's direct email address. Expect `email` to be None
    for most auto-ingested listings and plan on an enrichment step.
    """
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    brokerage: Optional[str] = None
    source: Provenance = Provenance.MISSING

    @property
    def is_contactable(self) -> bool:
        return bool(self.email and "@" in self.email)


@dataclass
class Listing:
    """One property under consideration."""

    # --- identity ---
    listing_id: str
    address: str
    city: str
    state: str = "OR"
    zip_code: Optional[str] = None
    county: Optional[str] = None

    # --- core facts ---
    list_price: Optional[int] = None
    bedrooms: Optional[float] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    stories: Optional[int] = None

    # --- motivation signals ---
    days_on_market: Optional[int] = None
    price_reduction_count: int = 0
    original_price: Optional[int] = None
    motivation_keywords_found: list[str] = field(default_factory=list)

    # --- narrative ---
    description: str = ""
    listing_url: Optional[str] = None

    # --- provenance / plumbing ---
    agent: ListingAgent = field(default_factory=ListingAgent)
    source: ListingSource = ListingSource.UNKNOWN
    source_message_id: Optional[str] = None
    ingested_at: datetime = field(default_factory=datetime.now)
    field_provenance: dict[str, str] = field(default_factory=dict)
    raw_text: str = ""

    # --- convenience ---
    @property
    def price_drop_amount(self) -> Optional[int]:
        if self.original_price and self.list_price:
            delta = self.original_price - self.list_price
            return delta if delta > 0 else 0
        return None

    @property
    def price_per_sqft(self) -> Optional[float]:
        if self.list_price and self.square_feet:
            return round(self.list_price / self.square_feet, 2)
        return None

    @property
    def slug(self) -> str:
        """Filesystem-safe identifier used for PDF filenames."""
        base = f"{self.address}_{self.city}".lower()
        return "".join(c if c.isalnum() else "_" for c in base).strip("_")[:80]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ingested_at"] = self.ingested_at.isoformat()
        d["source"] = self.source.value
        d["agent"]["source"] = self.agent.source.value
        return d


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

@dataclass
class ScreenResult:
    """Result of the cheap deterministic filter that runs BEFORE Claude."""
    outcome: ScreenOutcome
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome is ScreenOutcome.PASS


# ---------------------------------------------------------------------------
# Claude assessment
# ---------------------------------------------------------------------------

@dataclass
class AFHAssessment:
    """Structured output from afh_evaluator.py."""
    afh_feasibility_score: int
    pros: list[str]
    red_flags: list[str]
    master_bedroom_shared_potential: bool
    master_bedroom_reasoning: str
    ground_floor_bedroom_estimate: Optional[int]
    provider_room_viable: bool
    accessibility_notes: list[str]
    zoning_hoa_risk_notes: list[str]
    estimated_market_rent: Optional[int]
    suggested_phase1_holding_rent: Optional[int]
    suggested_phase2_full_rent: Optional[int]
    rent_basis: str
    unknowns: list[str] = field(default_factory=list)
    model_used: str = ""
    assessed_at: datetime = field(default_factory=datetime.now)

    def go_no_go(self, threshold: int) -> bool:
        return self.afh_feasibility_score >= threshold

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["assessed_at"] = self.assessed_at.isoformat()
        return d


# ---------------------------------------------------------------------------
# Underwriting
# ---------------------------------------------------------------------------

@dataclass
class RevenueLine:
    label: str
    count: int
    monthly_rate: float
    rate_source: str          # e.g. "APD rate schedule eff. 2026-01-01"
    verified: bool

    @property
    def monthly_total(self) -> float:
        return self.count * self.monthly_rate


@dataclass
class ExpenseLine:
    label: str
    monthly_amount: float
    basis: str
    is_fixed: bool = True


@dataclass
class DealEconomics:
    """Output of deal_calculator.py."""
    resident_capacity: int
    revenue_lines: list[RevenueLine]
    expense_lines: list[ExpenseLine]
    proposed_phase1_rent: float
    proposed_phase2_rent: float
    phase1_months: int

    unverified_inputs: list[str] = field(default_factory=list)

    # --- computed ---
    @property
    def gross_monthly_revenue(self) -> float:
        return sum(r.monthly_total for r in self.revenue_lines)

    @property
    def total_monthly_expenses(self) -> float:
        return sum(e.monthly_amount for e in self.expense_lines)

    @property
    def noi_monthly(self) -> float:
        return self.gross_monthly_revenue - self.total_monthly_expenses

    @property
    def noi_annual(self) -> float:
        return self.noi_monthly * 12

    @property
    def revenue_per_occupied_bed(self) -> float:
        occupied = sum(r.count for r in self.revenue_lines)
        return self.gross_monthly_revenue / occupied if occupied else 0.0

    @property
    def breakeven_residents(self) -> Optional[float]:
        """How many residents are needed to cover total monthly expenses."""
        per_bed = self.revenue_per_occupied_bed
        if per_bed <= 0:
            return None
        return round(self.total_monthly_expenses / per_bed, 2)

    @property
    def phase1_monthly_burn(self) -> float:
        """Cash burn per month during licensing, when revenue is zero."""
        non_rent = sum(
            e.monthly_amount for e in self.expense_lines
            if not e.label.lower().startswith("master lease")
        )
        # Staffing is not fully loaded pre-licensure; caller may override.
        return self.proposed_phase1_rent + non_rent

    @property
    def rent_coverage_ratio(self) -> Optional[float]:
        """Gross revenue / Phase 2 rent. Lenders and landlords look at this."""
        if self.proposed_phase2_rent <= 0:
            return None
        return round(self.gross_monthly_revenue / self.proposed_phase2_rent, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resident_capacity": self.resident_capacity,
            "gross_monthly_revenue": round(self.gross_monthly_revenue, 2),
            "total_monthly_expenses": round(self.total_monthly_expenses, 2),
            "noi_monthly": round(self.noi_monthly, 2),
            "noi_annual": round(self.noi_annual, 2),
            "breakeven_residents": self.breakeven_residents,
            "rent_coverage_ratio": self.rent_coverage_ratio,
            "proposed_phase1_rent": self.proposed_phase1_rent,
            "proposed_phase2_rent": self.proposed_phase2_rent,
            "unverified_inputs": self.unverified_inputs,
            "revenue_lines": [asdict(r) for r in self.revenue_lines],
            "expense_lines": [asdict(e) for e in self.expense_lines],
        }


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------

@dataclass
class Deal:
    """Everything the pipeline knows about one property, end to end."""
    listing: Listing
    screen: Optional[ScreenResult] = None
    assessment: Optional[AFHAssessment] = None
    economics: Optional[DealEconomics] = None
    loi_path: Optional[str] = None
    draft_id: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    created_on: date = field(default_factory=date.today)

    @property
    def advanced(self) -> bool:
        return bool(self.loi_path)
