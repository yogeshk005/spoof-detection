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
        "credential_id": credential, "display_name": "Demo User"
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
