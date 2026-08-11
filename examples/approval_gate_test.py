import unittest

from approval_gate import DraftStatus, create_draft


class ApprovalGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.draft = create_draft(
            recipient="review@example.test",
            body="Prepared response",
            evidence=["Inbound request", "Account context"],
        )

    def test_draft_requires_explicit_approval(self) -> None:
        self.assertFalse(self.draft.ready_for_execution)
        self.draft.approve("reviewer-1")
        self.assertTrue(self.draft.ready_for_execution)
        self.assertEqual(self.draft.status, DraftStatus.APPROVED)

    def test_rejected_draft_never_becomes_ready(self) -> None:
        self.draft.reject("reviewer-1", "Needs a factual correction")
        self.assertFalse(self.draft.ready_for_execution)
        self.assertEqual(self.draft.status, DraftStatus.REJECTED)

    def test_draft_cannot_be_approved_twice(self) -> None:
        self.draft.approve("reviewer-1")
        with self.assertRaises(ValueError):
            self.draft.approve("reviewer-2")


if __name__ == "__main__":
    unittest.main()
