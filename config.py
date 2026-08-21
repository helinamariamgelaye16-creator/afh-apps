"""
config.py
=========
Single source of truth for credentials, geography, screening thresholds,
lease terms and underwriting assumptions.

READ THIS BEFORE YOU RUN ANYTHING
---------------------------------
This module deliberately ships with NO invented Oregon APD / Medicaid
reimbursement rates. Care-tier rates change with rule revisions and
legislative sessions, and a pro-forma built on a hallucinated rate is worse
than no pro-forma at all. You must supply them in `.env` along with the
effective date of the schedule you pulled them from. If you don't,
deal_calculator.py raises and tells you exactly which values are missing.

Same rule for staffing, insurance and food costs -- put YOUR actual numbers in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Optional

from dotenv import load_dotenv

BASE_DIR: Final[Path] = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OUTPUT_DIR: Final[Path] = BASE_DIR / "output"
LOG_DIR: Final[Path] = BASE_DIR / "logs"
STATE_DIR: Final[Path] = BASE_DIR / "state"
for _d in (OUTPUT_DIR, LOG_DIR, STATE_DIR):
    _d.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# env helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


def _env_int(key: str, default: Optional[int] = None) -> Optional[int]:
    raw = _env(key)
    if raw in (None, ""):
        return default
    try:
        return int(float(raw))
    except ValueError:
        raise ValueError(f"Environment variable {key}={raw!r} is not a number.")


def _env_float(key: str, default: Optional[float] = None) -> Optional[float]:
    raw = _env(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"Environment variable {key}={raw!r} is not a number.")


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "y", "on")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY: Final[Optional[str]] = _env("ANTHROPIC_API_KEY")

# Model string is env-configurable on purpose -- model names change.
# Verify the current list at https://docs.claude.com/en/docs/about-claude/models
ANTHROPIC_MODEL: Final[str] = _env("ANTHROPIC_MODEL", "claude-sonnet-5") or "claude-sonnet-5"
ANTHROPIC_MAX_TOKENS: Final[int] = _env_int("ANTHROPIC_MAX_TOKENS", 4000) or 4000

GMAIL_CREDENTIALS_PATH: Final[Path] = Path(
    _env("GMAIL_CREDENTIALS_PATH", str(BASE_DIR / "credentials.json"))
)
GMAIL_TOKEN_PATH: Final[Path] = Path(
    _env("GMAIL_TOKEN_PATH", str(BASE_DIR / "token.json"))
)

# gmail.modify  -> read messages + mark them read
# gmail.compose -> create drafts (does NOT grant send)
GMAIL_SCOPES: Final[list[str]] = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]

# Gmail search query used to find listing alerts.
GMAIL_SEARCH_QUERY: Final[str] = _env(
    "GMAIL_SEARCH_QUERY",
    "is:unread (from:zillow.com OR from:redfin.com OR from:realtor.com OR "
    "from:move.com) newer_than:14d",
) or ""

GMAIL_MAX_MESSAGES: Final[int] = _env_int("GMAIL_MAX_MESSAGES", 25) or 25
GMAIL_MARK_READ: Final[bool] = _env_bool("GMAIL_MARK_READ", False)


# ---------------------------------------------------------------------------
# Company profile (goes on the LOI letterhead and in the email signature)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompanyProfile:
    legal_name: str
    dba: str
    signer_name: str
    signer_title: str
    phone: str
    email: str
    mailing_address: str
    website: str = ""

    # Claims that appear in outbound documents. Keep these conservative --
    # anything here is a representation to a landlord.
    state_licensure_language: str = ""

    @property
    def signature_block(self) -> str:
        lines = [self.signer_name, self.signer_title, self.legal_name,
                 self.phone, self.email]
        return "\n".join(x for x in lines if x)


COMPANY: Final[CompanyProfile] = CompanyProfile(
    legal_name=_env("COMPANY_LEGAL_NAME", "") or "",
    dba=_env("COMPANY_DBA", "") or "",
    signer_name=_env("SIGNER_NAME", "") or "",
    signer_title=_env("SIGNER_TITLE", "Owner") or "Owner",
    phone=_env("COMPANY_PHONE", "") or "",
    email=_env("COMPANY_EMAIL", "") or "",
    mailing_address=_env("COMPANY_MAILING_ADDRESS", "") or "",
    website=_env("COMPANY_WEBSITE", "") or "",
    state_licensure_language=_env("LICENSURE_LANGUAGE", "") or "",
)


# ---------------------------------------------------------------------------
# Geography: Clackamas County, Oregon
# ---------------------------------------------------------------------------

CLACKAMAS_CITIES: Final[frozenset[str]] = frozenset({
    "happy valley", "damascus", "oregon city", "gladstone", "milwaukie",
    "west linn", "lake oswego", "sandy", "estacada", "molalla", "canby",
    "wilsonville", "boring", "colton", "beavercreek", "clackamas",
    "eagle creek", "mulino", "oak grove", "jennings lodge", "johnson city",
    "rivergrove", "barlow", "aurora", "welches", "brightwood",
    "government camp", "rhododendron", "wemme", "marylhurst", "redland",
    "carver", "logan", "scotts mills",
})

# ZIP codes wholly or mostly inside Clackamas County.
CLACKAMAS_ZIPS: Final[frozenset[str]] = frozenset({
    "97004",  # Beavercreek
    "97009",  # Boring
    "97011",  # Brightwood
    "97013",  # Canby
    "97015",  # Clackamas
    "97017",  # Colton
    "97022",  # Eagle Creek
    "97023",  # Estacada
    "97027",  # Gladstone
    "97028",  # Government Camp
    "97034",  # Lake Oswego
    "97038",  # Molalla
    "97042",  # Mulino
    "97045",  # Oregon City
    "97049",  # Rhododendron
    "97055",  # Sandy
    "97067",  # Welches
    "97068",  # West Linn
    "97086",  # Happy Valley
    "97089",  # Damascus
    "97222",  # Milwaukie
    "97267",  # Oak Grove / Milwaukie
    "97269",  # Milwaukie (PO)
})

# ZIPs that STRADDLE a county line. A hit here is not proof of county.
# The pipeline flags these for manual verification against the Clackamas
# County Assessor's parcel lookup rather than assuming.
STRADDLE_ZIPS: Final[frozenset[str]] = frozenset({
    "97035",  # Lake Oswego  - Clackamas / Washington
    "97070",  # Wilsonville  - Clackamas / Washington
    "97140",  # Sherwood     - Washington / Clackamas
    "97002",  # Aurora       - Marion / Clackamas
    "97062",  # Tualatin     - Washington / Clackamas
    "97236",  # Portland     - Multnomah / Clackamas
})


# ---------------------------------------------------------------------------
# Screening thresholds
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScreeningThresholds:
    min_bedrooms: float = 5.0
    # A 4-bed with a den/bonus can still qualify -- handled as a soft pass.
    min_bedrooms_with_bonus: float = 4.0
    min_days_on_market: int = 30
    min_square_feet: int = 2000
    max_list_price: int = 900_000
    min_list_price: int = 200_000
    go_no_go_score: int = 75

    # OAR 411-050 minimum usable floor area for a SHARED resident bedroom.
    # VERIFY the current figure against the live rule text before relying on
    # it -- this is used as a screening heuristic only, not a compliance test.
    shared_bedroom_min_sqft: int = 120
    single_bedroom_min_sqft: int = 80

    bonus_room_keywords: tuple[str, ...] = (
        "den", "bonus room", "office", "flex room", "study", "media room",
        "fourth bedroom", "converted garage", "sunroom",
    )


THRESHOLDS: Final[ScreeningThresholds] = ScreeningThresholds(
    min_bedrooms=_env_float("MIN_BEDROOMS", 5.0) or 5.0,
    min_days_on_market=_env_int("MIN_DOM", 30) or 30,
    min_square_feet=_env_int("MIN_SQFT", 2000) or 2000,
    max_list_price=_env_int("MAX_LIST_PRICE", 900_000) or 900_000,
    min_list_price=_env_int("MIN_LIST_PRICE", 200_000) or 200_000,
    go_no_go_score=_env_int("GO_NO_GO_SCORE", 75) or 75,
)

MOTIVATION_KEYWORDS: Final[tuple[str, ...]] = (
    "motivated seller", "bring all offers", "bring offers", "vacant",
    "estate sale", "investor special", "previously rented", "as-is", "as is",
    "price reduced", "price improvement", "must sell", "relocating",
    "seller will consider", "flexible terms", "handyman special",
    "needs tlc", "probate", "trust sale", "back on market", "lease option",
    "seller financing", "owner carry",
)


# ---------------------------------------------------------------------------
# Lease structure proposed in the LOI
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LeaseTerms:
    term_years_min: int = 3
    term_years_max: int = 5
    phase1_months: int = 4
    phase1_pct_of_market_low: float = 0.50
    phase1_pct_of_market_high: float = 0.60
    phase2_premium_over_market: float = 0.10
    due_diligence_days: int = 60
    liability_per_occurrence: str = "$1,000,000"
    liability_aggregate: str = "$2,000,000"
    security_deposit_months: float = 1.0
    purchase_option_years: int = 5


LEASE: Final[LeaseTerms] = LeaseTerms(
    phase1_months=_env_int("PHASE1_MONTHS", 4) or 4,
    due_diligence_days=_env_int("DUE_DILIGENCE_DAYS", 60) or 60,
)


# ---------------------------------------------------------------------------
# Underwriting inputs  -- NO DEFAULTS. You must supply these.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnderwritingAssumptions:
    """
    Every monetary field here is Optional and defaults to None.

    deal_calculator.py collects the Nones and raises a single, readable
    MissingAssumptionsError listing exactly what you still need to fill in.
    This is intentional: it is not possible to responsibly guess an Oregon
    APD care-tier rate on your behalf.
    """
    resident_capacity: int = 5

    # --- revenue ---
    medicaid_resident_count: Optional[int] = None
    medicaid_monthly_rate: Optional[float] = None
    medicaid_rate_source: str = ""        # e.g. "APD rate schedule eff. YYYY-MM-DD"

    private_pay_resident_count: Optional[int] = None
    private_pay_monthly_rate: Optional[float] = None
    private_pay_rate_source: str = ""

    room_and_board_monthly: Optional[float] = None
    room_and_board_source: str = ""

    # --- expenses (monthly) ---
    staffing_cost: Optional[float] = None          # fully loaded, 24/7 coverage
    food_supplies_cost: Optional[float] = None
    insurance_cost: Optional[float] = None         # GL + professional
    utilities_cost: Optional[float] = None
    admin_software_cost: Optional[float] = None
    maintenance_reserve: Optional[float] = None
    licensing_amortized_cost: Optional[float] = None

    # --- notes ---
    assumptions_effective_date: str = ""


ASSUMPTIONS: Final[UnderwritingAssumptions] = UnderwritingAssumptions(
    resident_capacity=_env_int("RESIDENT_CAPACITY", 5) or 5,
    medicaid_resident_count=_env_int("MEDICAID_RESIDENT_COUNT"),
    medicaid_monthly_rate=_env_float("MEDICAID_MONTHLY_RATE"),
    medicaid_rate_source=_env("MEDICAID_RATE_SOURCE", "") or "",
    private_pay_resident_count=_env_int("PRIVATE_PAY_RESIDENT_COUNT"),
    private_pay_monthly_rate=_env_float("PRIVATE_PAY_MONTHLY_RATE"),
    private_pay_rate_source=_env("PRIVATE_PAY_RATE_SOURCE", "") or "",
    room_and_board_monthly=_env_float("ROOM_AND_BOARD_MONTHLY"),
    room_and_board_source=_env("ROOM_AND_BOARD_SOURCE", "") or "",
    staffing_cost=_env_float("STAFFING_MONTHLY_COST"),
    food_supplies_cost=_env_float("FOOD_SUPPLIES_MONTHLY_COST"),
    insurance_cost=_env_float("INSURANCE_MONTHLY_COST"),
    utilities_cost=_env_float("UTILITIES_MONTHLY_COST"),
    admin_software_cost=_env_float("ADMIN_SOFTWARE_MONTHLY_COST"),
    maintenance_reserve=_env_float("MAINTENANCE_RESERVE_MONTHLY"),
    licensing_amortized_cost=_env_float("LICENSING_AMORTIZED_MONTHLY"),
    assumptions_effective_date=_env("ASSUMPTIONS_EFFECTIVE_DATE", "") or "",
)


# ---------------------------------------------------------------------------
# Runtime switches
# ---------------------------------------------------------------------------

DRY_RUN_DEFAULT: Final[bool] = _env_bool("DRY_RUN", True)
CREATE_DRAFTS: Final[bool] = _env_bool("CREATE_DRAFTS", False)
LOG_LEVEL: Final[str] = (_env("LOG_LEVEL", "INFO") or "INFO").upper()

# Hard safety rail. The pipeline has no send path at all, but this makes the
# intent explicit and greppable.
ALLOW_AUTO_SEND: Final[bool] = False


def validate_startup(require_anthropic: bool = True,
                     require_gmail: bool = True) -> list[str]:
    """Return a list of human-readable configuration problems (empty == OK)."""
    problems: list[str] = []

    if require_anthropic and not ANTHROPIC_API_KEY:
        problems.append("ANTHROPIC_API_KEY is not set in .env")

    if require_gmail and not GMAIL_CREDENTIALS_PATH.exists():
        problems.append(
            f"Gmail OAuth client file not found at {GMAIL_CREDENTIALS_PATH}. "
            "Download it from Google Cloud Console (see README)."
        )

    if not COMPANY.legal_name:
        problems.append("COMPANY_LEGAL_NAME is not set -- the LOI needs a party name.")
    if not COMPANY.signer_name:
        problems.append("SIGNER_NAME is not set -- the LOI needs a signature block.")
    if not COMPANY.email:
        problems.append("COMPANY_EMAIL is not set -- the LOI needs a reply address.")

    return problems
