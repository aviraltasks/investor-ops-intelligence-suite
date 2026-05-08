"""Tests for fund/metric-aware layer boosting in RAG vector search."""

from __future__ import annotations

from app.rag.search import fund_metric_layer_boost_applies


def test_boost_when_manifest_fund_mentioned() -> None:
    assert fund_metric_layer_boost_applies("expense ratio SBI Small Cap")


def test_boost_when_comparison_metric_without_pure_definition() -> None:
    assert fund_metric_layer_boost_applies("compare expense ratios small cap funds")


def test_no_boost_pure_nav_definition() -> None:
    assert not fund_metric_layer_boost_applies("What is NAV?")
    assert not fund_metric_layer_boost_applies("what is the expense ratio?")


def test_boost_nav_question_when_fund_named() -> None:
    assert fund_metric_layer_boost_applies("What is the NAV of Parag Parikh Flexi Cap?")


def test_no_boost_generic_topic() -> None:
    assert not fund_metric_layer_boost_applies("How do mutual funds work in India?")


def test_metric_keyword_alone_triggers_boost_when_not_pure_definition() -> None:
    assert fund_metric_layer_boost_applies("compare NAV across funds")

