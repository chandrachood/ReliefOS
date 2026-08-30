import pytest
from pydantic import ValidationError

from app.models import CaseCreate, CaseRecord, Priority, ProcessingStatus
from app.services import merge_ai_triage
from app.triage import deterministic_triage


def test_mass_casualty_rule_is_p0():
    report = CaseCreate(
        case_type="trapped",
        affected_people_count=12,
        description="Building collapsed with many people inside",
        location_description="Market building",
        danger_indicators=["structural_collapse"],
    )

    result = deterministic_triage(report)

    assert result.suggested_priority == Priority.P0
    assert result.confidence == 1.0


def test_supply_request_is_p3_without_immediate_danger():
    report = CaseCreate(
        case_type="supply_request",
        description="Isolated family needs drinking water",
        location_description="Hill settlement",
        requested_assistance=["water"],
    )

    assert deterministic_triage(report).suggested_priority == Priority.P3


def test_ai_cannot_lower_deterministic_priority():
    report = CaseCreate(
        case_type="trapped",
        description="Person trapped in rising water",
        location_description="House",
        danger_indicators=["rising_water"],
    )
    deterministic = deterministic_triage(report)
    case = CaseRecord(
        case_id="case-test",
        access_token_hash="hash",
        idempotency_key="request-test",
        request_fingerprint="fingerprint",
        reporter_id="reporter",
        geo_cell=None,
        priority=deterministic.suggested_priority,
        priority_source="deterministic_rules",
        triage=deterministic,
        **report.model_dump(),
    )

    merged = merge_ai_triage(
        case,
        {
            "suggested_priority": "P4",
            "confidence": 0.8,
            "reason_codes": ["model_assessment"],
            "human_review_required": True,
        },
    )

    assert merged.priority == Priority.P1
    assert merged.processing_status == ProcessingStatus.AI_COMPLETE


def test_ai_may_escalate_priority():
    report = CaseCreate(
        case_type="supply_request",
        description="Insulin supply is nearly exhausted",
        location_description="Remote village",
    )
    deterministic = deterministic_triage(report)
    case = CaseRecord(
        case_id="case-escalate",
        access_token_hash="hash",
        idempotency_key="request-escalate",
        request_fingerprint="fingerprint",
        reporter_id="reporter",
        geo_cell=None,
        priority=deterministic.suggested_priority,
        priority_source="deterministic_rules",
        triage=deterministic,
        **report.model_dump(),
    )

    merged = merge_ai_triage(
        case,
        {
            "suggested_priority": "P1",
            "confidence": 0.7,
            "reason_codes": ["time_critical_medicine"],
            "human_review_required": True,
        },
    )

    assert merged.priority == Priority.P1
    assert merged.priority_source == "ai_escalation"


def test_infrastructure_report_without_active_danger_is_p4():
    report = CaseCreate(
        case_type="infrastructure_hazard",
        description="A road sign has fallen",
        location_description="Main road",
    )

    assert deterministic_triage(report).suggested_priority == Priority.P4


def test_report_requires_complete_coordinates_or_location_description():
    with pytest.raises(ValidationError):
        CaseCreate(
            case_type="stranded",
            description="Location cannot be determined",
            latitude=10.8,
        )
