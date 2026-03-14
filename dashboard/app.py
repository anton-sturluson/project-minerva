"""FastAPI dashboard for JobWatch — 90s retro hiring radar."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobwatch.config import COMPANY_REGISTRY, CompanyConfig
from jobwatch.db import JobWatchDB

_BASE_DIR: Path = Path(__file__).resolve().parent
_DB_PATH: Path = Path(os.environ.get("JOBWATCH_DB_PATH", "data/jobwatch.db"))

app: FastAPI = FastAPI(title="JobWatch Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

templates: Jinja2Templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

DEPT_LABELS: dict[str, str] = {
    "ENG": "Engineering",
    "RES": "Research",
    "PROD": "Product",
    "DES": "Design",
    "DATA": "Data & Analytics",
    "INFRA": "Infrastructure",
    "SEC": "Security",
    "SALES": "Sales",
    "MKT": "Marketing",
    "CS": "Customer Success",
    "OPS": "Operations",
    "PPL": "People",
    "FIN": "Finance",
    "LEGAL": "Legal",
    "EXEC": "Executive",
    "UNKNOWN": "Unknown",
}

DEPT_COLORS: dict[str, str] = {
    "ENG": "#008080",
    "RES": "#800080",
    "PROD": "#000080",
    "DES": "#FF6347",
    "DATA": "#808000",
    "INFRA": "#2F4F4F",
    "SEC": "#8B0000",
    "SALES": "#DAA520",
    "MKT": "#FF4500",
    "CS": "#4682B4",
    "OPS": "#556B2F",
    "PPL": "#CD853F",
    "FIN": "#006400",
    "LEGAL": "#483D8B",
    "EXEC": "#8B4513",
    "UNKNOWN": "#808080",
}

COMPANY_COLORS: dict[str, str] = {
    "anthropic": "#D4A574",
    "openai": "#74AA9C",
    "xai": "#1DA1F2",
    "cursor": "#7C3AED",
    "cognition": "#F59E0B",
}


async def _get_db() -> AsyncGenerator[JobWatchDB, None]:
    db: JobWatchDB = JobWatchDB(_DB_PATH)
    try:
        yield db
    finally:
        db.close()


def _company_lookup() -> dict[str, CompanyConfig]:
    return {c.id: c for c in COMPANY_REGISTRY}


def _trend_indicator(snapshots: list[dict]) -> str:
    """Return arrow character based on last two snapshots."""
    if len(snapshots) < 2:
        return "→"
    prev: int = snapshots[-2]["total_active"]
    curr: int = snapshots[-1]["total_active"]
    if curr > prev:
        return "↑"
    elif curr < prev:
        return "↓"
    return "→"


# ------------------------------------------------------------------
# Page routes
# ------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def overview(request: Request, db: JobWatchDB = Depends(_get_db)) -> HTMLResponse:
    """Overview page — total open roles per company, recent trends."""
    company_cards: list[dict] = []

    for company in COMPANY_REGISTRY:
        dept_mix: list[dict] = db.get_department_mix(company.id)
        total: int = sum(row["count"] for row in dept_mix)
        top_depts: list[dict] = dept_mix[:3]
        snapshots: list[dict] = db.get_snapshots(company.id)
        trend: str = _trend_indicator(snapshots)
        last_crawl: str | None = snapshots[-1]["crawl_date"] if snapshots else None

        company_cards.append({
            "id": company.id,
            "name": company.name,
            "total": total,
            "top_depts": top_depts,
            "trend": trend,
            "last_crawl": last_crawl,
            "color": COMPANY_COLORS.get(company.id, "#808080"),
        })

    return templates.TemplateResponse("overview.html", {
        "request": request,
        "cards": company_cards,
        "dept_labels": DEPT_LABELS,
        "dept_colors": DEPT_COLORS,
    })


@app.get("/company/{company_id}", response_class=HTMLResponse)
async def company_detail(
    request: Request, company_id: str, db: JobWatchDB = Depends(_get_db)
) -> HTMLResponse:
    """Company deep-dive — department breakdown, seniority, recent postings."""
    companies: dict[str, CompanyConfig] = _company_lookup()
    company: CompanyConfig | None = companies.get(company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    dept_mix: list[dict] = db.get_department_mix(company_id)
    max_dept: int = dept_mix[0]["count"] if dept_mix else 1

    postings: list[dict] = db.get_all_active_postings_with_classifications(company_id)

    seniority_counts: dict[str, int] = defaultdict(int)
    for p in postings:
        sen: str = p.get("seniority") or "UNKNOWN"
        seniority_counts[sen] += 1
    seniority_list: list[dict] = sorted(
        [{"seniority": k, "count": v} for k, v in seniority_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
    max_sen: int = seniority_list[0]["count"] if seniority_list else 1

    return templates.TemplateResponse("company.html", {
        "request": request,
        "company": company,
        "dept_mix": dept_mix,
        "max_dept": max_dept,
        "seniority_list": seniority_list,
        "max_sen": max_sen,
        "postings": postings[:50],
        "dept_labels": DEPT_LABELS,
        "dept_colors": DEPT_COLORS,
        "company_color": COMPANY_COLORS.get(company_id, "#808080"),
    })


@app.get("/compare", response_class=HTMLResponse)
async def compare(request: Request, db: JobWatchDB = Depends(_get_db)) -> HTMLResponse:
    """Cross-company comparison."""
    company_data: list[dict] = []
    all_depts: set[str] = set()

    for company in COMPANY_REGISTRY:
        dept_mix: list[dict] = db.get_department_mix(company.id)
        dept_map: dict[str, int] = {row["department"]: row["count"] for row in dept_mix}
        all_depts.update(dept_map.keys())
        total: int = sum(dept_map.values())

        role_counts: list[dict] = db.get_role_type_counts(company_id=company.id)
        eng_roles: int = sum(
            r["count"] for r in role_counts if r["role_type"].startswith("ENG.")
        )
        res_roles: int = sum(
            r["count"] for r in role_counts if r["role_type"].startswith("RES.")
        )
        ml_roles: int = sum(
            r["count"] for r in role_counts if r["role_type"] == "ENG.ML"
        )

        company_data.append({
            "id": company.id,
            "name": company.name,
            "dept_map": dept_map,
            "total": total,
            "eng": eng_roles,
            "res": res_roles,
            "ml": ml_roles,
            "color": COMPANY_COLORS.get(company.id, "#808080"),
        })

    global_max: int = max(
        (max(c["dept_map"].values()) for c in company_data if c["dept_map"]),
        default=1,
    )

    return templates.TemplateResponse("compare.html", {
        "request": request,
        "company_data": company_data,
        "all_depts": sorted(all_depts),
        "global_max": global_max,
        "dept_labels": DEPT_LABELS,
        "dept_colors": DEPT_COLORS,
    })


@app.get("/trends", response_class=HTMLResponse)
async def trends(request: Request, db: JobWatchDB = Depends(_get_db)) -> HTMLResponse:
    """Trend lines over time."""
    company_trends: list[dict] = []

    for company in COMPANY_REGISTRY:
        snapshots: list[dict] = db.get_snapshots(company.id)
        sparkline: str = _build_sparkline(snapshots)
        company_trends.append({
            "id": company.id,
            "name": company.name,
            "snapshots": snapshots,
            "sparkline": sparkline,
            "color": COMPANY_COLORS.get(company.id, "#808080"),
        })

    return templates.TemplateResponse("trends.html", {
        "request": request,
        "company_trends": company_trends,
    })


def _build_sparkline(snapshots: list[dict]) -> str:
    """Build an ASCII sparkline from snapshot total_active values."""
    if not snapshots:
        return ""
    values: list[int] = [s["total_active"] for s in snapshots]
    min_v: int = min(values)
    max_v: int = max(values)
    span: int = max_v - min_v if max_v != min_v else 1
    blocks: str = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min(int((v - min_v) / span * 7), 7)] for v in values)


@app.get("/heatmap", response_class=HTMLResponse)
async def heatmap(request: Request, db: JobWatchDB = Depends(_get_db)) -> HTMLResponse:
    """Company x department heatmap."""
    all_depts: set[str] = set()
    company_dept_counts: list[dict] = []
    global_max: int = 1

    for company in COMPANY_REGISTRY:
        dept_mix: list[dict] = db.get_department_mix(company.id)
        dept_map: dict[str, int] = {row["department"]: row["count"] for row in dept_mix}
        all_depts.update(dept_map.keys())
        if dept_map:
            local_max: int = max(dept_map.values())
            if local_max > global_max:
                global_max = local_max
        company_dept_counts.append({
            "id": company.id,
            "name": company.name,
            "dept_map": dept_map,
        })

    sorted_depts: list[str] = sorted(all_depts)

    return templates.TemplateResponse("heatmap.html", {
        "request": request,
        "companies": company_dept_counts,
        "departments": sorted_depts,
        "global_max": global_max,
        "dept_labels": DEPT_LABELS,
        "dept_colors": DEPT_COLORS,
    })


@app.get("/health", response_class=HTMLResponse)
async def health(request: Request, db: JobWatchDB = Depends(_get_db)) -> HTMLResponse:
    """Crawl health — recent runs and status."""
    runs: list[dict] = db.get_recent_crawl_runs(limit=30)
    companies: dict[str, CompanyConfig] = _company_lookup()
    return templates.TemplateResponse("health.html", {
        "request": request,
        "runs": runs,
        "companies": companies,
    })


# ------------------------------------------------------------------
# API partials (HTMX)
# ------------------------------------------------------------------


@app.get("/api/dept-mix/{company_id}", response_class=HTMLResponse)
async def api_dept_mix(
    request: Request, company_id: str, db: JobWatchDB = Depends(_get_db)
) -> HTMLResponse:
    """HTMX partial: department breakdown bars."""
    dept_mix: list[dict] = db.get_department_mix(company_id)
    max_count: int = dept_mix[0]["count"] if dept_mix else 1
    return templates.TemplateResponse("partials/dept_mix.html", {
        "request": request,
        "dept_mix": dept_mix,
        "max_count": max_count,
        "dept_labels": DEPT_LABELS,
        "dept_colors": DEPT_COLORS,
    })


@app.get("/api/trend-data/{company_id}", response_class=HTMLResponse)
async def api_trend_data(
    request: Request, company_id: str, db: JobWatchDB = Depends(_get_db)
) -> HTMLResponse:
    """HTMX partial: trend data table."""
    snapshots: list[dict] = db.get_snapshots(company_id)
    return templates.TemplateResponse("partials/trend_data.html", {
        "request": request,
        "snapshots": snapshots,
    })


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def main():
    import uvicorn

    uvicorn.run("dashboard.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
