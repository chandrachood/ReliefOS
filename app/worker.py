from __future__ import annotations

import json
import logging
import signal
import time

import boto3

from app.agent import StrandsTriageAgent
from app.models import AuditEvent, ProcessingStatus, utc_now
from app.repositories import build_repository
from app.services import merge_ai_triage
from app.settings import get_settings

logger = logging.getLogger(__name__)
stopping = False


def _stop(_signum: int, _frame: object) -> None:
    global stopping
    stopping = True


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    if not settings.case_queue_url:
        raise SystemExit("CASE_QUEUE_URL is required for the worker")
    repository = build_repository(settings)
    agent = StrandsTriageAgent(settings) if settings.ai_triage_enabled else None
    sqs = boto3.client("sqs", region_name=settings.aws_region)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopping:
        response = sqs.receive_message(
            QueueUrl=settings.case_queue_url,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=20,
            VisibilityTimeout=120,
        )
        for message in response.get("Messages", []):
            receipt = message["ReceiptHandle"]
            try:
                payload = json.loads(message["Body"])
                case_id = payload["case_id"]
                case = repository.get_case(case_id)
                if not case:
                    raise ValueError(f"case not found: {case_id}")
                if agent:
                    result = agent.analyze(case)
                    updated = merge_ai_triage(case, result)
                else:
                    updated = case.model_copy(
                        update={
                            "processing_status": ProcessingStatus.RULES_COMPLETE,
                            "updated_at": utc_now(),
                            "version": case.version + 1,
                        }
                    )
                repository.save_case(updated, expected_version=case.version)
                repository.append_audit(
                    AuditEvent(
                        event_id=f"worker_{case.case_id}_{int(time.time() * 1000)}",
                        entity_id=case.case_id,
                        event_type="case.ai_triage_completed" if agent else "case.rules_confirmed",
                        actor_id="system-worker",
                    )
                )
                sqs.delete_message(QueueUrl=settings.case_queue_url, ReceiptHandle=receipt)
            except Exception:
                logger.exception("case_processing_failed")


if __name__ == "__main__":
    main()
