"""
loi_generator.py
================
Builds a clean, institutional 2-page "Corporate Master Lease with Option to
Purchase" Letter of Intent using ReportLab Platypus.

LEGAL POSTURE -- READ THIS
--------------------------
This generates a NON-BINDING letter of intent. That is deliberate and the
non-binding clause is not optional -- do not delete it. An LOI that reads as a
binding offer can create an enforceable contract, and this one proposes a
multi-year rent guarantee.

I am not a lawyer and this is not legal advice. Have an Oregon real estate
attorney review the template ONCE before you send the first one, and have them
review the actual lease every time. The specific items worth their attention:

  * The "guaranteed rent" language. You are promising to pay whether or not
    the home ever gets licensed and whether or not it ever fills. Confirm you
    want that exposure, and consider whether the licensing contingency should
    survive into the lease as a termination right rather than dying at signing.
  * The purchase option strike price and whether Oregon recording or notice
    requirements apply.
  * Whether the modifications addendum adequately allocates who pays for and
    who owns the accessibility improvements at lease end.
  * Any disclosure obligation you have to the landlord about the intended use.

Design notes
------------
* Never use Unicode superscript/subscript glyphs -- ReportLab's built-in fonts
  lack them and they render as black boxes. Use <super> / <sub> markup.
* Content is sized to land on exactly two pages with a normal 5-6 line address
  block. A very long property address or agent name can push it to three; the
  `verify_page_count` helper tells you when that happens.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

import config
from models import AFHAssessment, DealEconomics, Listing

log = logging.getLogger(__name__)

ACCENT = colors.HexColor("#1F3A5F")
RULE = colors.HexColor("#B8C4D4")
MUTED = colors.HexColor("#55606E")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    s: dict[str, ParagraphStyle] = {}

    s["company"] = ParagraphStyle(
        "company", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=15, leading=18, textColor=ACCENT, spaceAfter=2,
    )
    s["companymeta"] = ParagraphStyle(
        "companymeta", parent=base["Normal"], fontName="Helvetica",
        fontSize=8.5, leading=11, textColor=MUTED,
    )
    s["doctitle"] = ParagraphStyle(
        "doctitle", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=12, leading=14.5, alignment=TA_CENTER, textColor=ACCENT,
        spaceBefore=6, spaceAfter=2,
    )
    s["docsub"] = ParagraphStyle(
        "docsub", parent=base["Normal"], fontName="Helvetica-Oblique",
        fontSize=9, leading=12, alignment=TA_CENTER, textColor=MUTED,
        spaceAfter=8,
    )
    s["h2"] = ParagraphStyle(
        "h2", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=9, leading=11, textColor=ACCENT,
        spaceBefore=6, spaceAfter=2,
    )
    s["body"] = ParagraphStyle(
        "body", parent=base["Normal"], fontName="Helvetica",
        fontSize=8.4, leading=11.2, alignment=TA_JUSTIFY, spaceAfter=4,
    )
    s["small"] = ParagraphStyle(
        "small", parent=base["Normal"], fontName="Helvetica",
        fontSize=7.5, leading=10, textColor=MUTED,
    )
    s["cell"] = ParagraphStyle(
        "cell", parent=base["Normal"], fontName="Helvetica",
        fontSize=8.1, leading=10.4,
    )
    s["cellb"] = ParagraphStyle(
        "cellb", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=8.1, leading=10.4,
    )
    return s


def _money(value: Optional[float]) -> str:
    if value is None or value <= 0:
        return "[TO BE COMPLETED]"
    return f"${value:,.0f}"


# ---------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------

def _make_page_decorator(company: config.CompanyProfile, prop_address: str):
    def _decorate(canvas, doc) -> None:
        canvas.saveState()
        w, h = letter

        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(0.75 * inch, 0.72 * inch, w - 0.75 * inch, 0.72 * inch)

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            0.75 * inch, 0.55 * inch,
            f"Non-binding Letter of Intent  |  {prop_address[:58]}",
        )
        canvas.drawRightString(
            w - 0.75 * inch, 0.55 * inch, f"Page {doc.page} of 2"
        )
        canvas.restoreState()

    return _decorate


def _letterhead(company: config.CompanyProfile, s: dict[str, ParagraphStyle]) -> list:
    name = company.legal_name or "[COMPANY LEGAL NAME]"
    meta_bits = [company.mailing_address, company.phone, company.email,
                 company.website]
    meta = "  |  ".join(b for b in meta_bits if b) or "[CONTACT DETAILS]"

    tbl = Table(
        [[Paragraph(name, s["company"])],
         [Paragraph(meta, s["companymeta"])]],
        colWidths=[7.0 * inch],
    )
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 1), (-1, 1), 1.1, ACCENT),
    ]))
    return [tbl, Spacer(1, 10)]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def generate_loi(
    listing: Listing,
    economics: Optional[DealEconomics] = None,
    assessment: Optional[AFHAssessment] = None,
    *,
    output_dir: Path = config.OUTPUT_DIR,
    company: config.CompanyProfile = config.COMPANY,
    lease: config.LeaseTerms = config.LEASE,
    purchase_strike_price: Optional[int] = None,
    letter_date: Optional[date] = None,
) -> Path:
    """Render the 2-page LOI PDF and return its path."""
    s = _styles()
    letter_date = letter_date or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"LOI_{listing.slug}_{letter_date:%Y%m%d}.pdf"

    full_address = ", ".join(
        p for p in [listing.address, listing.city,
                    f"OR {listing.zip_code}" if listing.zip_code else "OR"] if p
    )

    p1_rent = economics.proposed_phase1_rent if economics else None
    p2_rent = economics.proposed_phase2_rent if economics else None
    if p1_rent is None and assessment:
        p1_rent = assessment.suggested_phase1_holding_rent
    if p2_rent is None and assessment:
        p2_rent = assessment.suggested_phase2_full_rent

    if purchase_strike_price is None and listing.list_price:
        purchase_strike_price = listing.list_price

    story: list = []
    story += _letterhead(company, s)

    # ---------------- Page 1 ----------------
    story.append(Paragraph(
        "LETTER OF INTENT<br/>CORPORATE MASTER LEASE WITH OPTION TO PURCHASE",
        s["doctitle"]))
    story.append(Paragraph(
        "Non-binding proposal submitted for discussion purposes", s["docsub"]))

    agent_name = listing.agent.name or "Listing Agent"
    brokerage = listing.agent.brokerage or ""
    recipient = f"{agent_name}" + (f", {brokerage}" if brokerage else "")

    info_rows = [
        [Paragraph("Date", s["cellb"]), Paragraph(letter_date.strftime("%B %d, %Y"), s["cell"])],
        [Paragraph("To", s["cellb"]), Paragraph(f"{recipient}<br/>On behalf of the Property Owner", s["cell"])],
        [Paragraph("From", s["cellb"]), Paragraph(
            f"{company.signer_name or '[SIGNER]'}, {company.signer_title}<br/>"
            f"{company.legal_name or '[COMPANY]'} (\"Tenant\")", s["cell"])],
        [Paragraph("Property", s["cellb"]), Paragraph(full_address, s["cell"])],
        [Paragraph("Subject", s["cellb"]), Paragraph(
            "Proposal for a long-term corporate master lease with an option to "
            "purchase", s["cell"])],
    ]
    if listing.listing_url:
        info_rows.append([Paragraph("Listing", s["cellb"]),
                          Paragraph(listing.listing_url[:95], s["cell"])])

    info = Table(info_rows, colWidths=[1.05 * inch, 5.95 * inch])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]))
    story.append(info)
    story.append(Spacer(1, 7))

    story.append(Paragraph(
        f"{company.legal_name or '[COMPANY]'} (\"Tenant\") is pleased to submit "
        f"this non-binding Letter of Intent to lease the property at "
        f"<b>{full_address}</b> (the \"Property\") from its owner (\"Landlord\") "
        "under a corporate master lease. Tenant intends to operate the Property "
        "as a state-licensed residential care home for older adults and adults "
        "with disabilities, subject to the licensing and site-suitability "
        "contingency described in Section 7.",
        s["body"]))
    story.append(Paragraph(
        "Tenant is a single corporate lessee. Tenant is responsible for the "
        "full monthly rent regardless of the Property's internal occupancy, "
        "and Landlord deals with one professionally insured counterparty rather "
        "than a series of individual residential tenants.",
        s["body"]))

    story.append(Paragraph("1.  PARTIES AND PREMISES", s["h2"]))
    story.append(Paragraph(
        f"<b>Tenant:</b> {company.legal_name or '[COMPANY]'}, an Oregon limited "
        f"liability company.<br/>"
        f"<b>Landlord:</b> The record owner of the Property, to be identified in "
        f"the definitive lease.<br/>"
        f"<b>Premises:</b> {full_address}, together with all improvements, "
        "appurtenances and parking.", s["body"]))

    story.append(Paragraph("2.  LEASE TERM AND COMMENCEMENT", s["h2"]))
    story.append(Paragraph(
        f"An initial term of {lease.term_years_min} to {lease.term_years_max} "
        f"years, commencing on a date to be mutually agreed following the "
        f"expiration of the contingency period in Section 7. Tenant requests two "
        f"(2) renewal options of {lease.term_years_min} years each, exercisable "
        "on written notice not less than one hundred eighty (180) days before "
        "the then-current expiration date, with rent at renewal to be set as "
        "provided in the definitive lease.", s["body"]))

    story.append(Paragraph("3.  TWO-PHASE RENT STRUCTURE", s["h2"]))
    story.append(Paragraph(
        "Tenant proposes a phased rent that reflects the licensing timeline. "
        "During Phase 1 the Property generates no revenue while the licensing "
        "application, site review and any required modifications are completed. "
        "The reduced Phase 1 rent is intended to cover Landlord's carrying "
        "costs during that period. Phase 2 rent is set at a premium to "
        "prevailing market residential rent in consideration of the long term, "
        "the corporate guarantee and the intensity of use.", s["body"]))

    rent_tbl = Table([
        [Paragraph("Phase", s["cellb"]), Paragraph("Period", s["cellb"]),
         Paragraph("Monthly Rent", s["cellb"]), Paragraph("Purpose", s["cellb"])],
        [Paragraph("Phase 1<br/>Holding", s["cell"]),
         Paragraph(f"Months 1 through {lease.phase1_months}", s["cell"]),
         Paragraph(f"<b>{_money(p1_rent)}</b>", s["cell"]),
         Paragraph("Inspection, licensing application, site review and "
                   "modifications. Covers Landlord carrying costs.", s["cell"])],
        [Paragraph("Phase 2<br/>Operational", s["cell"]),
         Paragraph(f"Month {lease.phase1_months + 1} through end of term", s["cell"]),
         Paragraph(f"<b>{_money(p2_rent)}</b>", s["cell"]),
         Paragraph("Full guaranteed monthly rent, payable on the first of each "
                   "month regardless of internal occupancy.", s["cell"])],
    ], colWidths=[0.95 * inch, 1.5 * inch, 1.15 * inch, 3.4 * inch])
    rent_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F7")),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(KeepTogether(rent_tbl))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Security deposit: {lease.security_deposit_months:g} month(s) of Phase 2 "
        "rent, payable at lease execution. Rent escalation over the term to be "
        "agreed, and Tenant is open to a fixed annual increase.", s["body"]))

    story.append(Paragraph("4.  COMMERCIAL TERMS AND PROPERTY CARE", s["h2"]))
    story.append(Paragraph(
        "Tenant will be responsible for routine interior maintenance, "
        "housekeeping, landscaping and yard care, minor repairs, and all "
        "utilities. Landlord remains responsible for the roof, foundation, "
        "structural elements, and the major building systems except where damage "
        "results from Tenant's negligence. The Property will be professionally "
        "cleaned and maintained on a continuous basis and will be occupied and "
        "supervised twenty-four hours per day, which materially reduces the risk "
        "of vacancy damage, undetected leaks and vandalism.", s["body"]))

    story.append(PageBreak())

    # ---------------- Page 2 ----------------
    story.append(Paragraph("5.  INSURANCE", s["h2"]))
    story.append(Paragraph(
        f"Tenant will maintain, at Tenant's expense and throughout the term, "
        f"commercial general liability and professional liability coverage of not "
        f"less than {lease.liability_per_occurrence} per occurrence and "
        f"{lease.liability_aggregate} in the aggregate, together with statutory "
        "workers' compensation coverage and renter's or business personal "
        "property coverage. Landlord will be named as an additional insured, and "
        "certificates of insurance will be delivered at execution and at each "
        "renewal. Tenant will provide Landlord not less than thirty (30) days' "
        "notice of cancellation or material change.", s["body"]))

    story.append(Paragraph("6.  PROPERTY MODIFICATIONS ADDENDUM", s["h2"]))
    story.append(Paragraph(
        "Landlord agrees to permit reasonable accessibility enhancements at "
        "Tenant's sole cost, subject to Landlord's prior written approval of "
        "plans, which approval will not be unreasonably withheld. Anticipated "
        "modifications include exterior and interior ramps or threshold "
        "transitions, grab bars and bathroom safety fixtures, lever-style door "
        "handles, handrails, improved exterior and interior lighting, hard-wired "
        "smoke and carbon monoxide detection, and where required, egress window "
        "or door adjustments to satisfy the applicable Oregon administrative "
        "rules for adult foster homes (OAR chapter 411, division 050) and the "
        "applicable building and fire code officials.", s["body"]))
    story.append(Paragraph(
        "All work will be performed by licensed, bonded and insured "
        "contractors, with permits pulled where required. At the end of the "
        "term, Landlord may elect in writing either to have Tenant remove "
        "specified modifications and restore the affected areas to their prior "
        "condition, ordinary wear and tear excepted, or to retain the "
        "improvements at no cost to Landlord. Many of these improvements are "
        "durable, code-compliant upgrades that increase the Property's appeal "
        "to the aging-in-place buyer market.", s["body"]))

    story.append(Paragraph("7.  DUE DILIGENCE AND LICENSING CONTINGENCY", s["h2"]))
    story.append(Paragraph(
        f"This proposal is contingent on a {lease.due_diligence_days}-day due "
        "diligence period beginning on the date of a mutually executed letter of "
        "intent, during which Tenant will confirm at Tenant's expense: (a) the "
        "physical suitability of the Property for licensed residential care use, "
        "including a walkthrough with a licensing representative where "
        "available; (b) zoning, land use and any conditional use requirements "
        "with the applicable county or municipal planning authority; (c) the "
        "absence of any covenant, condition, restriction or homeowners "
        "association rule that would prohibit the intended use; (d) septic, "
        "well, water and utility capacity; and (e) the condition of the Property "
        "by professional inspection. If any of these cannot be satisfied, Tenant "
        "may terminate without penalty and any deposit will be refunded in "
        "full.", s["body"]))

    story.append(Paragraph("8.  OPTION TO PURCHASE", s["h2"]))
    strike = (f"${purchase_strike_price:,}" if purchase_strike_price
              else "[STRIKE PRICE TO BE AGREED]")
    story.append(Paragraph(
        f"Tenant requests an exclusive option to purchase the Property at any "
        f"time during the initial term at a strike price of <b>{strike}</b>, "
        "exercisable on sixty (60) days' written notice. The parties will agree "
        "in the definitive documents on the treatment of any rent credit, the "
        "closing timeline, and the allocation of closing costs. Tenant is also "
        "open to discussing a right of first refusal in lieu of a fixed-price "
        "option.", s["body"]))

    story.append(Paragraph("9.  BROKERAGE", s["h2"]))
    story.append(Paragraph(
        "Tenant acknowledges the listing broker's role and intends that the "
        "listing brokerage be compensated in accordance with the listing "
        "agreement, both on the lease transaction and on any subsequent exercise "
        "of the purchase option. Tenant is not represented by a separate "
        "brokerage in this transaction unless disclosed in writing.", s["body"]))

    story.append(Paragraph("10.  NON-BINDING NATURE OF THIS LETTER", s["h2"]))
    story.append(Paragraph(
        "<b>This Letter of Intent is a non-binding expression of interest and an "
        "invitation to negotiate. It does not create a lease, an option, or any "
        "obligation on either party to enter into any agreement. No party will "
        "be bound unless and until a definitive written lease is negotiated, "
        "approved and executed by both parties. Either party may terminate "
        "discussions at any time and for any reason, without liability.</b> The "
        "only provisions intended to be binding are the parties' agreement to "
        "keep the terms of these discussions confidential and to bear their own "
        "costs. This letter is governed by the laws of the State of Oregon. "
        "Each party should obtain independent legal and tax advice before "
        "entering into any definitive agreement.", s["body"]))

    story.append(Spacer(1, 8))

    sig = Table([
        [Paragraph("Submitted by:", s["cellb"]), Paragraph("Acknowledged and received:", s["cellb"])],
        [Paragraph("<br/><br/>______________________________", s["cell"]),
         Paragraph("<br/><br/>______________________________", s["cell"])],
        [Paragraph(
            f"{company.signer_name or '[SIGNER NAME]'}<br/>"
            f"{company.signer_title}<br/>"
            f"{company.legal_name or '[COMPANY]'}<br/>"
            f"{company.phone}<br/>{company.email}", s["small"]),
         Paragraph(
             f"{agent_name}<br/>{brokerage or 'Brokerage'}<br/>"
             "On behalf of Landlord<br/>Date: ______________", s["small"])],
    ], colWidths=[3.5 * inch, 3.5 * inch])
    sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(sig)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.55 * inch, bottomMargin=0.8 * inch,
        title=f"Letter of Intent - {full_address}",
        author=company.legal_name or "Tenant",
        subject="Corporate Master Lease with Option to Purchase",
    )
    decorator = _make_page_decorator(company, full_address)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator)

    log.info("Wrote LOI: %s", out_path)
    return out_path


def verify_page_count(pdf_path: Path, expected: int = 2) -> bool:
    """Best-effort page count check. Returns True if it matches `expected`."""
    try:
        from pypdf import PdfReader  # optional dependency
        pages = len(PdfReader(str(pdf_path)).pages)
    except Exception:  # noqa: BLE001
        data = Path(pdf_path).read_bytes()
        pages = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    if pages != expected:
        log.warning("LOI is %d pages, expected %d: %s", pages, expected, pdf_path)
        return False
    return True
