"""V2 evidence constants — categories and SEC section maps."""

from __future__ import annotations

# --- Recognized categories ---

RECOGNIZED_CATEGORIES: frozenset[str] = frozenset({
    # SEC
    "sec-annual",
    "sec-quarterly",
    "sec-earnings",
    "sec-financials",
    "sec-proxy",
    "sec-other",
    # External
    "industry-report",
    "competitor-data",
    "customer-evidence",
    "expert-input",
    "news",
    "company-ir",
    "regulatory",
    "other",
})

SEC_CATEGORIES: frozenset[str] = frozenset({
    "sec-annual",
    "sec-quarterly",
    "sec-earnings",
    "sec-financials",
    "sec-proxy",
    "sec-other",
})

# --- 10-K / 10-Q section maps ---
# Maps item number → (slug, display_name) for per-section file naming.

SECTION_MAP_10K: dict[str, tuple[str, str]] = {
    "1": ("business", "Business"),
    "1A": ("risk-factors", "Risk Factors"),
    "1B": ("unresolved-staff-comments", "Unresolved Staff Comments"),
    "1C": ("cybersecurity", "Cybersecurity"),
    "2": ("properties", "Properties"),
    "3": ("legal-proceedings", "Legal Proceedings"),
    "4": ("mine-safety-disclosures", "Mine Safety Disclosures"),
    "5": ("market-for-registrant", "Market for Registrant"),
    "7": ("mdna", "MD&A"),
    "7A": ("quantitative-qualitative-market-risk", "Quantitative & Qualitative Market Risk"),
    "8": ("financial-statements", "Financial Statements"),
    "9": ("changes-disagreements-accountants", "Changes/Disagreements with Accountants"),
    "9A": ("controls-and-procedures", "Controls and Procedures"),
    "9B": ("other-information", "Other Information"),
    "10": ("directors-and-officers", "Directors and Officers"),
    "11": ("executive-compensation", "Executive Compensation"),
    "12": ("security-ownership", "Security Ownership"),
    "13": ("related-transactions", "Related Transactions"),
    "14": ("principal-accountant-fees", "Principal Accountant Fees"),
    "15": ("exhibits-schedules", "Exhibits and Schedules"),
}

SECTION_MAP_10Q: dict[str, tuple[str, str]] = {
    "1": ("financial-statements", "Financial Statements"),
    "2": ("mdna", "MD&A"),
    "3": ("quantitative-qualitative-market-risk", "Quantitative & Qualitative Market Risk"),
    "4": ("controls-and-procedures", "Controls and Procedures"),
    "1A": ("risk-factors", "Risk Factors"),
    "5": ("other-information", "Other Information"),
    "6": ("exhibits", "Exhibits"),
}

# Default items to download for each form type.
DEFAULT_10K_ITEMS: list[str] = ["1", "1A", "1C", "2", "3", "7", "7A", "8", "9A"]
DEFAULT_10Q_ITEMS: list[str] = ["1", "2", "1A", "4"]
