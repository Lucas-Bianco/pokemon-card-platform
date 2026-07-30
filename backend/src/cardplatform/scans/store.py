"""Persists recognition attempts so accuracy can be measured on real photographs.

Everything measured so far used degraded reference images. This store is how the
project finally learns what happens with a phone camera pointed at a physical card.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardplatform.config import Settings
from cardplatform.config import settings as default_settings
from cardplatform.db.models import Card, ScanLog


@dataclass(frozen=True)
class ScanAccuracy:
    """Precision and coverage, reported separately and deliberately.

    A blended "accuracy" counts a declined `ambiguous` result as a wrong answer, which
    conflates refusing to guess with guessing wrong. Measured over 99 real scans, that
    blend read 74.4% for a pipeline that was right 29 out of 29 when it committed —
    and hid the real finding, which was that detection was failing, not recognition.

    precision = of the predictions a human checked, how many were right
    coverage  = of all scans, how many produced any answer at all
    """

    total: int
    answered: int
    predicted: int
    correct: int
    precision: float
    coverage: float
    by_status: dict[str, int]


class ScanStore:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or default_settings
        self.directory = self.settings.scan_image_dir
        self.directory.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        image_bytes: bytes,
        status: str,
        predicted_card_id: str | None = None,
        confidence: float | None = None,
        visual_margin: float | None = None,
        collector_number_read: str | None = None,
    ) -> ScanLog:
        # uuid rather than a counter: two scans in the same second must not collide,
        # and the filename should not depend on database state.
        name = f"{uuid.uuid4().hex}.png"
        (self.directory / name).write_bytes(image_bytes)

        scan = ScanLog(
            image_path=f"scans/{name}",
            predicted_card_id=predicted_card_id,
            status=status,
            confidence=confidence,
            visual_margin=visual_margin,
            collector_number_read=collector_number_read,
        )
        self.session.add(scan)
        self.session.commit()
        return scan

    def get(self, scan_id: int) -> ScanLog | None:
        return self.session.get(ScanLog, scan_id)

    def confirm(self, scan_id: int) -> ScanLog | None:
        scan = self.get(scan_id)
        if scan is None:
            return None
        scan.confirmed = True
        self.session.commit()
        return scan

    def correct(self, scan_id: int, card_id: str) -> ScanLog | None:
        scan = self.get(scan_id)
        if scan is None:
            return None
        if self.session.get(Card, card_id) is None:
            raise ValueError(f"unknown card: {card_id}")
        scan.corrected_card_id = card_id
        scan.confirmed = True
        self.session.commit()
        return scan

    def recent(self, limit: int = 50) -> list[ScanLog]:
        return list(
            self.session.scalars(
                select(ScanLog).order_by(ScanLog.created_at.desc(), ScanLog.id.desc()).limit(limit)
            ).all()
        )

    def accuracy(self) -> ScanAccuracy:
        rows = list(self.session.scalars(select(ScanLog)).all())
        by_status: dict[str, int] = {}
        for row in rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1

        answered = [r for r in rows if r.predicted_card_id is not None]
        # Only reviewed predictions are evidence; an unreviewed one is neither.
        predicted = [r for r in answered if r.confirmed]
        correct = [r for r in predicted if r.corrected_card_id is None]

        return ScanAccuracy(
            total=len(rows),
            answered=len(answered),
            predicted=len(predicted),
            correct=len(correct),
            precision=len(correct) / len(predicted) if predicted else 0.0,
            coverage=len(answered) / len(rows) if rows else 0.0,
            by_status=by_status,
        )
