"""V2 evidence constants — categories, extraction questions, context bundles.

These replace the YAML profile files under profiles/. All evidence
and analysis config is defined here as Python constants.
"""

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

# --- Extraction questions by category ---
# Each key maps to a list of {"id": ..., "question": ...} dicts.

EXTRACTION_QUESTIONS: dict[str, list[dict[str, str]]] = {
    "sec-annual": [
        {"id": "business-overview", "question": "Summarize the business model, operating segments, and primary revenue drivers."},
        {"id": "financial-highlights", "question": "Extract the key financial metrics as a markdown table with columns: Metric, Current Period, Prior Period, YoY Change. Include revenue, operating income, net income, EPS, and any segment-level breakdowns."},
        {"id": "growth-drivers", "question": "What is actually driving growth or decline? Identify the specific products, segments, geographies, or initiatives management credits for changes in revenue and profitability. Include numbers."},
        {"id": "competition", "question": "Summarize the competitive positioning, moats, and management's framing of competition."},
        {"id": "management", "question": "Summarize management priorities, strategic initiatives, and capital allocation signals."},
        {"id": "risks", "question": "Summarize the most important business and operating risks."},
    ],
    "sec-quarterly": [
        {"id": "recent-update", "question": "Summarize the most important quarter-to-date operating changes and management commentary."},
        {"id": "financial-update", "question": "Extract the key quarter financial metrics as a markdown table: Metric, Current Quarter, Prior Year Quarter, YoY Change. Include revenue, operating income, net income, and EPS."},
        {"id": "risks", "question": "Summarize the most important new or changed risks mentioned in the filing."},
    ],
    "sec-earnings": [
        {"id": "earnings-takeaways", "question": "Summarize the most important earnings takeaways, KPIs, and guidance changes."},
        {"id": "kpi-summary", "question": "Extract the key reported KPIs as a markdown table: KPI, Value, Prior Period Value, Change. Include user/customer metrics, engagement metrics, and unit economics."},
        {"id": "guidance", "question": "Extract any forward guidance, targets, or outlook statements. Quote management directly where possible. If no guidance was provided, state that explicitly."},
        {"id": "management", "question": "Summarize management's near-term priorities and tone from the earnings material."},
    ],
    "sec-financials": [
        {"id": "statement-summary", "question": "Summarize the key trends and material year-over-year changes."},
    ],
    "industry-report": [
        {"id": "external-evidence", "question": "Summarize the most important third-party evidence and how it changes the business view."},
    ],
    "competitor-data": [
        {"id": "external-evidence", "question": "Summarize competitor positioning and what it implies for the target company."},
    ],
    "customer-evidence": [
        {"id": "external-evidence", "question": "Summarize what customers say and what it implies for the business."},
    ],
    "news": [
        {"id": "external-evidence", "question": "Summarize newsworthy developments and their implications."},
    ],
    "company-ir": [
        {"id": "external-evidence", "question": "Summarize IR content and how it changes the business view."},
    ],
    "expert-input": [
        {"id": "external-evidence", "question": "Summarize expert input and its implications."},
    ],
}

# --- Context bundle definitions ---
# Each bundle specifies which evidence categories feed into it.

CONTEXT_BUNDLES: list[dict] = [
    {
        "name": "business-overview",
        "categories": ["sec-annual", "sec-quarterly", "industry-report", "company-ir"],
    },
    {
        "name": "competition",
        "categories": ["sec-annual", "industry-report", "competitor-data"],
    },
    {
        "name": "management",
        "categories": ["sec-annual", "sec-earnings"],
    },
    {
        "name": "risks",
        "categories": ["sec-annual", "sec-quarterly", "news", "regulatory"],
    },
    {
        "name": "valuation",
        "categories": ["sec-financials", "sec-earnings"],
        "extra_globs": ["analysis/valuation/**/*.md"],
    },
]

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
