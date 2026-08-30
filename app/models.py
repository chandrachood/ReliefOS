from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ActorRole(StrEnum):
    CITIZEN = "citizen"
    RESPONDER = "responder"
    MEDICAL = "medical"
    SHELTER_OPERATOR = "shelter_operator"
    COORDINATOR = "coordinator"
    RECOVERY_OFFICER = "recovery_officer"


class Actor(BaseModel):
    actor_id: str
    roles: set[ActorRole]


class CaseType(StrEnum):
    TRAPPED = "trapped"
    INJURED = "injured"
    MISSING = "missing"
    STRANDED = "stranded"
    DECEASED_RECOVERY = "deceased_recovery"
    INFRASTRUCTURE_HAZARD = "infrastructure_hazard"
    SUPPLY_REQUEST = "supply_request"


class DangerIndicator(StrEnum):
    CANNOT_BREATHE = "cannot_breathe"
    UNCONSCIOUS = "unconscious"
    SEVERE_BLEEDING = "severe_bleeding"
    RISING_WATER = "rising_water"
    ACTIVE_FIRE = "active_fire"
    STRUCTURAL_COLLAPSE = "structural_collapse"
    PEOPLE_TRAPPED = "people_trapped"
    MASS_CASUALTY = "mass_casualty"
    IMMOBILE = "immobile"


class AssistanceType(StrEnum):
    RESCUE = "rescue"
    MEDICAL = "medical"
    FOOD = "food"
    WATER = "water"
    MEDICINE = "medicine"
    SHELTER = "shelter"
    BOAT = "boat"
    EVACUATION = "evacuation"
    POWER = "power"
    COMMUNICATION = "communication"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


PRIORITY_RANK: dict[Priority, int] = {
    Priority.P0: 0,
    Priority.P1: 1,
    Priority.P2: 2,
    Priority.P3: 3,
    Priority.P4: 4,
}


class CaseStatus(StrEnum):
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    TEAM_ASSIGNED = "team_assigned"
    TEAM_EN_ROUTE = "team_en_route"
    REACHED_LOCATION = "reached_location"
    ASSISTANCE_DELIVERED = "assistance_delivered"
    EVACUATED = "evacuated"
    UNABLE_TO_REACH = "unable_to_reach"
    CLOSED = "closed"
    REJECTED = "rejected"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"
    SUSPECTED_MANIPULATION = "suspected_manipulation"
    TRUSTED_RESPONDER_VERIFIED = "trusted_responder_verified"
    OFFICIALLY_VERIFIED = "officially_verified"


class ProcessingStatus(StrEnum):
    RULES_COMPLETE = "rules_complete"
    QUEUED = "queued"
    AI_COMPLETE = "ai_complete"
    AI_FAILED = "ai_failed"


class Reporter(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, min_length=5, max_length=32)


class CaseCreate(BaseModel):
    case_type: CaseType
    reporter: Reporter = Field(default_factory=Reporter)
    affected_people_count: int = Field(default=1, ge=1, le=10_000)
    description: NonEmptyText = Field(max_length=4_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    gps_accuracy_meters: float | None = Field(default=None, ge=0, le=100_000)
    location_description: str | None = Field(default=None, max_length=500)
    danger_indicators: list[DangerIndicator] = Field(default_factory=list, max_length=20)
    requested_assistance: list[AssistanceType] = Field(default_factory=list, max_length=20)
    preferred_language: str = Field(default="en-IN", min_length=2, max_length=20)

    @model_validator(mode="after")
    def validate_location(self) -> CaseCreate:
        coordinates_complete = self.latitude is not None and self.longitude is not None
        coordinates_empty = self.latitude is None and self.longitude is None
        if not coordinates_complete and not coordinates_empty:
            raise ValueError("latitude and longitude must be supplied together")
        if coordinates_empty and not self.location_description:
            raise ValueError("GPS coordinates or a location description is required")
        return self


class TriageResult(BaseModel):
    """Validated output produced by deterministic rules or the Strands agent."""

    suggested_priority: Priority
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    summary: str = Field(default="", max_length=2_000)
    human_review_required: bool = True


class CaseRecord(BaseModel):
    case_id: str
    access_token_hash: str
    idempotency_key: str
    request_fingerprint: str
    reporter_id: str
    case_type: CaseType
    reporter: Reporter
    affected_people_count: int
    description: str
    latitude: float | None
    longitude: float | None
    gps_accuracy_meters: float | None
    location_description: str | None
    geo_cell: str | None
    danger_indicators: list[DangerIndicator]
    requested_assistance: list[AssistanceType]
    preferred_language: str
    priority: Priority
    priority_source: str
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    status: CaseStatus = CaseStatus.RECEIVED
    processing_status: ProcessingStatus = ProcessingStatus.RULES_COMPLETE
    assigned_team_id: str | None = None
    triage: TriageResult
    media_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    version: int = 1


class CaseView(BaseModel):
    case_id: str
    case_type: CaseType
    affected_people_count: int
    description: str
    latitude: float | None
    longitude: float | None
    gps_accuracy_meters: float | None
    location_description: str | None
    danger_indicators: list[DangerIndicator]
    requested_assistance: list[AssistanceType]
    preferred_language: str
    priority: Priority
    verification_status: VerificationStatus
    status: CaseStatus
    processing_status: ProcessingStatus
    assigned_team_id: str | None
    triage: TriageResult
    media_count: int
    created_at: datetime
    updated_at: datetime
    version: int


class CaseCreated(BaseModel):
    case: CaseView
    access_token: str


class PriorityUpdate(BaseModel):
    priority: Priority
    reason: NonEmptyText = Field(max_length=500)


class VerificationUpdate(BaseModel):
    verification_status: VerificationStatus
    reason: NonEmptyText = Field(max_length=500)


class AssignmentCreate(BaseModel):
    team_id: NonEmptyText = Field(max_length=120)
    reason: NonEmptyText = Field(max_length=500)


class MediaUploadRequest(BaseModel):
    file_name: NonEmptyText = Field(max_length=255)
    content_type: str = Field(pattern=r"^(image|video|audio)/[A-Za-z0-9.+-]+$")
    size_bytes: int = Field(ge=1)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class MediaUploadResponse(BaseModel):
    media_id: str
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str]
    form_fields: dict[str, str] | None = None
    expires_in_seconds: int


