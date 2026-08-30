from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status

from app.auth import get_actor, require_roles
from app.models import (
    Actor,
    ActorRole,
    AssignmentCreate,
    CaseCreate,
    CaseCreated,
    CaseStatus,
    CaseView,
    MediaUploadRequest,
    MediaUploadResponse,
    MissionRecord,
    MissionStatusUpdate,
    PersonCreate,
    PersonPublicView,
    PriorityUpdate,
    ResponderAvailabilityUpdate,
    ResponderCreate,
    ResponderLocationUpdate,
    ResponderRecord,
    ShelterCreate,
    ShelterNearbyView,
    ShelterRecord,
    VerificationUpdate,
)
from app.services import ReliefOSService

router = APIRouter(prefix="/v1")


def get_service(request: Request) -> ReliefOSService:
    return request.app.state.service


Service = Annotated[ReliefOSService, Depends(get_service)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
Coordinator = Annotated[Actor, Depends(require_roles(ActorRole.COORDINATOR))]
ResponderOrCoordinator = Annotated[
    Actor, Depends(require_roles(ActorRole.RESPONDER, ActorRole.COORDINATOR))
]


@router.post("/cases", response_model=CaseCreated, status_code=status.HTTP_201_CREATED)
def create_case(
    report: CaseCreate,
    service: Service,
    actor: CurrentActor,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> CaseCreated:
    return service.create_case(report, actor, idempotency_key)


@router.get("/cases/{case_id}", response_model=CaseView)
def get_case(
    case_id: str,
    service: Service,
    actor: CurrentActor,
    x_case_access_token: Annotated[str | None, Header(alias="X-Case-Access-Token")] = None,
) -> CaseView:
    return service.get_case(case_id, actor, x_case_access_token)


@router.post("/cases/{case_id}/media-upload", response_model=MediaUploadResponse)
def prepare_media_upload(
    case_id: str,
    upload: MediaUploadRequest,
    service: Service,
    actor: CurrentActor,
    x_case_access_token: Annotated[str | None, Header(alias="X-Case-Access-Token")] = None,
) -> MediaUploadResponse:
    return service.create_media_upload(case_id, upload, actor, x_case_access_token)


@router.put("/local-media/{case_id}/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def upload_local_media(
    case_id: str,
    media_id: str,
    request: Request,
    service: Service,
    x_upload_token: Annotated[str, Header(alias="X-Upload-Token")],
    content_type: Annotated[str, Header(alias="Content-Type")],
) -> Response:
    if service.settings.app_env == "production":
        raise HTTPException(status_code=404, detail="Not found")
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        if declared_size < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if declared_size > service.settings.max_media_bytes:
            raise HTTPException(status_code=413, detail="Media is too large")
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > service.settings.max_media_bytes:
            raise HTTPException(status_code=413, detail="Media is too large")
        chunks.append(chunk)
    try:
        service.media.consume_local_ticket(
            case_id, media_id, x_upload_token, content_type, b"".join(chunks)
        )
        service.mark_media_uploaded(case_id, "local-upload", media_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/people/reports", response_model=PersonPublicView, status_code=201)
def report_person(report: PersonCreate, service: Service, actor: CurrentActor) -> PersonPublicView:
    return service.register_person(report, actor)


@router.get("/people/search", response_model=list[PersonPublicView])
def search_people(
    service: Service,
    query: Annotated[str, Query(min_length=2, max_length=160)],
) -> list[PersonPublicView]:
    return service.search_people(query)


@router.post("/responders/register", response_model=ResponderRecord, status_code=201)
def register_responder(
    report: ResponderCreate, service: Service, actor: CurrentActor
) -> ResponderRecord:
    return service.register_responder(report, actor)


@router.patch("/responders/{responder_id}/availability", response_model=ResponderRecord)
def update_responder_availability(
    responder_id: str,
    update: ResponderAvailabilityUpdate,
    service: Service,
    actor: ResponderOrCoordinator,
) -> ResponderRecord:
    if ActorRole.COORDINATOR not in actor.roles and actor.actor_id != responder_id:
        raise HTTPException(status_code=403, detail="Responder access denied")
    return service.update_responder_availability(responder_id, update)


@router.patch("/responders/{responder_id}/location", response_model=ResponderRecord)
def update_responder_location(
    responder_id: str,
    update: ResponderLocationUpdate,
    service: Service,
    actor: ResponderOrCoordinator,
) -> ResponderRecord:
    if ActorRole.COORDINATOR not in actor.roles and actor.actor_id != responder_id:
        raise HTTPException(status_code=403, detail="Responder access denied")
    return service.update_responder_location(responder_id, update)


@router.get("/responders/{responder_id}/missions", response_model=list[MissionRecord])
def list_responder_missions(
    responder_id: str, service: Service, actor: ResponderOrCoordinator
) -> list[MissionRecord]:
    if ActorRole.COORDINATOR not in actor.roles and actor.actor_id != responder_id:
        raise HTTPException(status_code=403, detail="Responder access denied")
    return service.list_team_missions(responder_id)


@router.post("/missions/{mission_id}/status", response_model=MissionRecord)
def update_mission_status(
    mission_id: str,
    update: MissionStatusUpdate,
    service: Service,
    actor: ResponderOrCoordinator,
) -> MissionRecord:
    return service.update_mission(mission_id, update, actor)


@router.get("/shelters/nearby", response_model=list[ShelterNearbyView])
def nearby_shelters(
    service: Service,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(gt=0, le=500)] = 50,
) -> list[ShelterNearbyView]:
    return service.nearby_shelters(latitude, longitude, radius_km)


@router.get("/admin/cases", response_model=list[CaseView])
def admin_list_cases(
    service: Service,
    actor: Coordinator,
    case_status: Annotated[CaseStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CaseView]:
    del actor
    return service.list_cases(case_status, limit)


@router.post("/admin/cases/{case_id}/priority", response_model=CaseView)
def admin_update_priority(
    case_id: str, update: PriorityUpdate, service: Service, actor: Coordinator
) -> CaseView:
    return service.update_priority(case_id, update, actor)


@router.post("/admin/cases/{case_id}/verify", response_model=CaseView)
def admin_verify_case(
    case_id: str, update: VerificationUpdate, service: Service, actor: Coordinator
) -> CaseView:
    return service.update_verification(case_id, update, actor)


@router.post("/admin/cases/{case_id}/assign", response_model=MissionRecord, status_code=201)
def admin_assign_case(
    case_id: str, assignment: AssignmentCreate, service: Service, actor: Coordinator
) -> MissionRecord:
    return service.assign_case(case_id, assignment, actor)


@router.get("/admin/responders", response_model=list[ResponderRecord])
def admin_list_responders(service: Service, actor: Coordinator) -> list[ResponderRecord]:
    del actor
    return service.list_responders()


@router.post("/admin/responders/{responder_id}/approve", response_model=ResponderRecord)
def admin_approve_responder(
    responder_id: str, service: Service, actor: Coordinator
) -> ResponderRecord:
    return service.approve_responder(responder_id, actor)


@router.post("/admin/shelters", response_model=ShelterRecord, status_code=201)
def admin_create_shelter(
    shelter: ShelterCreate, service: Service, actor: Coordinator
) -> ShelterRecord:
    return service.create_shelter(shelter, actor)
