from backend.app.models.core import CandidateTerm, ReviewStatus


EXPORTABLE_STATUSES = {
    ReviewStatus.APPROVED,
    ReviewStatus.APPROVED_WITH_EDITS,
}


def can_export_to_odk(candidate: CandidateTerm) -> bool:
    """Return true only when a human-approved candidate may enter ODK templates."""
    return candidate.review_status in EXPORTABLE_STATUSES

