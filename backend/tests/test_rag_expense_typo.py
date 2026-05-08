"""Expense-ratio intent detection (typos)."""

from __future__ import annotations

from app.agents.rag_agent import expense_ratio_requested


def test_expense_ration_typo() -> None:
    assert expense_ratio_requested("expense ration of SBI Nifty Index")


def test_expence_misspelling() -> None:
    assert expense_ratio_requested("expence ratio of HDFC Flexi Cap")


def test_expense_ratios_plural() -> None:
    assert expense_ratio_requested("compare expense ratios for small caps")
