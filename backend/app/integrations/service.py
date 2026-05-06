"""Integration service with mock/live adapters and graceful fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import (
    get_google_calendar_id,
    get_google_integrations_mode,
    get_google_sheet_id,
)
from app.db.models import Booking


def _calendar_event_summary(booking: Booking) -> str:
    if (booking.status or "").lower() == "waitlisted":
        return f"WAITLIST — {booking.advisor} — {booking.topic} — {booking.booking_code}"
    return f"Advisor Q&A - {booking.advisor} - {booking.topic} - {booking.booking_code}"


@dataclass
class SyncResult:
    ok: bool
    reference: str | None = None
    detail: str = ""


class CalendarPort(Protocol):
    def create_tentative_hold(self, booking: Booking) -> SyncResult: ...
    def cancel_hold(self, booking: Booking) -> SyncResult: ...


class SheetsPort(Protocol):
    def upsert_booking_row(self, booking: Booking) -> SyncResult: ...


class GmailPort(Protocol):
    def queue_advisor_draft(self, booking: Booking) -> SyncResult: ...


class MockCalendarAdapter:
    def create_tentative_hold(self, booking: Booking) -> SyncResult:
        prefix = "mock-waitlist" if (booking.status or "").lower() == "waitlisted" else "mock-cal"
        ref = f"{prefix}-{booking.booking_code}"
        return SyncResult(ok=True, reference=ref, detail="mock calendar hold created")

    def cancel_hold(self, booking: Booking) -> SyncResult:
        return SyncResult(ok=True, reference=booking.calendar_event_id, detail="mock calendar hold cancelled")


class MockSheetsAdapter:
    def upsert_booking_row(self, booking: Booking) -> SyncResult:
        return SyncResult(ok=True, reference=f"row-{booking.booking_code}", detail="mock sheet upserted")


class MockGmailAdapter:
    def queue_advisor_draft(self, booking: Booking) -> SyncResult:
        return SyncResult(ok=True, reference=f"draft-{booking.booking_code}", detail="mock email draft queued")


class LiveGoogleCalendarAdapter:
    """Best-effort direct Google API adapter (falls back gracefully)."""

    def __init__(self, calendar_id: str) -> None:
        self.calendar_id = calendar_id

    def _service(self):
        from google.oauth2 import service_account  # type: ignore[import-not-found]
        from googleapiclient.discovery import build  # type: ignore[import-not-found]

        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")
        if raw:
            import base64

            parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
            creds = service_account.Credentials.from_service_account_info(
                parsed, scopes=["https://www.googleapis.com/auth/calendar"]
            )
            return build("calendar", "v3", credentials=creds, cache_discovery=False)

        path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not path:
            raise RuntimeError("Google credentials not configured")
        creds = service_account.Credentials.from_service_account_file(
            path, scopes=["https://www.googleapis.com/auth/calendar"]
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    def create_tentative_hold(self, booking: Booking) -> SyncResult:
        try:
            svc = self._service()
            # Keep event simple for phase delivery reliability.
            event = {
                "summary": _calendar_event_summary(booking),
                "description": f"Auto-created tentative hold for {booking.customer_name}",
                "start": {"dateTime": f"{booking.date}T10:00:00+05:30"},
                "end": {"dateTime": f"{booking.date}T10:30:00+05:30"},
            }
            res = (
                svc.events()
                .insert(calendarId=self.calendar_id, body=event)
                .execute()
            )
            return SyncResult(ok=True, reference=res.get("id"), detail="calendar event created")
        except Exception as exc:  # noqa: BLE001
            return SyncResult(ok=False, detail=f"calendar sync failed: {exc}")

    def cancel_hold(self, booking: Booking) -> SyncResult:
        if not booking.calendar_event_id:
            return SyncResult(ok=False, detail="missing calendar_event_id")
        try:
            svc = self._service()
            svc.events().delete(
                calendarId=self.calendar_id, eventId=booking.calendar_event_id
            ).execute()
            return SyncResult(ok=True, reference=booking.calendar_event_id, detail="calendar event deleted")
        except Exception as exc:  # noqa: BLE001
            return SyncResult(ok=False, detail=f"calendar cancel failed: {exc}")


class LiveSheetsAdapter:
    def __init__(self, sheet_id: str) -> None:
        self.sheet_id = sheet_id

    def upsert_booking_row(self, booking: Booking) -> SyncResult:
        # Keep this intentionally minimal and robust for Phase 6.
        try:
            from google.oauth2 import service_account  # type: ignore[import-not-found]
            from googleapiclient.discovery import build  # type: ignore[import-not-found]

            raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_BASE64")
            if raw:
                import base64

                parsed = json.loads(base64.b64decode(raw).decode("utf-8"))
                creds = service_account.Credentials.from_service_account_info(
                    parsed, scopes=["https://www.googleapis.com/auth/spreadsheets"]
                )
            else:
                path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                if not path:
                    raise RuntimeError("Google credentials not configured")
                creds = service_account.Credentials.from_service_account_file(
                    path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
                )

            svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
            row = [
                booking.booking_code,
                booking.customer_name,
                booking.topic,
                booking.date,
                booking.time_ist,
                booking.advisor,
                booking.status,
                datetime.utcnow().isoformat(timespec="seconds"),
                f"/secure/{booking.booking_code}",
                booking.email_status,
                "",
                "",
            ]
            # Prefer explicit tab range; fallback to plain A:L for existing sheets.
            preferred_range = os.getenv("GOOGLE_SHEET_RANGE", "Bookings!A:L").strip() or "Bookings!A:L"
            try:
                svc.spreadsheets().values().append(
                    spreadsheetId=self.sheet_id,
                    range=preferred_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": [row]},
                ).execute()
            except Exception:
                svc.spreadsheets().values().append(
                    spreadsheetId=self.sheet_id,
                    range="A:L",
                    valueInputOption="USER_ENTERED",
                    body={"values": [row]},
                ).execute()
            return SyncResult(ok=True, reference=f"row-{booking.booking_code}", detail="sheet append success")
        except Exception as exc:  # noqa: BLE001
            return SyncResult(ok=False, detail=f"sheet sync failed: {exc}")


def _smtp_send(*, to_email: str, subject: str, body: str) -> SyncResult:
    host = (os.getenv("GMAIL_SMTP_HOST", "smtp.gmail.com") or "").strip()
    port_raw = (os.getenv("GMAIL_SMTP_PORT", "587") or "").strip()
    user = (os.getenv("GMAIL_SMTP_USER") or "").strip()
    app_password = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
    if not host or not port_raw or not user or not app_password:
        return SyncResult(ok=False, detail="smtp not configured (set GMAIL_SMTP_USER and GMAIL_APP_PASSWORD)")
    try:
        port = int(port_raw)
    except ValueError:
        return SyncResult(ok=False, detail=f"invalid GMAIL_SMTP_PORT: {port_raw}")
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, app_password)
            server.send_message(msg)
        return SyncResult(ok=True, reference=to_email, detail="smtp send success")
    except Exception as exc:  # noqa: BLE001
        return SyncResult(ok=False, detail=f"smtp send failed: {exc}")


class LiveGmailAdapter:
    def queue_advisor_draft(self, booking: Booking) -> SyncResult:
        # Keep queue operation for booking-time flow; actual send happens in admin endpoint.
        return SyncResult(ok=True, reference=f"draft-{booking.booking_code}", detail="draft queued for HITL")


class ErrorCalendarAdapter:
    def __init__(self, detail: str) -> None:
        self.detail = detail

    def create_tentative_hold(self, booking: Booking) -> SyncResult:
        return SyncResult(ok=False, detail=self.detail)

    def cancel_hold(self, booking: Booking) -> SyncResult:
        return SyncResult(ok=False, detail=self.detail)


class ErrorSheetsAdapter:
    def __init__(self, detail: str) -> None:
        self.detail = detail

    def upsert_booking_row(self, booking: Booking) -> SyncResult:
        return SyncResult(ok=False, detail=self.detail)


def build_integration_service() -> tuple[CalendarPort, SheetsPort, GmailPort]:
    mode = get_google_integrations_mode()
    if mode == "live":
        calendar_id = get_google_calendar_id()
        sheet_id = get_google_sheet_id()
        cal: CalendarPort = (
            LiveGoogleCalendarAdapter(calendar_id)
            if calendar_id
            else ErrorCalendarAdapter("missing GOOGLE_CALENDAR_ID in live mode")
        )
        sheets: SheetsPort = (
            LiveSheetsAdapter(sheet_id)
            if sheet_id
            else ErrorSheetsAdapter("missing GOOGLE_SHEET_ID in live mode")
        )
        return (
            cal,
            sheets,
            LiveGmailAdapter(),
        )
    return MockCalendarAdapter(), MockSheetsAdapter(), MockGmailAdapter()


def sync_booking_created(booking: Booking) -> dict:
    cal, sheets, mail = build_integration_service()
    c = cal.create_tentative_hold(booking)
    s = sheets.upsert_booking_row(booking)
    m = mail.queue_advisor_draft(booking)
    return {
        "calendar": c.__dict__,
        "sheets": s.__dict__,
        "email_draft": m.__dict__,
    }


def sync_booking_cancelled(booking: Booking) -> dict:
    cal, sheets, _mail = build_integration_service()
    c = cal.cancel_hold(booking)
    s = sheets.upsert_booking_row(booking)
    return {"calendar": c.__dict__, "sheets": s.__dict__}


def send_booking_email_smtp(*, to_email: str, subject: str, body: str) -> SyncResult:
    return _smtp_send(to_email=to_email, subject=subject, body=body)


def send_pulse_email_smtp(*, to_email: str, subject: str, body: str) -> SyncResult:
    return _smtp_send(to_email=to_email, subject=subject, body=body)
