"""Inventar Etappe 3: oeffentliche Nur-Lese-Sicht fuer Gaeste (ohne Anmeldung)."""
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
    r = await client.get("/api/inventory-public/search", params={"q": "schutzbrille"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert [x["name"] for x in res] == ["Laserbrille"]
    assert res[0]["place"]["code"] == "LAS-M01-E01" and res[0]["place"]["path"] == "Laser › Tisch 1 › Ebene 1"
    kinds = sorted(x["type"] for x in (await client.get("/api/inventory-public/search", params={"q": "laser"})).json())
    assert kinds == ["furniture", "machine", "tool"]
    assert (await client.get("/api/inventory-public/search", params={"q": "linse"})).json() == []     # ausgemustert bleibt verborgen


async def test_public_code_view_lists_tools_and_machines(client, enabled, power, db):
    await _fill(client, power, db)
    r = (await client.get("/api/inventory-public/code/LAS-M01")).json()
    assert r["scope"] == "furniture" and [i["name"] for i in r["items"]] == ["Laserbrille", "Spiegel"]
    assert [m["name"] for m in r["machines"]] == ["Lasercutter"]
    lvl = (await client.get("/api/inventory-public/code/LAS-M01-E02")).json()
    assert [i["name"] for i in lvl["items"]] == ["Spiegel"] and lvl["machines"] == []
    assert (await client.get("/api/inventory-public/code/LAS")).json()["machines"][0]["name"] == "Lasercutter"
    assert (await client.get("/api/inventory-public/code/ZZZ")).status_code == 404


async def test_public_item_hides_scrapped_and_exposes_nothing_internal(client, enabled, power, db):
    await _fill(client, power, db)
    items = (await client.get("/api/inventory/items", headers=power)).json()["items"]
    brille = [i for i in items if i["name"] == "Laserbrille"][0]
    alt = [i for i in items if i["name"] == "Alte Linse"][0]
    d = (await client.get(f"/api/inventory-public/items/{brille['id']}")).json()
    assert d["place"]["code"] == "LAS-M01-E01" and "position_id" not in str(d)
    assert (await client.get(f"/api/inventory-public/items/{alt['id']}")).status_code == 404


async def test_public_overview_and_switch(client, power, db):
    await _setup(db)
    assert (await client.get("/api/inventory-public/overview")).status_code == 404          # Modul aus
