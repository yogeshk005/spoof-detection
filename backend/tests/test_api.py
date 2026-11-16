from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_enrollment_and_verification_demo():
    credential = "TEST-BLINK-1001"
    start = client.post("/api/enrollment/start", json={
        "credential_id": credential, "display_name": "Demo User",
        "email": "demo@example.com"
    })
    assert start.status_code == 200
    session_id = start.json()["session_id"]
    done = client.post(f"/api/enrollment/{session_id}/complete")
    assert done.status_code == 200
    verify = client.post("/api/verification/start", json={"credential_id": credential})
    assert verify.status_code == 200
    result = client.post(f"/api/verification/{verify.json()['session_id']}/complete")
    assert result.status_code == 200
    assert result.json()["outcome"] in ["ALLOW", "REQUEST VERIFICATION", "DENY"]

def test_reenrollment_supersedes_open_session():
    credential = "TEST-BLINK-REENROLL"
    first = client.post("/api/enrollment/start", json={
        "credential_id": credential, "display_name": "First User",
        "email": "first@example.com"
    })
    assert first.status_code == 200
    second = client.post("/api/enrollment/start", json={
        "credential_id": credential, "display_name": "Updated User",
        "email": "updated@example.com"
    })
    assert second.status_code == 200
    stale = client.post(f"/api/enrollment/{first.json()['session_id']}/complete")
    assert stale.status_code == 404
    current = client.post(f"/api/enrollment/{second.json()['session_id']}/complete")
    assert current.status_code == 200
