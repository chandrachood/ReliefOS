from __future__ import annotations

import json

from app.models import CaseRecord, TriageResult
from app.settings import Settings

SYSTEM_PROMPT = """
You are the triage-support component of ReliefOS, a disaster-response coordination system.
You recommend; you never dispatch, reject, close, identify a deceased person, or reduce a
deterministic life-safety priority. Use only the submitted case facts. Never invent road access,
medical diagnosis, media authenticity, or responder availability. Identify missing information,
use short machine-readable reason codes, and always require human review.
""".strip()


class StrandsTriageAgent:
    """Optional Bedrock-backed enrichment that cannot replace deterministic triage."""

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_triage_enabled or not settings.bedrock_model_id:
            raise ValueError("AI triage is disabled")

        from strands import Agent
        from strands.models import BedrockModel

        bedrock_model = BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
            temperature=0.1,
            guardrail_id=settings.bedrock_guardrail_id,
            guardrail_version=settings.bedrock_guardrail_version,
        )
        self.agent = Agent(
            model=bedrock_model,
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
        )

    def analyze(self, case: CaseRecord) -> TriageResult:
        facts = {
            "case_type": case.case_type,
            "affected_people_count": case.affected_people_count,
            "description": case.description,
            "location_available": case.latitude is not None,
            "gps_accuracy_meters": case.gps_accuracy_meters,
            "danger_indicators": case.danger_indicators,
            "requested_assistance": case.requested_assistance,
            "deterministic_priority": case.triage.suggested_priority,
            "deterministic_reason_codes": case.triage.reason_codes,
        }
        prompt = (
            "Review this case and return a structured triage recommendation. "
            "Do not reduce the deterministic priority.\n" + json.dumps(facts, default=str)
        )
        return self.agent.structured_output(TriageResult, prompt)
