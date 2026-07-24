"""Focused tests for valuation calculations."""

import pytest

from minerva.valuation import run_implied_return


def _value_for_return(
    cash_distributions: list[float],
    equity_return: float,
    terminal_growth: float,
) -> float:
    years: int = len(cash_distributions)
    explicit_value: float = sum(
        distribution / (1 + equity_return) ** year
        for year, distribution in enumerate(cash_distributions, start=1)
    )
    terminal_value: float = (
        cash_distributions[-1]
        * (1 + terminal_growth)
        / (equity_return - terminal_growth)
        / (1 + equity_return) ** years
    )
    return explicit_value + terminal_value


def test_run_implied_return_solves_known_return_and_equity_risk_premium() -> None:
    cash_distributions = [4.0, 5.0, 6.0]
    expected_return: float = 0.25
    terminal_growth: float = 0.03
    current_value: float = _value_for_return(
        cash_distributions,
        expected_return,
        terminal_growth,
    )

    result = run_implied_return(
        current_value=current_value,
        cash_distributions=cash_distributions,
        terminal_growth=terminal_growth,
        risk_free_rate=0.04,
    )

    assert result.current_value == current_value
    assert result.implied_return == pytest.approx(expected_return, abs=1e-10)
    assert result.equity_risk_premium == pytest.approx(0.21, abs=1e-10)
    assert result.implied_return > terminal_growth


def test_run_implied_return_rejects_negative_cash_distribution() -> None:
    with pytest.raises(ValueError, match="cash_distributions must be non-negative"):
        run_implied_return(
            current_value=100.0,
            cash_distributions=[5.0, -1.0, 6.0],
            terminal_growth=0.03,
        )


def test_run_implied_return_reports_no_solution_above_terminal_growth() -> None:
    with pytest.raises(ValueError, match="no implied return greater than terminal_growth"):
        run_implied_return(
            current_value=20.0,
            cash_distributions=[10.0, 0.0],
            terminal_growth=0.03,
        )
