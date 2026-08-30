def create_case(client, citizen_headers, urgent_case_payload, key="request-0001"):
    return client.post(
        "/v1/cases",
        json=urgent_case_payload,
        headers={**citizen_headers, "Idempotency-Key": key},
    )


def test_urgent_case_is_persisted_before_ai(client, citizen_headers, urgent_case_payload):
    response = create_case(client, citizen_headers, urgent_case_payload)

    assert response.status_code == 201
    result = response.json()
    assert result["case"]["priority"] == "P1"
    assert result["case"]["processing_status"] == "rules_complete"
    assert "rising_water" in result["case"]["triage"]["reason_codes"]
    assert result["access_token"]


def test_idempotent_retry_returns_same_case(client, citizen_headers, urgent_case_payload):
    first = create_case(client, citizen_headers, urgent_case_payload).json()
    second = create_case(client, citizen_headers, urgent_case_payload).json()

    assert first["case"]["case_id"] == second["case"]["case_id"]
    assert first["access_token"] == second["access_token"]


def test_idempotency_key_cannot_be_reused_for_different_report(
    client, citizen_headers, urgent_case_payload
):
    create_case(client, citizen_headers, urgent_case_payload)
    changed = {**urgent_case_payload, "description": "Different emergency details"}

    response = create_case(client, citizen_headers, changed)

    assert response.status_code == 409


def test_case_requires_owner_or_access_token(client, citizen_headers, urgent_case_payload):
    created = create_case(client, citizen_headers, urgent_case_payload).json()
    case_id = created["case"]["case_id"]

    denied = client.get(
        f"/v1/cases/{case_id}",
        headers={"X-Actor-ID": "different-person", "X-Actor-Role": "citizen"},
    )
    allowed = client.get(
        f"/v1/cases/{case_id}",
        headers={
            "X-Actor-ID": "different-person",
            "X-Actor-Role": "citizen",
            "X-Case-Access-Token": created["access_token"],
        },
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_admin_case_list_is_role_protected(
    client, citizen_headers, coordinator_headers, urgent_case_payload
):
    create_case(client, citizen_headers, urgent_case_payload)

    assert client.get("/v1/admin/cases", headers=citizen_headers).status_code == 403
    response = client.get("/v1/admin/cases", headers=coordinator_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_local_media_upload_is_bounded_and_single_use(client, citizen_headers, urgent_case_payload):
    created = create_case(client, citizen_headers, urgent_case_payload).json()
    case_id = created["case"]["case_id"]
    content = b"small-image-payload"
    prepared = client.post(
        f"/v1/cases/{case_id}/media-upload",
        json={"file_name": "damage.jpg", "content_type": "image/jpeg", "size_bytes": len(content)},
        headers={**citizen_headers, "X-Case-Access-Token": created["access_token"]},
    )
    assert prepared.status_code == 200
    ticket = prepared.json()

    upload = client.put(
        ticket["upload_url"],
        content=content,
        headers=ticket["headers"],
    )
    second_upload = client.put(
        ticket["upload_url"],
        content=content,
        headers=ticket["headers"],
    )

    assert upload.status_code == 204
    assert second_upload.status_code == 403


def test_local_media_upload_rejects_invalid_content_length(
    client, citizen_headers, urgent_case_payload
):
    created = create_case(client, citizen_headers, urgent_case_payload).json()
    case_id = created["case"]["case_id"]
    content = b"small-image-payload"
    prepared = client.post(
        f"/v1/cases/{case_id}/media-upload",
        json={"file_name": "damage.jpg", "content_type": "image/jpeg", "size_bytes": len(content)},
        headers={**citizen_headers, "X-Case-Access-Token": created["access_token"]},
    ).json()

    response = client.put(
        prepared["upload_url"],
        content=content,
        headers={**prepared["headers"], "Content-Length": "not-a-number"},
    )

    assert response.status_code == 400


def test_coordinator_can_verify_and_override_priority(
    client, citizen_headers, coordinator_headers, urgent_case_payload
):
    case_id = create_case(client, citizen_headers, urgent_case_payload).json()["case"]["case_id"]

    verified = client.post(
        f"/v1/admin/cases/{case_id}/verify",
        headers=coordinator_headers,
        json={"verification_status": "corroborated", "reason": "Confirmed by field team"},
    )
    changed = client.post(
        f"/v1/admin/cases/{case_id}/priority",
        headers=coordinator_headers,
        json={"priority": "P0", "reason": "Water level increased rapidly"},
    )

    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert changed.status_code == 200
    assert changed.json()["priority"] == "P0"


def test_media_larger_than_configured_limit_is_rejected(
    client, citizen_headers, urgent_case_payload
):
    created = create_case(client, citizen_headers, urgent_case_payload).json()
    response = client.post(
        f"/v1/cases/{created['case']['case_id']}/media-upload",
        json={
            "file_name": "large.mp4",
            "content_type": "video/mp4",
            "size_bytes": 25_000_001,
        },
        headers={**citizen_headers, "X-Case-Access-Token": created["access_token"]},
    )

    assert response.status_code == 413
