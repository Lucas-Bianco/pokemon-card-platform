"""Notification delivery for Phase 3c alerts.

`NotificationService.dispatch(event)` delivers one AlertEvent across every
configured channel. The engine creates the AlertEvent row (with
`delivered_inapp=True`) and flushes it BEFORE calling dispatch, so dispatch
only needs to set the push/email flags and prune dead subscriptions.

CRITICAL contract — dispatch() NEVER raises. A broken channel degrades: the
relevant `delivered_*` flag stays False, a warning is logged, and the next
channel still runs. The engine's per-watch SAVEPOINT already swallows
dispatch exceptions, but the notifier is robust on its own so a manual
test-call (outside an engine tick) is safe too.

Unconfigured channels are HONESTLY skipped, never faked as delivered: no
VAPID keys -> push is a no-op (delivered_push stays False); no smtp_host ->
email is a no-op (delivered_email stays False).

Email is sent SYNCHRONOUSLY (no thread pool). Threading is premature for a
single-user local-first app and would make delivery flags non-deterministic
in tests; a thread pool can be layered on later if a tick ever needs to fan
out to many SMTP recipients (YAGNI for now). Because email is synchronous, the
SMTP connection uses a bounded `timeout=10` so a hung server cannot block the
poll tick forever. Supported ports: 587 (STARTTLS, the default), 465
(SMTPS / implicit TLS via SMTP_SSL), and 25 (plaintext, no STARTTLS).

dispatch() does NOT commit — the engine commits once at the end of the tick.
Callers that invoke dispatch directly (e.g. tests, a manual fire) must commit
themselves. Pruned PushSubscription rows are deleted in-session and persisted
by the caller's commit.
"""

from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage

from pywebpush import WebPushException, webpush

from cardplatform.config import settings as default_settings
from cardplatform.db.models import AlertEvent, PushSubscription

log = logging.getLogger(__name__)


class NotificationService:
    """Delivers an AlertEvent across in-app / web push / email channels.

    All collaborators resolve from the injected session + settings, so tests
    inject a SimpleNamespace settings and monkeypatch the network calls.
    """

    def __init__(self, session, settings=None) -> None:
        self.session = session
        self.settings = settings or default_settings

    def dispatch(self, event: AlertEvent) -> None:
        """Deliver `event` across configured channels. NEVER raises."""
        try:
            # In-app: the engine already set delivered_inapp=True and flushed the
            # row. Defensively ensure the flag is True (the engine always does
            # this, but a manual/test caller might construct an event without
            # it). No re-insert — the row already exists.
            if not event.delivered_inapp:
                event.delivered_inapp = True

            self._send_push(event)
            self._send_email(event)
        except Exception:
            # Defense-in-depth: each channel has its own try/except, but an
            # unexpected error in one channel must NEVER propagate. The engine's
            # per-watch SAVEPOINT would catch a raise, but the notifier owns
            # this contract directly so standalone use is safe.
            log.warning("notifier dispatch failed unexpectedly", exc_info=True)

    # ----------------------------------------------------------------- push

    def _send_push(self, event: AlertEvent) -> None:
        """Web Push to every PushSubscription. Opt-in via VAPID keys; prunes 410/404."""
        s = self.settings
        if not (s.vapid_public_key and s.vapid_private_key):
            # Unconfigured channel: honestly skip (never fake delivered_push).
            return
        try:
            subs = self.session.query(PushSubscription).all()
        except Exception:
            log.warning("push subscription query failed", exc_info=True)
            return
        if not subs:
            return

        # Build the payload + VAPID claims in their own try/except so a failure
        # here (e.g. non-serializable context) logs and returns from _send_push
        # without preventing _send_email from running — true channel isolation.
        # Control jumps to dispatch's outer try/except only if the per-sub loop
        # itself raises unexpectedly.
        try:
            payload = json.dumps(
                {
                    "title": "Cardplatform alert",
                    "body": event.message,
                    # context is a JSON string (the engine stores ctx as json.dumps);
                    # surface it as the click-through target if present.
                    "url": event.context or "",
                }
            )
            vapid_claims = {
                "sub": s.vapid_subject or "mailto:noreply@example.com",
            }
        except Exception:
            log.warning("push payload/claims build failed for event id=%s", getattr(event, "id", None), exc_info=True)
            return
        any_success = False
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=payload,
                    vapid_private_key=s.vapid_private_key,
                    vapid_claims=vapid_claims,
                )
                any_success = True
            except WebPushException as exc:
                status = _push_status(exc)
                if status in (404, 410):
                    # Subscription expired / invalid: prune it so dead endpoints
                    # don't accumulate. session.delete is persisted by the
                    # caller's commit (the engine commits once per tick).
                    try:
                        self.session.delete(sub)
                        log.info("pruned expired push subscription id=%s (status=%s)", sub.id, status)
                    except Exception:
                        log.warning("failed to prune expired subscription id=%s", sub.id, exc_info=True)
                else:
                    log.warning("webpush failed for subscription id=%s (status=%s): %s", sub.id, status, exc)
            except Exception:
                log.warning("webpush failed for subscription id=%s", getattr(sub, "id", None), exc_info=True)
        if any_success:
            event.delivered_push = True

    # ---------------------------------------------------------------- email

    def _send_email(self, event: AlertEvent) -> None:
        """Plain-text alert email. Opt-in via smtp_host; sent to smtp_from (self-loop)."""
        s = self.settings
        if not s.smtp_host:
            return
        if not s.smtp_from:
            # Host configured but no sender address: skip honestly rather than
            # guess a from address. smtp_from doubles as the recipient.
            return
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[Cardplatform] {event.alert_type} alert"
            msg["From"] = s.smtp_from
            # Single-user local-first app: the owner gets their own alerts.
            # A per-watch recipient field is a follow-up (no per-user email in
            # the schema yet).
            msg["To"] = s.smtp_from
            msg.set_content(event.message)
            # Context appended if present so the email body is useful without
            # opening the app.
            if event.context:
                msg.set_content(f"{event.message}\n\nContext: {event.context}")

            # 465 = SMTPS (implicit TLS); 587 = STARTTLS; 25 = plaintext.
            # timeout=10 so a hung/unresponsive SMTP server cannot block the
            # synchronous send (and thus the poll tick) indefinitely.
            if s.smtp_port == 465:
                server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10)
                if s.smtp_port == 587:
                    server.starttls()
            with server as smtp:
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password or "")
                smtp.sendmail(s.smtp_from, [s.smtp_from], msg.as_string())
            event.delivered_email = True
        except Exception:
            log.warning("email send failed for alert event id=%s", getattr(event, "id", None), exc_info=True)


def _push_status(exc: WebPushException) -> int | None:
    """Extract the HTTP status code from a WebPushException, or None if absent.

    pywebpush attaches the `requests.Response` (or None) as `exc.response`; tests
    build the exception with a SimpleNamespace carrying `status_code`.
    """
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)