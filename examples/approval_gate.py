"""A minimal approval boundary for a draft-producing workflow.

The example deliberately stops before any real-world side effect. A caller can
prepare a draft, but only an explicit approval for that draft can make it ready
for execution by a separate, audited adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class DraftStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Draft:
    recipient: str
    body: str
    evidence: tuple[str, ...]
    id: str = field(default_factory=lambda: str(uuid4()))
    status: DraftStatus = DraftStatus.PENDING_REVIEW
    reviewer: str | None = None
    rejection_reason: str | None = None

    def approve(self, reviewer: str) -> None:
        if not reviewer.strip():
            raise ValueError("An identified reviewer is required.")
        if self.status is not DraftStatus.PENDING_REVIEW:
            raise ValueError("Only a pending draft can be approved.")
        self.status = DraftStatus.APPROVED
        self.reviewer = reviewer

    def reject(self, reviewer: str, reason: str) -> None:
        if not reviewer.strip() or not reason.strip():
            raise ValueError("A reviewer and rejection reason are required.")
        if self.status is not DraftStatus.PENDING_REVIEW:
            raise ValueError("Only a pending draft can be rejected.")
        self.status = DraftStatus.REJECTED
        self.reviewer = reviewer
        self.rejection_reason = reason

    @property
    def ready_for_execution(self) -> bool:
        return self.status is DraftStatus.APPROVED


def create_draft(recipient: str, body: str, evidence: list[str]) -> Draft:
    """Validate the minimum information needed for human review."""
    if not recipient.strip() or not body.strip() or not evidence:
        raise ValueError("Recipient, body, and supporting evidence are required.")
    return Draft(recipient=recipient, body=body, evidence=tuple(evidence))
