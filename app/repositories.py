from __future__ import annotations

import json
import threading
from decimal import Decimal
from typing import Any, Protocol, TypeVar

from boto3.dynamodb.conditions import Attr

from app.models import (
    AuditEvent,
    CaseRecord,
    CaseStatus,
    MissionRecord,
    PersonRecord,
    ResponderRecord,
    ShelterRecord,
)
from app.settings import Settings


class ConflictError(RuntimeError):
    """Raised when an optimistic or uniqueness condition fails."""


class Repository(Protocol):
    def get_case(self, case_id: str) -> CaseRecord | None: ...

    def save_case(self, case: CaseRecord, *, expected_version: int | None = None) -> None: ...

    def list_cases(
        self, *, status: CaseStatus | None = None, limit: int = 100
    ) -> list[CaseRecord]: ...

    def save_person(self, person: PersonRecord) -> None: ...

    def search_people(self, query: str, *, limit: int = 50) -> list[PersonRecord]: ...

    def save_responder(self, responder: ResponderRecord) -> None: ...

    def get_responder(self, responder_id: str) -> ResponderRecord | None: ...

    def list_responders(self) -> list[ResponderRecord]: ...

    def save_mission(self, mission: MissionRecord) -> None: ...

    def get_mission(self, mission_id: str) -> MissionRecord | None: ...

    def list_missions_for_team(self, team_id: str) -> list[MissionRecord]: ...

    def save_shelter(self, shelter: ShelterRecord) -> None: ...

    def get_shelter(self, shelter_id: str) -> ShelterRecord | None: ...

    def list_shelters(self) -> list[ShelterRecord]: ...

    def append_audit(self, event: AuditEvent) -> None: ...


ModelT = TypeVar("ModelT")


