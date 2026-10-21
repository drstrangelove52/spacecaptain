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


@pytest.mark.asyncio
async def test_gast_token_per_header_statt_query(client, session_factory):
    from app.services.auth import bearer_or_query
    from app.routers.guest_auth import create_guest_token
    async with session_factory() as s:
        g = Guest(name="A", username="a", password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(), is_active=True)
        s.add(g)
        await s.commit()
        gid = g.id
    t = create_guest_token(gid)
    assert (await client.get("/api/guest/my")).status_code == 401
    assert (await client.get("/api/guest/my", headers={"Authorization": f"Bearer {t}"})).status_code == 200
    assert (await client.get(f"/api/guest/my?access_token={t}")).status_code == 200
    assert (await client.get("/api/queue/my", headers={"Authorization": f"Bearer {t}"})).status_code == 200
    assert bearer_or_query("Bearer abc", None) == "abc"


@pytest.mark.asyncio
async def test_manager_kann_gast_und_manager_entsperren(client, manager):
    for _ in range(login_guard.MAX_FAILS_IDENT):
        await client.post("/api/guest/login", json={"username": "anna", "password": "x"})
        await client.post("/api/auth/login", json={"email": "Chef@Test.ch", "password": "x"})
    assert (await client.post("/api/guest/login", json={"username": "anna", "password": "x"})).status_code == 429
    r = await client.get("/api/auth/lockouts", headers=manager)
    assert set(r.json()["idents"]) == {"g:anna", "chef@test.ch"}
    assert (await client.get("/api/auth/lockouts")).status_code == 401
    assert (await client.post("/api/auth/unlock", json={"kind": "guest", "value": "anna"}, headers=manager)).status_code == 200
    assert (await client.post("/api/auth/unlock", json={"kind": "user", "value": "Chef@Test.ch"}, headers=manager)).status_code == 200
    assert (await client.get("/api/auth/lockouts", headers=manager)).json() == {"idents": [], "ips": []}
    assert (await client.post("/api/guest/login", json={"username": "anna", "password": "x"})).status_code == 401
    assert (await client.post("/api/auth/unlock", json={"kind": "user", "value": "x"})).status_code == 401


@pytest.mark.asyncio
async def test_manager_darf_maschinenstatus_aendern_aber_nicht_bearbeiten(client, manager, power, db):
    from app.models import Machine
    m = Machine(name="Fräse", category="Sonstiges", qr_token="tok-fraese")
    db.add(m)
    await db.commit()
    r = await client.post(f"/api/machines/{m.id}/status", json={"status": "maintenance"}, headers=manager)
    assert r.status_code == 200 and r.json()["status"] == "maintenance"
    assert (await client.post(f"/api/machines/{m.id}/status", json={"status": "kaputt"}, headers=manager)).status_code == 422
    assert (await client.post(f"/api/machines/{m.id}/status", json={"status": "online"})).status_code == 401
    assert (await client.patch(f"/api/machines/{m.id}", json={"name": "X"}, headers=manager)).status_code == 403
