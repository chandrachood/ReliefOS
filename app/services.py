from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from app.integrations import MediaService, QueuePublisher
from app.models import (
    PRIORITY_RANK,
    Actor,
    ActorRole,
    AssignmentCreate,
    AuditEvent,
    Availability,
    CaseCreate,
    CaseCreated,
    CaseRecord,
    CaseStatus,
    CaseView,
    MediaUploadRequest,
    MediaUploadResponse,
    MissionRecord,
    MissionStatus,
    MissionStatusUpdate,
    PersonCreate,
    PersonPublicView,
    PersonRecord,
    PersonStatus,
    PriorityUpdate,
    ProcessingStatus,
    ResponderAvailabilityUpdate,
    ResponderCreate,
    ResponderLocationUpdate,
    ResponderRecord,
    ShelterCreate,
    ShelterNearbyView,
    ShelterRecord,
    VerificationUpdate,
    utc_now,
)
from app.repositories import ConflictError, Repository
from app.settings import Settings
from app.triage import deterministic_triage


def geo_cell(latitude: float | None, longitude: float | None, precision: int = 2) -> str | None:
    if latitude is None or longitude is None:
        return None
    return f"{round(latitude, precision):.{precision}f}:{round(longitude, precision):.{precision}f}"


def case_view(case: CaseRecord) -> CaseView:
    return CaseView.model_validate(case.model_dump(exclude={"access_token_hash", "reporter"}))


