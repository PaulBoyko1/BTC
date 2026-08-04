from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.interval_main import app


def test_root_static_mount_is_final_catch_all() -> None:
    final_route = app.router.routes[-1]

    assert isinstance(final_route, Mount)
    assert final_route.name == "static"


def test_interval_assets_endpoint_is_reachable() -> None:
    response = TestClient(app).get("/api/interval/assets")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert any(asset["symbol"] == "BTCUSDT" for asset in payload)


def test_root_static_page_remains_reachable() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Crypto Interval Analyzer" in response.text
