from backend.app.models.core import CandidateTerm, ReviewStatus
from backend.app.review.policy import can_export_to_odk


def candidate(status: ReviewStatus) -> CandidateTerm:
    return CandidateTerm(
        candidate_id="CAND:0001",
        label="test term",
        confidence_score=0.9,
        review_status=status,
    )


def test_only_approved_candidates_export() -> None:
    assert can_export_to_odk(candidate(ReviewStatus.APPROVED))
    assert can_export_to_odk(candidate(ReviewStatus.APPROVED_WITH_EDITS))
    assert not can_export_to_odk(candidate(ReviewStatus.NEW))
    assert not can_export_to_odk(candidate(ReviewStatus.REJECTED))

