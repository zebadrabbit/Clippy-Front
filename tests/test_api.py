"""
Test API endpoints.
"""
import json


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data["status"] == "healthy"
    assert "message" in data


def test_start_task(client):
    """Test starting a background task."""
    response = client.post("/api/tasks/start", json={"task_name": "test_task"})
    assert response.status_code == 200

    data = json.loads(response.data)
    assert "task_id" in data
    assert data["status"] == "started"
    assert data["message"] == "Task test_task started"


def test_get_task_status(client):
    """Test getting task status."""
    # Start a task first
    start_response = client.post("/api/tasks/start", json={"task_name": "test_task"})
    start_data = json.loads(start_response.data)
    task_id = start_data["task_id"]

    # Get task status
    response = client.get(f"/api/tasks/{task_id}")
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data["task_id"] == task_id
    assert "status" in data