class PersonStatus(StrEnum):
    SAFE = "safe"
    STRANDED = "stranded"
    MISSING = "missing"
    LOCATED = "located"
    UNDER_RESCUE = "under_rescue"
    EVACUATED = "evacuated"
    AT_SHELTER = "at_shelter"
    HOSPITALIZED = "hospitalized"
    DECEASED_UNVERIFIED = "deceased_unverified"
    DECEASED_VERIFIED = "deceased_verified"


class PersonCreate(BaseModel):
    full_name: NonEmptyText = Field(max_length=160)
    approximate_age: int | None = Field(default=None, ge=0, le=130)
    status: PersonStatus
    last_confirmed_area: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    case_id: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1_000)


class PersonRecord(BaseModel):
    person_id: str
    full_name: str
    normalized_name: str
    approximate_age: int | None
    status: PersonStatus
    last_confirmed_area: str | None
    phone_hash: str | None
    case_id: str | None
    notes: str | None
    reported_by: str
    official_status: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PersonPublicView(BaseModel):
    person_id: str
    full_name: str
    approximate_age: int | None
    status: PersonStatus
    last_confirmed_area: str | None
    official_status: bool
    updated_at: datetime


class ResponderType(StrEnum):
    RESCUE_TEAM = "rescue_team"
    MEDICAL_PROFESSIONAL = "medical_professional"
    SHELTER_TEAM = "shelter_team"


class Availability(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


class ResponderCreate(BaseModel):
    name: NonEmptyText = Field(max_length=160)
    agency: str | None = Field(default=None, max_length=160)
    responder_type: ResponderType
    capabilities: list[str] = Field(default_factory=list, max_length=30)
    phone: str | None = Field(default=None, max_length=32)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ResponderRecord(BaseModel):
    responder_id: str
    name: str
    agency: str | None
    responder_type: ResponderType
    capabilities: list[str]
    phone: str | None
    latitude: float | None
    longitude: float | None
    geo_cell: str | None
    availability: Availability = Availability.OFFLINE
    approved: bool = False
    workload: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResponderAvailabilityUpdate(BaseModel):
    availability: Availability


class ResponderLocationUpdate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class MissionStatus(StrEnum):
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    EN_ROUTE = "en_route"
    REACHED = "reached"
    COMPLETED = "completed"
    UNABLE_TO_REACH = "unable_to_reach"
    REJECTED = "rejected"


class MissionRecord(BaseModel):
    mission_id: str
    case_id: str
    team_id: str
    status: MissionStatus = MissionStatus.ASSIGNED
    assignment_reason: str
    status_note: str | None = None
    assigned_by: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MissionStatusUpdate(BaseModel):
    status: MissionStatus
    note: str | None = Field(default=None, max_length=500)


class ShelterCreate(BaseModel):
    name: NonEmptyText = Field(max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=500)
    capacity: int = Field(ge=0, le=1_000_000)
    occupancy: int = Field(default=0, ge=0, le=1_000_000)
    facilities: list[str] = Field(default_factory=list, max_length=30)
    operational: bool = True
    contact: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def occupancy_not_above_capacity(self) -> ShelterCreate:
        if self.occupancy > self.capacity:
            raise ValueError("occupancy cannot exceed capacity")
        return self


class ShelterRecord(ShelterCreate):
    shelter_id: str
    geo_cell: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ShelterNearbyView(ShelterRecord):
    distance_km: float


class AuditEvent(BaseModel):
    event_id: str
    entity_id: str
    event_type: str
    actor_id: str
    reason: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
