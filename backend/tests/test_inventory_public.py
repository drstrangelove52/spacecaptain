"""Inventar Etappe 3: oeffentliche Nur-Lese-Sicht fuer Gaeste (mit Anmeldung)."""
from tests.test_inventory_machines import _setup, _area_id, _machines


async def _fill(client, power, db):
    await _setup(db)
    laser = await _area_id(client, power, "Laser")
    t = (await client.post("/api/inventory/furniture", headers=power,
                           json={"area_id": laser, "kind": "tisch", "name": "Tisch 1", "levels": 2})).json()
    mk = lambda name, code, **kw: client.post("/api/inventory/items", headers=power, json={"name": name, "code": code, **kw})
    await mk("Laserbrille", "LAS-M01-E01", synonyms="Schutzbrille")
    await mk("Alte Linse", "LAS-M01-E01", status="ausgemustert")
    await mk("Spiegel", "LAS-M01-E02")
    mid = (await _machines(client, power))["Lasercutter"]["id"]
    await client.patch(f"/api/inventory/machines/{mid}", headers=power, json={"furniture_id": t["id"]})


async def test_public_search_needs_no_login(client, enabled, power, db):
    await _fill(client, power, db)
    r = await client.get("/api/inventory-public/search", headers=power, params={"q": "schutzbrille"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert [x["name"] for x in res] == ["Laserbrille"]
    assert res[0]["place"]["code"] == "LAS-M01-E01" and res[0]["place"]["path"] == "Laser › Tisch 1 › Ebene 1"
    kinds = sorted(x["type"] for x in (await client.get("/api/inventory-public/search", headers=power, params={"q": "laser"})).json())
    assert kinds == ["furniture", "machine", "tool"]
    assert (await client.get("/api/inventory-public/search", headers=power, params={"q": "linse"})).json() == []     # ausgemustert bleibt verborgen


async def test_public_code_view_lists_tools_and_machines(client, enabled, power, db):
    await _fill(client, power, db)
    r = (await client.get("/api/inventory-public/code/LAS-M01", headers=power)).json()
    assert r["scope"] == "furniture" and [i["name"] for i in r["items"]] == ["Laserbrille", "Spiegel"]
    assert [m["name"] for m in r["machines"]] == ["Lasercutter"]
    assert r["machines"][0]["code"] == "LAS-M01" and r["machines"][0]["id"]      # für den Plan-Link (Möbel markieren)
    lvl = (await client.get("/api/inventory-public/code/LAS-M01-E02", headers=power)).json()
    assert [i["name"] for i in lvl["items"]] == ["Spiegel"] and lvl["machines"] == []
    assert (await client.get("/api/inventory-public/code/LAS", headers=power)).json()["machines"][0]["name"] == "Lasercutter"
    assert (await client.get("/api/inventory-public/code/ZZZ", headers=power)).status_code == 404


async def test_public_item_hides_scrapped_and_exposes_nothing_internal(client, enabled, power, db):
    await _fill(client, power, db)
    items = (await client.get("/api/inventory/items", headers=power)).json()["items"]
    brille = [i for i in items if i["name"] == "Laserbrille"][0]
    alt = [i for i in items if i["name"] == "Alte Linse"][0]
    d = (await client.get(f"/api/inventory-public/items/{brille['id']}", headers=power)).json()
    assert d["place"]["code"] == "LAS-M01-E01" and "position_id" not in str(d)
    assert (await client.get(f"/api/inventory-public/items/{alt['id']}", headers=power)).status_code == 404


async def test_public_overview_and_switch(client, power, db):
    await _setup(db)
    assert (await client.get("/api/inventory-public/overview", headers=power)).status_code == 404          # Modul aus


async def test_public_needs_login_guest_or_manager(client, enabled, power, db, session_factory):
    from app.models import Guest
    from app.routers.guest_auth import create_guest_token
    await _fill(client, power, db)
    for path in ("/search?q=laser", "/overview", "/plan", "/code/LAS", "/plan/floors/1/background"):
        assert (await client.get("/api/inventory-public" + path)).status_code == 401, path
    assert (await client.get("/api/inventory-public/overview", headers={"Authorization": "Bearer kaputt"})).status_code == 401
    async with session_factory() as s:
        g = Guest(name="A", username="a", is_active=True)
        s.add(g)
        await s.commit()
        gid = g.id
    ok = {"Authorization": "Bearer " + create_guest_token(gid)}
    assert (await client.get("/api/inventory-public/overview", headers=ok)).status_code == 200
    async with session_factory() as s:
        (await s.get(Guest, gid)).is_active = False
        await s.commit()
    assert (await client.get("/api/inventory-public/overview", headers=ok)).status_code == 401      # deaktivierter Gast


async def test_guest_token_is_not_a_manager_token(client, admin, session_factory):
    """Ein Gast-JWT trägt die Gast-ID in `sub`; es darf nie als Lab-Manager mit derselben ID gelten."""
    from app.models import Guest
    from app.routers.guest_auth import create_guest_token
    async with session_factory() as s:
        g = Guest(name="A", username="a", is_active=True)
        s.add(g)
        await s.commit()
        gid = g.id
    r = await client.get("/api/users", headers={"Authorization": "Bearer " + create_guest_token(gid)})
    assert r.status_code == 401
    assert (await client.get("/api/users", headers=admin)).status_code == 200
