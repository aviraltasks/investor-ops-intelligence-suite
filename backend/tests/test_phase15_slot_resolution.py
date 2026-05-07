"""Unit tests for centralized booking slot parsing and validation."""

from __future__ import annotations

from datetime import datetime

from app.scheduling.slot_resolution import message_looks_like_slot_refinement, resolve_booking_slot

# Friday 2026-05-08 11:00 local (tests assume same naive semantics as production)
_NOW_FRI = datetime(2026, 5, 8, 11, 0, 0)


def test_named_month_day_year_with_clock() -> None:
    slot, reason = resolve_booking_slot("9:00 AM 12 may 2026", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "ok"
    assert slot is not None
    assert slot[0] == "2026-05-12"
    assert slot[1].startswith("09:00")


def test_month_day_year_order_variants() -> None:
    slot, reason = resolve_booking_slot("may 15, 2026 3 pm", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "ok" and slot is not None
    assert slot[0] == "2026-05-15"


def test_iso_date() -> None:
    slot, reason = resolve_booking_slot("2026-05-11 10:30am", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "ok" and slot is not None
    assert slot[0] == "2026-05-11"


def test_tomorrow_rolls_weekend() -> None:
    slot, reason = resolve_booking_slot("tomorrow at 10 am", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "ok" and slot is not None
    assert slot[0] == "2026-05-11"


def test_weekend_explicit_rejected() -> None:
    _, reason = resolve_booking_slot("10 am 9 may 2026", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "weekend"


def test_too_far_future() -> None:
    _, reason = resolve_booking_slot("10 am 10 may 2028", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "too_far_future"


def test_outside_hours() -> None:
    _, reason = resolve_booking_slot("12 may 2026 8 am", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "outside_hours"


def test_message_looks_like_slot_refinement() -> None:
    assert message_looks_like_slot_refinement("9:00 AM 12 may 2026")
    assert message_looks_like_slot_refinement("tomorrow at 10am")
    assert not message_looks_like_slot_refinement("what is nav")


def test_past_calendar_day() -> None:
    _, reason = resolve_booking_slot("10 am 5 may 2026", now=_NOW_FRI, max_days_ahead=120)
    assert reason == "past_time"

