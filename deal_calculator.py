"""
deal_calculator.py
==================
Builds the operating pro-forma for a 5-resident Oregon adult foster home under
the proposed master lease.

THE ONE THING TO UNDERSTAND ABOUT THIS MODULE
---------------------------------------------
It ships with zero default reimbursement rates and it will refuse to run
without yours. Oregon APD adult foster home service payments are tiered, they
are revised, and room-and-board is accounted for separately from the service
payment. A pro-forma built on a number someone guessed is a liability, not a
tool -- especially one that ends up justifying a rent figure you then commit to
in a signed lease.

So: `MissingAssumptionsError` is a feature. Fill in `.env`, record where each
number came from and the date you pulled it, and re-run.

Where to source your inputs
---------------------------
* Service payment tiers   -> your current APD provider rate schedule / your
                             existing home's remittance advices.
* Room and board          -> the current OSIPM room-and-board standard.
* Private pay             -> your own executed residency agreements.
* Staffing                -> your actual payroll, fully loaded (wages + employer
                             taxes + workers comp + any benefits + relief
                             coverage). Do not use base wage alone.
* Insurance               -> the quotes you gathered for GL + professional.
"""

from __future__ import annotations

import logging
from typing import Optional

import config
from models import AFHAssessment, DealEconomics, ExpenseLine, Listing, RevenueLine

log = logging.getLogger(__name__)


