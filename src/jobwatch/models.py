"""Pydantic models and enums for JobWatch."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Department(StrEnum):
    ENG = "ENG"
    RES = "RES"
    PROD = "PROD"
    DES = "DES"
    DATA = "DATA"
    INFRA = "INFRA"
    SEC = "SEC"
    SALES = "SALES"
    MKT = "MKT"
    CS = "CS"
    OPS = "OPS"
    PPL = "PPL"
    FIN = "FIN"
    LEGAL = "LEGAL"
    EXEC = "EXEC"
    UNKNOWN = "UNKNOWN"


class RoleType(StrEnum):
    # Engineering subcategories
    ENG_FE = "ENG.FE"
    ENG_BE = "ENG.BE"
    ENG_FS = "ENG.FS"
    ENG_ML = "ENG.ML"
    ENG_PLAT = "ENG.PLAT"
    ENG_SRE = "ENG.SRE"
    ENG_MOB = "ENG.MOB"
    ENG_DATA = "ENG.DATA"
    ENG_SEC = "ENG.SEC"
    ENG_EMBEDDED = "ENG.EMBEDDED"
    ENG_QA = "ENG.QA"
    ENG_FDE = "ENG.FDE"
    ENG_GEN = "ENG.GEN"
    # Generic for all other departments
    RES_GEN = "RES.GEN"
    PROD_GEN = "PROD.GEN"
    DES_GEN = "DES.GEN"
    DATA_GEN = "DATA.GEN"
    INFRA_GEN = "INFRA.GEN"
    SEC_GEN = "SEC.GEN"
    SALES_GEN = "SALES.GEN"
    MKT_GEN = "MKT.GEN"
    CS_GEN = "CS.GEN"
    OPS_GEN = "OPS.GEN"
    PPL_GEN = "PPL.GEN"
    FIN_GEN = "FIN.GEN"
    LEGAL_GEN = "LEGAL.GEN"
    EXEC_GEN = "EXEC.GEN"
    UNKNOWN_GEN = "UNKNOWN.GEN"


class Seniority(StrEnum):
    INTERN = "INTERN"
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    STAFF = "STAFF"
    LEAD = "LEAD"
    DIRECTOR = "DIRECTOR"
    VP = "VP"
    C_LEVEL = "C_LEVEL"
    UNKNOWN = "UNKNOWN"


class ATSType(StrEnum):
    GREENHOUSE = "greenhouse"
    ASHBY = "ashby"
    ASHBY_SSR = "ashby_ssr"


class CrawlStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class ReclassifyTrigger(StrEnum):
    NEW_POSTING = "new_posting"
    CONTENT_CHANGE = "content_change"
    TAXONOMY_UPDATE = "taxonomy_update"
    MANUAL_RECLASSIFY = "manual_reclassify"


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERN = "intern"


class RawPosting(BaseModel):
    """Normalized posting returned by ATS clients."""

    ats_job_id: str
    title: str
    department_raw: str | None = None
    location: str | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    description: str | None = None
    url: str | None = None


class FetchResult(BaseModel):
    """Result from an ATS client fetch."""

    postings: list[RawPosting]
    is_exhaustive: bool
    response_hash: str


class JobClassification(BaseModel):
    """LLM classification output."""

    justification: str
    department: str
    role_type: str
    seniority: str
    confidence: float = Field(ge=0.0, le=1.0)


TAXONOMY_VERSION: str = "v1"
PROMPT_VERSION: str = "v1"
