def test_person_search_exposes_only_public_safe_fields(client, citizen_headers):
    reported = client.post(
        "/v1/people/reports",
        headers=citizen_headers,
        json={
            "full_name": "Anjali Nair",
            "approximate_age": 34,
            "status": "safe",
            "last_confirmed_area": "Palakkad district",
            "phone": "+91 9000000001",
            "notes": "Sensitive internal note",
        },
    )
    assert reported.status_code == 201

    result = client.get("/v1/people/search?query=Anjali").json()[0]

    assert result["full_name"] == "Anjali Nair"
    assert "phone" not in result
    assert "notes" not in result


def test_public_cannot_claim_official_death(client, citizen_headers):
    response = client.post(
        "/v1/people/reports",
        headers=citizen_headers,
        json={"full_name": "Unknown person", "status": "deceased_verified"},
    )

    assert response.status_code == 403


def test_unverified_deceased_report_is_not_publicly_searchable(client, citizen_headers):
    response = client.post(
        "/v1/people/reports",
        headers=citizen_headers,
        json={"full_name": "Unknown recovery record", "status": "deceased_unverified"},
    )
    assert response.status_code == 201

    results = client.get("/v1/people/search?query=Unknown recovery").json()
    assert results == []
