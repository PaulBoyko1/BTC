from fastapi.testclient import TestClient
from starlette.routing import Mount

from app.interval_main import app


def test_interval_api_routes_precede_root_static_mount() -> None:
    assets_index = next(
        index
        for index, route in enumerate(app.router.routes)
        if getattr(route, "path", None) == "/api/interval/assets"
    )
    static_index = next(
        index
        for index, route in enumerate(app.router.routes)
        if isinstance(route, Mount) and route.name == "static"
    )

    assert assets_index < static_index


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
