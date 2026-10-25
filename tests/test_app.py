
import pytest

from app import app as flask_app


@pytest.fixture()
def client():
    flask_app.config.update(TESTING=True)

    with flask_app.test_client() as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200


def test_dashboard_loads(client):
    response = client.get("/")

    assert response.status_code == 200


def test_expenses_endpoint_returns_json(client):
    response = client.get("/api/expenses")

    assert response.status_code == 200
    assert response.is_json
    assert isinstance(response.get_json(), list)
