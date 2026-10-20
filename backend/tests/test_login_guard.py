import pytest
from app.models import Guest
from app.services import login_guard
import bcrypt


@pytest.fixture(autouse=True)
def _reset():
    login_guard.reset()
    yield
    login_guard.reset()


@pytest.mark.asyncio
async def test_manager_login_gesperrt_nach_fehlversuchen(client):
    for _ in range(login_guard.MAX_FAILS_IDENT):
        r = await client.post("/api/auth/login", json={"email": "x@y.ch", "password": "falsch"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "x@y.ch", "password": "falsch"})
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_gast_login_gesperrt_und_andere_kennung_frei(client):
    for _ in range(login_guard.MAX_FAILS_IDENT):
        await client.post("/api/guest/login", json={"username": "anna", "password": "x"})
    r = await client.post("/api/guest/login", json={"username": "anna", "password": "x"})
    assert r.status_code == 429
    r = await client.post("/api/guest/login", json={"username": "bob", "password": "x"})
    assert r.status_code == 401


def test_erfolg_setzt_kennung_zurueck():
    for _ in range(3):
        login_guard.record_failure("1.2.3.4", "a")
    login_guard.record_success("a")
    assert not login_guard.is_blocked("9.9.9.9", "a")
