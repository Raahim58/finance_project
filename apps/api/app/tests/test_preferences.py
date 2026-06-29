def test_default_and_updated_preferences(client):
    signup = client.post(
        "/auth/signup",
        json={"email": "prefs@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    defaults = client.get("/settings/preferences", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json()["risk_tolerance"] == "balanced"
    assert defaults.json()["preferred_analysis_mode"] == "combined"

    updated = client.patch(
        "/settings/preferences",
        headers=headers,
        json={
            "risk_tolerance": "conservative",
            "investment_horizon": "medium-term",
            "preferred_analysis_mode": "fundamentals",
            "preferred_sectors": ["Banking", "Technology"],
            "followup_frequency": "minimally",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["risk_tolerance"] == "conservative"
    assert updated.json()["preferred_sectors"] == ["Banking", "Technology"]
