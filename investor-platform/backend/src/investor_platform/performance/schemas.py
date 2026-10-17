"""Performance request choices and validation."""

from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from investor_platform.market_data import types as market_types


class Baseline(StrEnum):
    HISTORY = "history"
    RECORDED = "recorded"


class PerformanceScope(StrEnum):
    ACCOUNT = "account"
    STOCKS = "stocks"


class BenchmarkMode(StrEnum):
    BUY_HOLD = "buy_hold"
    MATCHED = "matched"
    FUNDED_HOLD = "funded_hold"


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date
    anchor_date: date | None = None
    scope: PerformanceScope = PerformanceScope.ACCOUNT
    benchmark_mode: BenchmarkMode = BenchmarkMode.BUY_HOLD
    baseline: Baseline = Baseline.HISTORY
    exclude_security_ids: list[UUID] = Field(
        default_factory=list, max_length=market_types.MAX_SECURITIES
    )