class MissingAssumptionsError(RuntimeError):
    """Raised when required underwriting inputs are absent."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        lines = "\n".join(f"  - {m}" for m in missing)
        super().__init__(
            "Cannot underwrite: required inputs are missing from .env.\n"
            f"{lines}\n\n"
            "These are deliberately not defaulted. Supply your own verified "
            "figures and set ASSUMPTIONS_EFFECTIVE_DATE to the date you "
            "pulled them."
        )


REQUIRED_FIELDS: dict[str, str] = {
    "medicaid_resident_count": "MEDICAID_RESIDENT_COUNT (planned Medicaid census)",
    "medicaid_monthly_rate": "MEDICAID_MONTHLY_RATE (APD service payment per resident/month)",
    "private_pay_resident_count": "PRIVATE_PAY_RESIDENT_COUNT (planned private-pay census)",
    "private_pay_monthly_rate": "PRIVATE_PAY_MONTHLY_RATE (your contracted private rate)",
    "staffing_cost": "STAFFING_MONTHLY_COST (fully loaded 24/7 coverage)",
    "food_supplies_cost": "FOOD_SUPPLIES_MONTHLY_COST",
    "insurance_cost": "INSURANCE_MONTHLY_COST (general + professional liability)",
    "utilities_cost": "UTILITIES_MONTHLY_COST",
}


def check_assumptions(
    assumptions: config.UnderwritingAssumptions = config.ASSUMPTIONS,
) -> list[str]:
    """Return human-readable descriptions of missing required inputs."""
    missing: list[str] = []
    for attr, label in REQUIRED_FIELDS.items():
        if getattr(assumptions, attr, None) in (None, ""):
            missing.append(label)
    return missing


# ---------------------------------------------------------------------------
# Rent derivation
# ---------------------------------------------------------------------------

def derive_rents(
    assessment: Optional[AFHAssessment],
    *,
    lease: config.LeaseTerms = config.LEASE,
) -> tuple[Optional[float], Optional[float], list[str]]:
    """Return (phase1_rent, phase2_rent, notes).

    Prefers Claude's suggestions; falls back to deriving them from the market
    rent estimate; returns (None, None) if there is no defensible basis.
    """
    notes: list[str] = []
    if assessment is None:
        return None, None, ["No assessment available -- rents undetermined."]

    p1 = assessment.suggested_phase1_holding_rent
    p2 = assessment.suggested_phase2_full_rent
    market = assessment.estimated_market_rent

    if p1 and p2:
        notes.append(f"Rents taken from the AI assessment. Basis: {assessment.rent_basis}")
        return float(p1), float(p2), notes

    if market:
        mid_pct = (lease.phase1_pct_of_market_low + lease.phase1_pct_of_market_high) / 2
        p1 = round(market * mid_pct / 25) * 25
        p2 = round(market * (1 + lease.phase2_premium_over_market) / 25) * 25
        notes.append(
            f"Rents derived from estimated market rent of ${market:,}: "
            f"Phase 1 at {mid_pct:.0%}, Phase 2 at a "
            f"{lease.phase2_premium_over_market:.0%} premium."
        )
        return float(p1), float(p2), notes

    notes.append(
        "No market rent estimate was available, so no rent figures were "
        "generated. Pull rental comps for this submarket before sending an LOI."
    )
    return None, None, notes


# ---------------------------------------------------------------------------
# Pro-forma construction
# ---------------------------------------------------------------------------

def build_economics(
    listing: Listing,
    assessment: Optional[AFHAssessment] = None,
    *,
    assumptions: config.UnderwritingAssumptions = config.ASSUMPTIONS,
    lease: config.LeaseTerms = config.LEASE,
    phase1_rent: Optional[float] = None,
    phase2_rent: Optional[float] = None,
    strict: bool = True,
) -> DealEconomics:
    """Assemble the monthly operating model.

    `strict=True` raises MissingAssumptionsError when inputs are absent.
    `strict=False` substitutes 0.0 and records the gap in `unverified_inputs`
    so you can still exercise the pipeline end to end with a sample payload.
    """
    missing = check_assumptions(assumptions)
    if missing and strict:
        raise MissingAssumptionsError(missing)

    unverified: list[str] = list(missing)

    if phase1_rent is None or phase2_rent is None:
        d1, d2, notes = derive_rents(assessment, lease=lease)
        phase1_rent = phase1_rent if phase1_rent is not None else d1
        phase2_rent = phase2_rent if phase2_rent is not None else d2
        unverified.extend(n for n in notes if "undetermined" in n or "No market" in n)

    if phase1_rent is None or phase2_rent is None:
        unverified.append("Proposed rent could not be determined -- shown as $0.")
        phase1_rent = phase1_rent or 0.0
        phase2_rent = phase2_rent or 0.0

    def _num(v: Optional[float]) -> float:
        return float(v) if v is not None else 0.0

    # ---- revenue ---------------------------------------------------------
    revenue: list[RevenueLine] = []

    med_n = int(_num(assumptions.medicaid_resident_count))
    if med_n:
        revenue.append(RevenueLine(
            label="APD Medicaid service payment",
            count=med_n,
            monthly_rate=_num(assumptions.medicaid_monthly_rate),
            rate_source=assumptions.medicaid_rate_source or "NOT DOCUMENTED",
            verified=bool(assumptions.medicaid_rate_source),
        ))

    pp_n = int(_num(assumptions.private_pay_resident_count))
    if pp_n:
        revenue.append(RevenueLine(
            label="Private pay",
            count=pp_n,
            monthly_rate=_num(assumptions.private_pay_monthly_rate),
            rate_source=assumptions.private_pay_rate_source or "NOT DOCUMENTED",
            verified=bool(assumptions.private_pay_rate_source),
        ))

    if assumptions.room_and_board_monthly and med_n:
        revenue.append(RevenueLine(
            label="Room and board (Medicaid residents)",
            count=med_n,
            monthly_rate=_num(assumptions.room_and_board_monthly),
            rate_source=assumptions.room_and_board_source or "NOT DOCUMENTED",
            verified=bool(assumptions.room_and_board_source),
        ))

    census = med_n + pp_n
    if census > assumptions.resident_capacity:
        unverified.append(
            f"Planned census of {census} exceeds the stated capacity of "
            f"{assumptions.resident_capacity}. Oregon AFHs are licensed for a "
            "maximum of five residents."
        )

    for line in revenue:
        if not line.verified:
            unverified.append(
                f"Rate source not documented for '{line.label}' -- set the "
                "matching *_RATE_SOURCE variable with the schedule and date."
            )

    # ---- expenses --------------------------------------------------------
    expenses: list[ExpenseLine] = [
        ExpenseLine("Master lease rent (Phase 2)", float(phase2_rent),
                    "Proposed in the LOI"),
        ExpenseLine("Staffing (24/7 coverage, fully loaded)",
                    _num(assumptions.staffing_cost), "Operator payroll"),
        ExpenseLine("Food and supplies", _num(assumptions.food_supplies_cost),
                    "Operator actuals"),
        ExpenseLine("General + professional liability insurance",
                    _num(assumptions.insurance_cost), "Broker quote"),
        ExpenseLine("Utilities", _num(assumptions.utilities_cost),
                    "Operator estimate"),
    ]
    for label, value, basis in (
        ("Admin / software", assumptions.admin_software_cost, "Operator estimate"),
        ("Maintenance reserve", assumptions.maintenance_reserve, "Reserve policy"),
        ("Licensing cost amortisation", assumptions.licensing_amortized_cost,
         "Start-up cost spread"),
    ):
        if value:
            expenses.append(ExpenseLine(label, float(value), basis, is_fixed=False))

    economics = DealEconomics(
        resident_capacity=assumptions.resident_capacity,
        revenue_lines=revenue,
        expense_lines=expenses,
        proposed_phase1_rent=float(phase1_rent),
        proposed_phase2_rent=float(phase2_rent),
        phase1_months=lease.phase1_months,
        unverified_inputs=unverified,
    )

    log.info(
        "Underwrote %s: revenue $%s/mo, expenses $%s/mo, NOI $%s/mo",
        listing.address,
        f"{economics.gross_monthly_revenue:,.0f}",
        f"{economics.total_monthly_expenses:,.0f}",
        f"{economics.noi_monthly:,.0f}",
    )
    return economics


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def format_summary(economics: DealEconomics) -> str:
    """Plain-text pro-forma summary, safe to paste anywhere."""
    lines: list[str] = []
    lines.append("MONTHLY OPERATING MODEL")
    lines.append("-" * 58)

    lines.append("Revenue")
    for r in economics.revenue_lines:
        flag = "" if r.verified else "   [UNVERIFIED RATE]"
        lines.append(
            f"  {r.label:<42} {r.count} x ${r.monthly_rate:>8,.0f} "
            f"= ${r.monthly_total:>10,.0f}{flag}"
        )
    lines.append(f"  {'Gross monthly revenue':<42} {'':>21}${economics.gross_monthly_revenue:>10,.0f}")
    lines.append("")

    lines.append("Expenses")
    for e in economics.expense_lines:
        lines.append(f"  {e.label:<42} {'':>21}${e.monthly_amount:>10,.0f}")
    lines.append(f"  {'Total monthly expenses':<42} {'':>21}${economics.total_monthly_expenses:>10,.0f}")
    lines.append("")

    lines.append(f"  {'Net operating income (monthly)':<42} {'':>21}${economics.noi_monthly:>10,.0f}")
    lines.append(f"  {'Net operating income (annual)':<42} {'':>21}${economics.noi_annual:>10,.0f}")

    be = economics.breakeven_residents
    lines.append(f"  {'Break-even residents':<42} {'':>21}"
                 f"{be if be is not None else 'n/a':>11}")
    rcr = economics.rent_coverage_ratio
    lines.append(f"  {'Rent coverage ratio (revenue / rent)':<42} {'':>21}"
                 f"{rcr if rcr is not None else 'n/a':>11}")
    lines.append("")
    lines.append(f"  Phase 1 rent (months 1-{economics.phase1_months}): "
                 f"${economics.proposed_phase1_rent:,.0f}/mo")
    lines.append(f"  Phase 2 rent (operational):        "
                 f"${economics.proposed_phase2_rent:,.0f}/mo")
    lines.append(f"  Estimated Phase 1 monthly burn:    "
                 f"${economics.phase1_monthly_burn:,.0f}/mo (pre-revenue)")

    if economics.unverified_inputs:
        lines.append("")
        lines.append("!! UNVERIFIED OR MISSING INPUTS")
        for item in economics.unverified_inputs:
            lines.append(f"   - {item}")

    return "\n".join(lines)
