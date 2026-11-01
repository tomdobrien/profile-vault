from fastapi.testclient import TestClient
from app.main import app

def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "healthy"}

def test_profile_endpoint_returns_structured_empty_profile(tmp_path, monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "published_resume_path", str(tmp_path / "unpublished.json"))
    with TestClient(app) as client:
        response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == {"displayName": None, "headline": None, "introduction": None, "location": None, "contactEmail": None, "contactPhone": None, "experience": [], "selectedWork": [], "skills": [], "links": [], "awards": [], "education": []}
