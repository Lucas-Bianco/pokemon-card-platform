"""Records known third-party grades against scans — the honest source of truth.

Every other "graded card" datum in this project comes from degraded reference
images. A label here is what a user actually received back from PSA/CGC/BGS for a
real photograph they took, which is the only signal a future grade predictor can
learn from without lying to itself. One label per scan: a card has one grade,
and re-submitting the same scan to a grader is not a new grade, it is a
correction of the same verdict.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.config import Settings
from cardplatform.config import settings as default_settings
from cardplatform.db.models import GradingLabel, ScanLog

# The graders we track. Uppercased on input so a caller typing "psa" still
# stores "PSA" — the catalog of graded prices (T4) keys on these exact strings.
_GRADERS = ("PSA", "CGC", "BGS")

# PSA grades whole numbers 1-10; BGS/CGC allow .5 increments in the same range.
# Anything outside is a client mistake, not a server fault.
_MIN_GRADE = 1.0
_MAX_GRADE = 10.0


class GradingLabelStore:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or default_settings

    def label(
        self,
        scan_id: int,
        grade: float,
        grader: str,
        cert_number: str | None = None,
        notes: str | None = None,
    ) -> GradingLabel | None:
        """Attach (or update) the grade for one scan. None if the scan does not exist.

        card_id is resolved honestly from the scan, never fabricated: a user
        correction wins over the pipeline's prediction, and a scan that named no
        card at all cannot be labeled — you cannot grade a card you never
        identified. variant likewise comes from the scan (the user's pick on the
        rectified crop); we never invent one.

        Upserts on the unique scan_id: re-labeling a scan updates the existing row
        in place rather than inserting a second one, so one scan always yields one
        label. `created_at` is left untouched on update — it records when the
        label was first entered, not when it was last corrected.
        """
        scan = self.session.get(ScanLog, scan_id)
        if scan is None:
            return None

        card_id = scan.corrected_card_id or scan.predicted_card_id
        if card_id is None:
            # A not_found scan with no correction has no card to grade. This is an
            # honest constraint, not a validation detail: fabricating a card_id
            # here would poison the training set the predictor is meant to learn
            # from.
            raise ValueError("cannot label a scan with no card")

        # variant is whatever the user picked when scanning; None is a real value
        # (a scan that never chose one) and must NOT be defaulted to "normal".
        variant = scan.variant

        grader = grader.upper()
        if grader not in _GRADERS:
            raise ValueError(f"unknown grader: {grader!r}; expected one of {_GRADERS}")
        if not (_MIN_GRADE <= grade <= _MAX_GRADE):
            raise ValueError(
                f"grade {grade} out of range; must be within [{_MIN_GRADE}, {_MAX_GRADE}]"
            )

        existing = self._row_for_scan(scan_id)
        if existing is not None:
            # Update in place; do not stamp created_at.
            existing.card_id = card_id
            existing.variant = variant
            existing.grade = grade
            existing.grader = grader
            existing.cert_number = cert_number
            existing.notes = notes
            self.session.commit()
            return existing

        row = GradingLabel(
            scan_id=scan_id,
            card_id=card_id,
            variant=variant,
            grade=grade,
            grader=grader,
            cert_number=cert_number,
            notes=notes,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def for_scan(self, scan_id: int) -> GradingLabel | None:
        """The label attached to a scan, or None if there is none yet."""
        return self._row_for_scan(scan_id)

    def list_labels(
        self,
        card_id: str | None = None,
        grader: str | None = None,
    ) -> list[GradingLabel]:
        """Labels, newest first by created_at. Both filters optional.

        `grader` matches case-insensitively via func.lower()==, the project's
        idiom for case-insensitive equality (never ilike, which is a substring
        operator disguised as equality and would match "PSAX" for "psa").
        """
        stmt = select(GradingLabel).order_by(
            GradingLabel.created_at.desc(), GradingLabel.id.desc()
        )
        if card_id is not None:
            stmt = stmt.where(GradingLabel.card_id == card_id)
        if grader is not None:
            stmt = stmt.where(func.lower(GradingLabel.grader) == grader.lower())
        return list(self.session.scalars(stmt).all())

    def _row_for_scan(self, scan_id: int) -> GradingLabel | None:
        return self.session.scalar(
            select(GradingLabel).where(GradingLabel.scan_id == scan_id)
        )