class ReliefOSService:
    def __init__(
        self,
        repository: Repository,
        queue: QueuePublisher,
        media: MediaService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.media = media
        self.settings = settings

    def _case_token(self, case_id: str) -> str:
        digest = hmac.new(
            self.settings.case_access_secret.encode(), case_id.encode(), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    @staticmethod
    def _fingerprint(report: CaseCreate) -> str:
        body = report.model_dump_json(exclude_none=True)
        return hashlib.sha256(body.encode()).hexdigest()

    def _audit(
        self,
        entity_id: str,
        event_type: str,
        actor_id: str,
        *,
        reason: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.repository.append_audit(
            AuditEvent(
                event_id=f"audit_{uuid.uuid4().hex}",
                entity_id=entity_id,
                event_type=event_type,
                actor_id=actor_id,
                reason=reason,
                details=details or {},
            )
        )

    def create_case(self, report: CaseCreate, actor: Actor, idempotency_key: str) -> CaseCreated:
        if not 8 <= len(idempotency_key) <= 200:
            raise HTTPException(status_code=400, detail="Idempotency-Key must be 8-200 characters")
        case_id = (
            "case_"
            + uuid.uuid5(uuid.NAMESPACE_URL, f"reliefos:{actor.actor_id}:{idempotency_key}").hex
        )
        fingerprint = self._fingerprint(report)
        access_token = self._case_token(case_id)
        existing = self.repository.get_case(case_id)
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with different request data",
                )
            return CaseCreated(case=case_view(existing), access_token=access_token)

        triage = deterministic_triage(report)
        case = CaseRecord(
            case_id=case_id,
            access_token_hash=hashlib.sha256(access_token.encode()).hexdigest(),
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            reporter_id=actor.actor_id,
            priority=triage.suggested_priority,
            priority_source="deterministic_rules",
            triage=triage,
            geo_cell=geo_cell(report.latitude, report.longitude),
            **report.model_dump(),
        )
        try:
            self.repository.save_case(case)
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        self._audit(case.case_id, "case.created", actor.actor_id)

        try:
            if self.queue.publish_case(case.case_id):
                updated = case.model_copy(
                    update={
                        "processing_status": ProcessingStatus.QUEUED,
                        "updated_at": utc_now(),
                        "version": case.version + 1,
                    }
                )
                self.repository.save_case(updated, expected_version=case.version)
                case = updated
        except Exception:
            # Queue failure must never erase or reject an already durable emergency report.
            self._audit(case.case_id, "case.queue_failed", "system")

        return CaseCreated(case=case_view(case), access_token=access_token)

    def get_case(self, case_id: str, actor: Actor, access_token: str | None) -> CaseView:
        case = self.repository.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        privileged = bool(
            actor.roles
            & {
                ActorRole.COORDINATOR,
                ActorRole.RESPONDER,
                ActorRole.MEDICAL,
                ActorRole.RECOVERY_OFFICER,
            }
        )
        token_valid = access_token is not None and hmac.compare_digest(
            hashlib.sha256(access_token.encode()).hexdigest(), case.access_token_hash
        )
        if actor.actor_id != case.reporter_id and not privileged and not token_valid:
            raise HTTPException(status_code=403, detail="Case access denied")
        return case_view(case)

    def list_cases(self, status: CaseStatus | None, limit: int) -> list[CaseView]:
        return [case_view(item) for item in self.repository.list_cases(status=status, limit=limit)]

    def update_priority(self, case_id: str, update: PriorityUpdate, actor: Actor) -> CaseView:
        case = self._require_case(case_id)
        updated = case.model_copy(
            update={
                "priority": update.priority,
                "priority_source": f"human:{actor.actor_id}",
                "updated_at": utc_now(),
                "version": case.version + 1,
            }
        )
        self.repository.save_case(updated, expected_version=case.version)
        self._audit(
            case_id,
            "case.priority_changed",
            actor.actor_id,
            reason=update.reason,
            details={"from": case.priority.value, "to": update.priority.value},
        )
        return case_view(updated)

    def update_verification(
        self, case_id: str, update: VerificationUpdate, actor: Actor
    ) -> CaseView:
        case = self._require_case(case_id)
        status = CaseStatus.VERIFIED if case.status == CaseStatus.RECEIVED else case.status
        updated = case.model_copy(
            update={
                "verification_status": update.verification_status,
                "status": status,
                "updated_at": utc_now(),
                "version": case.version + 1,
            }
        )
        self.repository.save_case(updated, expected_version=case.version)
        self._audit(
            case_id,
            "case.verification_changed",
            actor.actor_id,
            reason=update.reason,
            details={"to": update.verification_status.value},
        )
        return case_view(updated)

    def assign_case(
        self, case_id: str, assignment: AssignmentCreate, actor: Actor
    ) -> MissionRecord:
        case = self._require_case(case_id)
        team = self.repository.get_responder(assignment.team_id)
        if not team or not team.approved:
            raise HTTPException(status_code=400, detail="Approved response team not found")
        if team.availability == Availability.OFFLINE:
            raise HTTPException(status_code=409, detail="Response team is offline")
        mission = MissionRecord(
            mission_id=f"mission_{uuid.uuid4().hex}",
            case_id=case_id,
            team_id=team.responder_id,
            assignment_reason=assignment.reason,
            assigned_by=actor.actor_id,
        )
        self.repository.save_mission(mission)
        updated_case = case.model_copy(
            update={
                "assigned_team_id": team.responder_id,
                "status": CaseStatus.TEAM_ASSIGNED,
                "updated_at": utc_now(),
                "version": case.version + 1,
            }
        )
        self.repository.save_case(updated_case, expected_version=case.version)
        self.repository.save_responder(
            team.model_copy(update={"workload": team.workload + 1, "updated_at": utc_now()})
        )
        self._audit(
            case_id,
            "case.assigned",
            actor.actor_id,
            reason=assignment.reason,
            details={"team_id": team.responder_id, "mission_id": mission.mission_id},
        )
        return mission

    def create_media_upload(
        self,
        case_id: str,
        request: MediaUploadRequest,
        actor: Actor,
        access_token: str | None,
    ) -> MediaUploadResponse:
        self.get_case(case_id, actor, access_token)
        case = self._require_case(case_id)
        try:
            upload = self.media.create_upload(case, request)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        self._audit(
            case_id,
            "media.upload_prepared",
            actor.actor_id,
            details={"media_id": upload.media_id, "content_type": request.content_type},
        )
        return upload

    def register_person(self, report: PersonCreate, actor: Actor) -> PersonPublicView:
        if report.status == PersonStatus.DECEASED_VERIFIED and not actor.roles.intersection(
            {ActorRole.COORDINATOR, ActorRole.RECOVERY_OFFICER}
        ):
            raise HTTPException(
                status_code=403, detail="Only authorized officers can verify deceased status"
            )
        normalized_name = " ".join(report.full_name.casefold().split())
        phone_hash = (
            hashlib.sha256(re.sub(r"\D", "", report.phone).encode()).hexdigest()
            if report.phone
            else None
        )
        person = PersonRecord(
            person_id=f"person_{uuid.uuid4().hex}",
            normalized_name=normalized_name,
            phone_hash=phone_hash,
            reported_by=actor.actor_id,
            **report.model_dump(exclude={"phone"}),
        )
        self.repository.save_person(person)
        self._audit(person.person_id, "person.reported", actor.actor_id)
        return PersonPublicView.model_validate(person.model_dump())

    def search_people(self, query: str) -> list[PersonPublicView]:
        normalized = " ".join(query.casefold().split())
        digits = re.sub(r"\D", "", query)
        search_value = (
            hashlib.sha256(digits.encode()).hexdigest() if len(digits) >= 5 else normalized
        )
        return [
            PersonPublicView.model_validate(item.model_dump())
            for item in self.repository.search_people(search_value)
            if item.status != PersonStatus.DECEASED_UNVERIFIED
        ]

    def mark_media_uploaded(self, case_id: str, actor_id: str, media_id: str) -> None:
        case = self._require_case(case_id)
        updated = case.model_copy(
            update={
                "media_count": case.media_count + 1,
                "updated_at": utc_now(),
                "version": case.version + 1,
            }
        )
        self.repository.save_case(updated, expected_version=case.version)
        self._audit(
            case_id,
            "media.uploaded",
            actor_id,
            details={"media_id": media_id},
        )

    def register_responder(self, report: ResponderCreate, actor: Actor) -> ResponderRecord:
        responder = ResponderRecord(
            responder_id=f"responder_{uuid.uuid4().hex}",
            geo_cell=geo_cell(report.latitude, report.longitude),
            **report.model_dump(),
        )
        self.repository.save_responder(responder)
        self._audit(responder.responder_id, "responder.registered", actor.actor_id)
        return responder

    def approve_responder(self, responder_id: str, actor: Actor) -> ResponderRecord:
        responder = self.repository.get_responder(responder_id)
        if not responder:
            raise HTTPException(status_code=404, detail="Responder not found")
        updated = responder.model_copy(update={"approved": True, "updated_at": utc_now()})
        self.repository.save_responder(updated)
        self._audit(responder_id, "responder.approved", actor.actor_id)
        return updated

    def update_responder_availability(
        self, responder_id: str, update: ResponderAvailabilityUpdate
    ) -> ResponderRecord:
        responder = self._require_responder(responder_id)
        updated = responder.model_copy(
            update={"availability": update.availability, "updated_at": utc_now()}
        )
        self.repository.save_responder(updated)
        return updated

    def update_responder_location(
        self, responder_id: str, update: ResponderLocationUpdate
    ) -> ResponderRecord:
        responder = self._require_responder(responder_id)
        updated = responder.model_copy(
            update={
                "latitude": update.latitude,
                "longitude": update.longitude,
                "geo_cell": geo_cell(update.latitude, update.longitude),
                "updated_at": utc_now(),
            }
        )
        self.repository.save_responder(updated)
        return updated

    def list_responders(self) -> list[ResponderRecord]:
        return self.repository.list_responders()

    def list_team_missions(self, team_id: str) -> list[MissionRecord]:
        return self.repository.list_missions_for_team(team_id)

    def update_mission(
        self, mission_id: str, update: MissionStatusUpdate, actor: Actor
    ) -> MissionRecord:
        mission = self.repository.get_mission(mission_id)
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")
        if actor.actor_id != mission.team_id and ActorRole.COORDINATOR not in actor.roles:
            raise HTTPException(status_code=403, detail="Mission access denied")
        updated = mission.model_copy(
            update={"status": update.status, "status_note": update.note, "updated_at": utc_now()}
        )
        self.repository.save_mission(updated)
        case = self._require_case(mission.case_id)
        case_status_by_mission = {
            MissionStatus.ACCEPTED: CaseStatus.TEAM_ASSIGNED,
            MissionStatus.EN_ROUTE: CaseStatus.TEAM_EN_ROUTE,
            MissionStatus.REACHED: CaseStatus.REACHED_LOCATION,
            MissionStatus.COMPLETED: CaseStatus.ASSISTANCE_DELIVERED,
            MissionStatus.UNABLE_TO_REACH: CaseStatus.UNABLE_TO_REACH,
            MissionStatus.REJECTED: CaseStatus.UNDER_REVIEW,
        }
        if update.status in case_status_by_mission:
            updated_case = case.model_copy(
                update={
                    "status": case_status_by_mission[update.status],
                    "updated_at": utc_now(),
                    "version": case.version + 1,
                }
            )
            self.repository.save_case(updated_case, expected_version=case.version)
        self._audit(
            mission.case_id,
            "mission.status_changed",
            actor.actor_id,
            reason=update.note,
            details={"mission_id": mission_id, "status": update.status.value},
        )
        return updated

    def create_shelter(self, report: ShelterCreate, actor: Actor) -> ShelterRecord:
        shelter = ShelterRecord(
            shelter_id=f"shelter_{uuid.uuid4().hex}",
            geo_cell=geo_cell(report.latitude, report.longitude) or "",
            **report.model_dump(),
        )
        self.repository.save_shelter(shelter)
        self._audit(shelter.shelter_id, "shelter.created", actor.actor_id)
        return shelter

    def nearby_shelters(
        self, latitude: float, longitude: float, radius_km: float
    ) -> list[ShelterNearbyView]:
        results: list[ShelterNearbyView] = []
        for shelter in self.repository.list_shelters():
            distance = self._distance_km(latitude, longitude, shelter.latitude, shelter.longitude)
            if shelter.operational and distance <= radius_km:
                results.append(
                    ShelterNearbyView(**shelter.model_dump(), distance_km=round(distance, 2))
                )
        return sorted(results, key=lambda item: item.distance_km)

    def _require_case(self, case_id: str) -> CaseRecord:
        case = self.repository.get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    def _require_responder(self, responder_id: str) -> ResponderRecord:
        responder = self.repository.get_responder(responder_id)
        if not responder:
            raise HTTPException(status_code=404, detail="Responder not found")
        return responder

    @staticmethod
    def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6_371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def merge_ai_triage(case: CaseRecord, ai_result: object) -> CaseRecord:
    """Merge AI output without allowing it to lower a deterministic priority."""

    from app.models import TriageResult

    result = TriageResult.model_validate(ai_result)
    priority = (
        result.suggested_priority
        if PRIORITY_RANK[result.suggested_priority] < PRIORITY_RANK[case.priority]
        else case.priority
    )
    return case.model_copy(
        update={
            "priority": priority,
            "priority_source": (
                "ai_escalation" if priority != case.priority else case.priority_source
            ),
            "triage": result,
            "processing_status": ProcessingStatus.AI_COMPLETE,
            "updated_at": datetime.now(UTC),
            "version": case.version + 1,
        }
    )
