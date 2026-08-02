"""T4: NotificationService — in-app + web push + email delivery for AlertEvents.

Mirrors test_alert_engine.py: a temp SQLite session (the `db` fixture), real
AlertEvent + PushSubscription rows (not fakes) so the prune path exercises the
DB, and a SimpleNamespace `settings` injected via the constructor so tests
don't depend on ambient env. `pywebpush.webpush` and `smtplib.SMTP` are
monkeypatched so nothing touches the network.

Email is sent SYNCHRONOUSLY (no thread pool). Threading is premature for a
single-user local-first app and would make delivery flags non-deterministic
in tests; a thread pool can be layered on later if a tick ever needs to fan out
to many SMTP recipients (YAGNI for now). See notify.py for the matching note.
"""

from __future__ import annotations

import smtplib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cardplatform.alerts.notify import NotificationService
from cardplatform.db.models import AlertEvent, PushSubscription
from pywebpush import WebPushException


def _settings(**kw):
    """Build a settings stub with every NotificationService field defaulted off."""
    base = dict(
        vapid_public_key=None,
        vapid_private_key=None,
        vapid_subject=None,
        smtp_host=None,
        smtp_port=587,
        smtp_user=None,
        smtp_password=None,
        smtp_from=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _event(db, **kw) -> AlertEvent:
    """Insert a real AlertEvent row, commit, and return it (mirrors the engine,
    which creates+flushes the row before calling dispatch)."""
    defaults = dict(
        alert_type="price_target",
        message="Charizard: price hit target $38.00 <= $40.00",
        context=None,
        delivered_inapp=True,
        delivered_push=False,
        delivered_email=False,
    )
    defaults.update(kw)
    e = AlertEvent(**defaults)
    db.add(e)
    db.commit()
    return e


def _sub(db, **kw) -> PushSubscription:
    """Insert a real PushSubscription row, commit, and return it."""
    defaults = dict(
        endpoint="https://fcm.googleapis.com/fcm/send/abc123",
        p256dh="p256dh-key-material",
        auth="auth-key-material",
    )
    defaults.update(kw)
    s = PushSubscription(**defaults)
    db.add(s)
    db.commit()
    return s


# ---------------------------------------------------------- in-app default

def test_in_app_always(db):
    """No vapid, no smtp -> in-app stays True (engine already set it), push and
    email stay False, no raise."""
    event = _event(db)
    svc = NotificationService(db, settings=_settings())

    svc.dispatch(event)

    assert event.delivered_inapp is True
    assert event.delivered_push is False
    assert event.delivered_email is False


# ------------------------------------------------------------------- push

def test_push_when_vapid_and_subscription(db, monkeypatch):
    """Vapid keys set + 1 subscription + webpush succeeds -> delivered_push True."""
    called = []
    monkeypatch.setattr(
        "cardplatform.alerts.notify.webpush",
        lambda **kw: called.append(kw) or MagicMock(status_code=201),
    )
    event = _event(db)
    _sub(db)
    svc = NotificationService(
        db, settings=_settings(vapid_public_key="Bpub", vapid_private_key="priv")
    )

    svc.dispatch(event)

    assert event.delivered_push is True
    assert len(called) == 1
    # The subscription_info passed to webpush carries the row's key material.
    info = called[0]["subscription_info"]
    assert info["endpoint"] == "https://fcm.googleapis.com/fcm/send/abc123"
    assert info["keys"]["p256dh"] == "p256dh-key-material"
    assert info["keys"]["auth"] == "auth-key-material"


def test_push_skipped_without_vapid(db, monkeypatch):
    """No vapid keys + 1 subscription -> push skipped, webpush NOT called."""
    called = []
    monkeypatch.setattr(
        "cardplatform.alerts.notify.webpush", lambda **kw: called.append(kw)
    )
    event = _event(db)
    _sub(db)
    svc = NotificationService(db, settings=_settings())

    svc.dispatch(event)

    assert event.delivered_push is False
    assert called == []


def test_push_skipped_without_subscriptions(db, monkeypatch):
    """Vapid set + 0 subscriptions -> push skipped, webpush NOT called, no raise."""
    called = []
    monkeypatch.setattr(
        "cardplatform.alerts.notify.webpush", lambda **kw: called.append(kw)
    )
    event = _event(db)
    svc = NotificationService(
        db, settings=_settings(vapid_public_key="Bpub", vapid_private_key="priv")
    )

    svc.dispatch(event)

    assert event.delivered_push is False
    assert called == []


def test_push_prunes_410(db, monkeypatch):
    """The only subscription returns 410 Gone -> it is DELETED from the DB,
    delivered_push stays False (no successful send), no raise."""
    def boom(**kw):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr("cardplatform.alerts.notify.webpush", boom)
    event = _event(db)
    _sub(db)
    svc = NotificationService(
        db, settings=_settings(vapid_public_key="Bpub", vapid_private_key="priv")
    )

    svc.dispatch(event)
    db.commit()  # persist the prune (dispatch does not commit; the engine does)

    assert event.delivered_push is False
    assert db.query(PushSubscription).count() == 0


# ------------------------------------------------------------------ email

def test_email_when_smtp(db, monkeypatch):
    """smtp_host + smtp_from set + SMTP monkeypatched -> delivered_email True."""
    smtp_instance = MagicMock()
    smtp_instance.sendmail.return_value = {}
    # `with smtplib.SMTP(...) as smtp:` binds smtp to __enter__.return_value;
    # make it return the same mock so sendmail is observable on it.
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_cls = MagicMock(return_value=smtp_instance)
    monkeypatch.setattr("cardplatform.alerts.notify.smtplib.SMTP", smtp_cls)

    event = _event(db)
    svc = NotificationService(
        db,
        settings=_settings(
            smtp_host="smtp.example.com", smtp_port=587, smtp_from="me@example.com"
        ),
    )

    svc.dispatch(event)

    assert event.delivered_email is True
    smtp_cls.assert_called_once_with("smtp.example.com", 587)
    # Self-loop: single-user app sends from smtp_from TO smtp_from.
    smtp_instance.sendmail.assert_called_once()
    from_addr, to_addrs, _msg = smtp_instance.sendmail.call_args.args
    assert from_addr == "me@example.com"
    assert to_addrs == ["me@example.com"]


def test_email_skipped_without_smtp(db, monkeypatch):
    """No smtp_host -> email skipped, smtplib.SMTP NOT called."""
    smtp_cls = MagicMock()
    monkeypatch.setattr("cardplatform.alerts.notify.smtplib.SMTP", smtp_cls)
    event = _event(db)
    svc = NotificationService(db, settings=_settings())

    svc.dispatch(event)

    assert event.delivered_email is False
    smtp_cls.assert_not_called()


# --------------------------------------------------------- robustness

def test_never_raises(db, monkeypatch):
    """Both push AND email paths raise -> dispatch returns None without raising;
    delivered_push and delivered_email both stay False."""
    def boom_push(**kw):
        raise WebPushException("server error", response=SimpleNamespace(status_code=500))

    monkeypatch.setattr("cardplatform.alerts.notify.webpush", boom_push)
    smtp_cls = MagicMock(side_effect=RuntimeError("smtp blew up"))
    monkeypatch.setattr("cardplatform.alerts.notify.smtplib.SMTP", smtp_cls)

    event = _event(db)
    _sub(db)
    svc = NotificationService(
        db,
        settings=_settings(
            vapid_public_key="Bpub",
            vapid_private_key="priv",
            smtp_host="smtp.example.com",
            smtp_from="me@example.com",
        ),
    )

    result = svc.dispatch(event)  # must NOT raise

    assert result is None
    assert event.delivered_push is False
    assert event.delivered_email is False
    assert event.delivered_inapp is True