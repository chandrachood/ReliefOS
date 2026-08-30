def create_case(client, headers):
    response = client.post(
        "/v1/cases",
        headers={**headers, "Idempotency-Key": "assignment-case-1"},
        json={
            "case_type": "injured",
            "description": "Person with a serious leg injury",
            "location_description": "Community hall",
            "requested_assistance": ["medical", "evacuation"],
        },
    )
    return response.json()["case"]


def test_verified_responder_can_be_assigned(client, citizen_headers, coordinator_headers):
    case = create_case(client, citizen_headers)
    registered = client.post(
        "/v1/responders/register",
        headers=citizen_headers,
        json={
            "name": "Palakkad Medical Team",
            "responder_type": "rescue_team",
            "capabilities": ["medical", "evacuation_transport"],
        },
    ).json()
    responder_id = registered["responder_id"]

    client.post(f"/v1/admin/responders/{responder_id}/approve", headers=coordinator_headers)
    client.patch(
        f"/v1/responders/{responder_id}/availability",
        headers=coordinator_headers,
        json={"availability": "available"},
    )
    assignment = client.post(
        f"/v1/admin/cases/{case['case_id']}/assign",
        headers=coordinator_headers,
        json={"team_id": responder_id, "reason": "Closest approved medical team"},
    )

    assert assignment.status_code == 201
    mission = assignment.json()
    assert mission["status"] == "assigned"
    missions = client.get(
        f"/v1/responders/{responder_id}/missions", headers=coordinator_headers
    ).json()
    assert missions[0]["case_id"] == case["case_id"]

    update = client.post(
        f"/v1/missions/{mission['mission_id']}/status",
        headers={"X-Actor-ID": responder_id, "X-Actor-Role": "responder"},
        json={"status": "en_route", "note": "Boat team departed"},
    )
    assert update.status_code == 200
    assert update.json()["status"] == "en_route"


def test_offline_responder_cannot_be_assigned(client, citizen_headers, coordinator_headers):
    case = create_case(client, citizen_headers)
    responder = client.post(
        "/v1/responders/register",
        headers=citizen_headers,
        json={"name": "Offline Team", "responder_type": "rescue_team"},
    ).json()
    client.post(
        f"/v1/admin/responders/{responder['responder_id']}/approve",
        headers=coordinator_headers,
    )

    response = client.post(
        f"/v1/admin/cases/{case['case_id']}/assign",
        headers=coordinator_headers,
        json={"team_id": responder["responder_id"], "reason": "Test"},
    )

    assert response.status_code == 409


def test_nearby_shelters_are_sorted(client, coordinator_headers):
    for name, latitude in [("Near shelter", 10.79), ("Far shelter", 11.2)]:
        response = client.post(
            "/v1/admin/shelters",
            headers=coordinator_headers,
            json={
                "name": name,
                "latitude": latitude,
                "longitude": 76.65,
                "capacity": 100,
                "occupancy": 20,
            },
        )
        assert response.status_code == 201

    response = client.get("/v1/shelters/nearby?latitude=10.7867&longitude=76.6548&radius_km=100")

    assert response.status_code == 200
    shelters = response.json()
    assert [item["name"] for item in shelters] == ["Near shelter", "Far shelter"]


def test_responder_cannot_modify_another_responder(client, citizen_headers):
    responder = client.post(
        "/v1/responders/register",
        headers=citizen_headers,
        json={"name": "Team A", "responder_type": "rescue_team"},
    ).json()

    denied = client.patch(
        f"/v1/responders/{responder['responder_id']}/location",
        headers={"X-Actor-ID": "another-team", "X-Actor-Role": "responder"},
        json={"latitude": 10.8, "longitude": 76.6},
    )

    assert denied.status_code == 403


def test_shelter_occupancy_cannot_exceed_capacity(client, coordinator_headers):
    response = client.post(
        "/v1/admin/shelters",
        headers=coordinator_headers,
        json={
            "name": "Overfilled shelter",
            "latitude": 10.8,
            "longitude": 76.6,
            "capacity": 10,
            "occupancy": 11,
        },
    )

    assert response.status_code == 422