class MemoryRepository:
    """Thread-safe local repository used for development and tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cases: dict[str, CaseRecord] = {}
        self._people: dict[str, PersonRecord] = {}
        self._responders: dict[str, ResponderRecord] = {}
        self._missions: dict[str, MissionRecord] = {}
        self._shelters: dict[str, ShelterRecord] = {}
        self._audit: list[AuditEvent] = []

    @staticmethod
    def _copy(model: ModelT) -> ModelT:
        if hasattr(model, "model_copy"):
            return model.model_copy(deep=True)  # type: ignore[no-any-return,union-attr]
        return model

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self._lock:
            case = self._cases.get(case_id)
            return self._copy(case) if case else None

    def save_case(self, case: CaseRecord, *, expected_version: int | None = None) -> None:
        with self._lock:
            existing = self._cases.get(case.case_id)
            if expected_version is None and existing is not None:
                if existing.request_fingerprint != case.request_fingerprint:
                    raise ConflictError("case already exists with different request data")
                return
            if expected_version is not None:
                if existing is None or existing.version != expected_version:
                    raise ConflictError("case was updated by another request")
            self._cases[case.case_id] = self._copy(case)

    def list_cases(self, *, status: CaseStatus | None = None, limit: int = 100) -> list[CaseRecord]:
        with self._lock:
            cases = [
                case for case in self._cases.values() if status is None or case.status == status
            ]
            cases.sort(key=lambda item: (item.priority.value, item.created_at))
            return [self._copy(case) for case in cases[:limit]]

    def save_person(self, person: PersonRecord) -> None:
        with self._lock:
            self._people[person.person_id] = self._copy(person)

    def search_people(self, query: str, *, limit: int = 50) -> list[PersonRecord]:
        normalized = " ".join(query.casefold().split())
        with self._lock:
            matches = [
                person
                for person in self._people.values()
                if normalized in person.normalized_name
                or normalized == person.person_id.casefold()
                or normalized == (person.case_id or "").casefold()
                or normalized == (person.phone_hash or "").casefold()
            ]
            return [self._copy(person) for person in matches[:limit]]

    def save_responder(self, responder: ResponderRecord) -> None:
        with self._lock:
            self._responders[responder.responder_id] = self._copy(responder)

    def get_responder(self, responder_id: str) -> ResponderRecord | None:
        with self._lock:
            responder = self._responders.get(responder_id)
            return self._copy(responder) if responder else None

    def list_responders(self) -> list[ResponderRecord]:
        with self._lock:
            return [self._copy(item) for item in self._responders.values()]

    def save_mission(self, mission: MissionRecord) -> None:
        with self._lock:
            self._missions[mission.mission_id] = self._copy(mission)

    def get_mission(self, mission_id: str) -> MissionRecord | None:
        with self._lock:
            mission = self._missions.get(mission_id)
            return self._copy(mission) if mission else None

    def list_missions_for_team(self, team_id: str) -> list[MissionRecord]:
        with self._lock:
            missions = [item for item in self._missions.values() if item.team_id == team_id]
            return [self._copy(item) for item in missions]

    def save_shelter(self, shelter: ShelterRecord) -> None:
        with self._lock:
            self._shelters[shelter.shelter_id] = self._copy(shelter)

    def get_shelter(self, shelter_id: str) -> ShelterRecord | None:
        with self._lock:
            shelter = self._shelters.get(shelter_id)
            return self._copy(shelter) if shelter else None

    def list_shelters(self) -> list[ShelterRecord]:
        with self._lock:
            return [self._copy(item) for item in self._shelters.values()]

    def append_audit(self, event: AuditEvent) -> None:
        with self._lock:
            self._audit.append(self._copy(event))


def _to_dynamo(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value), parse_float=Decimal)


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, list):
        return [_from_dynamo(item) for item in value]
    if isinstance(value, dict):
        return {key: _from_dynamo(item) for key, item in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


class DynamoRepository:
    """DynamoDB adapter. Table names and credentials come from environment configuration."""

    def __init__(self, settings: Settings) -> None:
        import boto3

        resource = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
            endpoint_url=settings.dynamodb_endpoint_url,
        )
        self.cases = resource.Table(settings.cases_table)
        self.people = resource.Table(settings.people_table)
        self.responders = resource.Table(settings.responders_table)
        self.missions = resource.Table(settings.missions_table)
        self.shelters = resource.Table(settings.shelters_table)
        self.audit = resource.Table(settings.audit_table)

    @staticmethod
    def _item(model: Any) -> dict[str, Any]:
        return _to_dynamo(model.model_dump(mode="json"))

    @staticmethod
    def _scan_all(table: Any, *, filter_expression: Any = None, limit: int = 100) -> list[Any]:
        items: list[Any] = []
        kwargs: dict[str, Any] = {"Limit": min(limit, 100)}
        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression
        while len(items) < limit:
            response = table.scan(**kwargs)
            items.extend(response.get("Items", []))
            key = response.get("LastEvaluatedKey")
            if not key:
                break
            kwargs["ExclusiveStartKey"] = key
            kwargs["Limit"] = min(limit - len(items), 100)
        return items[:limit]

    def get_case(self, case_id: str) -> CaseRecord | None:
        item = self.cases.get_item(Key={"case_id": case_id}, ConsistentRead=True).get("Item")
        return CaseRecord.model_validate(_from_dynamo(item)) if item else None

    def save_case(self, case: CaseRecord, *, expected_version: int | None = None) -> None:
        from botocore.exceptions import ClientError

        kwargs: dict[str, Any] = {"Item": self._item(case)}
        if expected_version is None:
            kwargs["ConditionExpression"] = "attribute_not_exists(case_id)"
        else:
            kwargs["ConditionExpression"] = "#version = :expected"
            kwargs["ExpressionAttributeNames"] = {"#version": "version"}
            kwargs["ExpressionAttributeValues"] = {":expected": expected_version}
        try:
            self.cases.put_item(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                if expected_version is None:
                    existing = self.get_case(case.case_id)
                    if existing and existing.request_fingerprint == case.request_fingerprint:
                        return
                raise ConflictError("case write condition failed") from exc
            raise

    def list_cases(self, *, status: CaseStatus | None = None, limit: int = 100) -> list[CaseRecord]:
        expression = Attr("status").eq(status.value) if status else None
        items = self._scan_all(self.cases, filter_expression=expression, limit=limit)
        cases = [CaseRecord.model_validate(_from_dynamo(item)) for item in items]
        return sorted(cases, key=lambda item: (item.priority.value, item.created_at))

    def save_person(self, person: PersonRecord) -> None:
        self.people.put_item(Item=self._item(person))

    def search_people(self, query: str, *, limit: int = 50) -> list[PersonRecord]:
        normalized = " ".join(query.casefold().split())
        expression = (
            Attr("normalized_name").contains(normalized)
            | Attr("person_id").eq(query)
            | Attr("case_id").eq(query)
            | Attr("phone_hash").eq(query)
        )
        items = self._scan_all(self.people, filter_expression=expression, limit=limit)
        return [PersonRecord.model_validate(_from_dynamo(item)) for item in items]

    def save_responder(self, responder: ResponderRecord) -> None:
        self.responders.put_item(Item=self._item(responder))

    def get_responder(self, responder_id: str) -> ResponderRecord | None:
        item = self.responders.get_item(Key={"responder_id": responder_id}).get("Item")
        return ResponderRecord.model_validate(_from_dynamo(item)) if item else None

    def list_responders(self) -> list[ResponderRecord]:
        return [
            ResponderRecord.model_validate(_from_dynamo(item))
            for item in self._scan_all(self.responders, limit=500)
        ]

    def save_mission(self, mission: MissionRecord) -> None:
        self.missions.put_item(Item=self._item(mission))

    def get_mission(self, mission_id: str) -> MissionRecord | None:
        item = self.missions.get_item(Key={"mission_id": mission_id}).get("Item")
        return MissionRecord.model_validate(_from_dynamo(item)) if item else None

    def list_missions_for_team(self, team_id: str) -> list[MissionRecord]:
        items = self._scan_all(
            self.missions, filter_expression=Attr("team_id").eq(team_id), limit=500
        )
        return [MissionRecord.model_validate(_from_dynamo(item)) for item in items]

    def save_shelter(self, shelter: ShelterRecord) -> None:
        self.shelters.put_item(Item=self._item(shelter))

    def get_shelter(self, shelter_id: str) -> ShelterRecord | None:
        item = self.shelters.get_item(Key={"shelter_id": shelter_id}).get("Item")
        return ShelterRecord.model_validate(_from_dynamo(item)) if item else None

    def list_shelters(self) -> list[ShelterRecord]:
        return [
            ShelterRecord.model_validate(_from_dynamo(item))
            for item in self._scan_all(self.shelters, limit=1_000)
        ]

    def append_audit(self, event: AuditEvent) -> None:
        self.audit.put_item(
            Item=self._item(event), ConditionExpression="attribute_not_exists(event_id)"
        )


def build_repository(settings: Settings) -> Repository:
    if settings.storage_backend == "dynamodb":
        return DynamoRepository(settings)
    return MemoryRepository()
