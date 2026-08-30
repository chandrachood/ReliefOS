from app.models import (
    AssistanceType,
    CaseCreate,
    CaseType,
    DangerIndicator,
    Priority,
    TriageResult,
)

P1_INDICATORS = {
    DangerIndicator.CANNOT_BREATHE,
    DangerIndicator.UNCONSCIOUS,
    DangerIndicator.SEVERE_BLEEDING,
    DangerIndicator.RISING_WATER,
    DangerIndicator.ACTIVE_FIRE,
    DangerIndicator.STRUCTURAL_COLLAPSE,
    DangerIndicator.PEOPLE_TRAPPED,
}


def deterministic_triage(report: CaseCreate) -> TriageResult:
    """Safety rules that run before and independently of all model calls."""

    indicators = set(report.danger_indicators)
    reasons: list[str] = []
    capabilities: set[str] = set()
    missing: list[str] = []

    if DangerIndicator.MASS_CASUALTY in indicators or (
        report.affected_people_count >= 10
        and indicators
        & {
            DangerIndicator.STRUCTURAL_COLLAPSE,
            DangerIndicator.ACTIVE_FIRE,
            DangerIndicator.RISING_WATER,
        }
    ):
        priority = Priority.P0
        reasons.append("mass_casualty_or_expanding_threat")
    elif indicators & P1_INDICATORS:
        priority = Priority.P1
        reasons.extend(sorted(item.value for item in indicators & P1_INDICATORS))
    elif report.case_type in {CaseType.INJURED, CaseType.TRAPPED, CaseType.STRANDED}:
        priority = Priority.P2
        reasons.append(f"serious_case_type:{report.case_type.value}")
    elif report.case_type == CaseType.SUPPLY_REQUEST:
        priority = Priority.P3
        reasons.append("essential_supply_request")
    else:
        priority = Priority.P4
        reasons.append("assessment_required")

    if (
        AssistanceType.MEDICAL in report.requested_assistance
        or report.case_type == CaseType.INJURED
    ):
        capabilities.add("medical")
    if (
        AssistanceType.BOAT in report.requested_assistance
        or DangerIndicator.RISING_WATER in indicators
    ):
        capabilities.add("boat")
    if report.case_type == CaseType.TRAPPED or DangerIndicator.STRUCTURAL_COLLAPSE in indicators:
        capabilities.add("search_and_rescue")
    if AssistanceType.EVACUATION in report.requested_assistance:
        capabilities.add("evacuation_transport")
    if report.case_type == CaseType.DECEASED_RECOVERY:
        capabilities.add("authorized_recovery")

    if report.latitude is None:
        missing.append("verified_coordinates")
    if not report.reporter.phone:
        missing.append("reporter_contact")
    if not report.requested_assistance:
        missing.append("requested_assistance")

    return TriageResult(
        suggested_priority=priority,
        confidence=1.0,
        reason_codes=reasons,
        required_capabilities=sorted(capabilities),
        missing_information=missing,
        summary="Deterministic safety triage completed. Human review is required.",
        human_review_required=True,
    )
