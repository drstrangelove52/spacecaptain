import asyncio
from types import SimpleNamespace
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models import Plug, Machine, MachinePlug, SystemSettings, User, PlugType, LogType, PlugScanExclusion
from app.schemas import PlugCreate, PlugUpdate, PlugOut
from app.services.auth import get_current_user, require_power_manager
from app.services.plug import switch_plug, discover_devices, set_plug_auth, generate_password, clear_plug_auth, get_plug_status
from app.services import logger as log_svc

router = APIRouter(prefix="/plugs", tags=["plugs"])

LIVE_STATUS_CONCURRENCY = 20

VALID_TYPES = {"mystrom", "shelly", "shelly_gen2"}


async def _plug_out(plug: Plug, db: AsyncSession) -> dict:
    res = await db.execute(
        select(Machine.id, Machine.name)
        .join(MachinePlug, MachinePlug.machine_id == Machine.id)
        .where(MachinePlug.plug_id == plug.id)
        .order_by(MachinePlug.sort_order)
    )
    machines = [{"id": r[0], "name": r[1]} for r in res.all()]

    # Notfall-Alarm: Sirene / Blinklicht ebenfalls anzeigen
    cfg_res = await db.execute(select(SystemSettings).where(SystemSettings.id == 1))
    cfg = cfg_res.scalar_one_or_none()
    if cfg:
        if cfg.emergency_plug_id == plug.id:
            machines.append({"id": None, "name": "🚨 Sirene"})
        if cfg.emergency_plug2_id == plug.id:
            machines.append({"id": None, "name": "🚨 Blinklicht"})

    return {
        "id": plug.id,
        "name": plug.name,
        "plug_type": plug.plug_type,
        "plug_ip": plug.plug_ip,
        "plug_token": plug.plug_token,
        "mac": plug.mac,
        "notes": plug.notes,
        "created_at": plug.created_at,
        "machines": machines,
    }


@router.get("", response_model=List[PlugOut])
async def list_plugs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Plug).order_by(Plug.created_at.desc()))
    plugs = result.scalars().all()
    return [await _plug_out(p, db) for p in plugs]


@router.get("/live-status")
async def get_plugs_live_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Fragt den tatsaechlichen Ein/Aus-Zustand aller Plugs live ab — bewusst
    kein Hintergrund-Polling, sondern eine einmalige Momentaufnahme, ausgeloest
    durch den Seitenaufruf/Klick auf Aktualisieren im Plug-Pool. Erkennt auch
    Plugs, die ausserhalb von SpaceCaptain geschaltet wurden."""
    result = await db.execute(select(Plug))
    plugs = result.scalars().all()
    sem = asyncio.Semaphore(LIVE_STATUS_CONCURRENCY)

    async def _one(plug: Plug):
        async with sem:
            proxy = SimpleNamespace(plug_type=plug.plug_type, plug_ip=plug.plug_ip, plug_token=plug.plug_token)
            status = await get_plug_status(proxy)
            return plug.id, status

    results = await asyncio.gather(*(_one(p) for p in plugs))
    return {str(pid): status for pid, status in results}


@router.post("", response_model=PlugOut)
async def create_plug(
    payload: PlugCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    if payload.plug_type not in VALID_TYPES:
        raise HTTPException(400, f"plug_type muss einer von {sorted(VALID_TYPES)} sein")
    dup = await db.execute(select(Plug).where(Plug.name == payload.name))
    if dup.scalar_one_or_none():
        raise HTTPException(400, f"Plug-Name '{payload.name}' bereits vergeben")
    plug = Plug(**payload.model_dump())
    db.add(plug)
    await db.commit()
    await db.refresh(plug)
    await log_svc.log(db, LogType.plug_created, f"Plug {plug.name} hinzugefügt", user_id=current.id)
    return await _plug_out(plug, db)


@router.patch("/{plug_id}", response_model=PlugOut)
async def update_plug(
    plug_id: int,
    payload: PlugUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    if "plug_type" in changes and changes["plug_type"] not in VALID_TYPES:
        raise HTTPException(400, f"plug_type muss einer von {sorted(VALID_TYPES)} sein")
    if "name" in changes:
        dup = await db.execute(select(Plug).where(Plug.name == changes["name"], Plug.id != plug_id))
        if dup.scalar_one_or_none():
            raise HTTPException(400, f"Plug-Name '{changes['name']}' bereits vergeben")
    for field, value in changes.items():
        setattr(plug, field, value)
    # Sync IP/token/type auf alle Maschinen wo dieser Plug PRIMÄR ist (sort_order=0)
    if any(f in changes for f in ("plug_ip", "plug_token", "plug_type")):
        mres = await db.execute(
            select(Machine)
            .join(MachinePlug, MachinePlug.machine_id == Machine.id)
            .where(MachinePlug.plug_id == plug_id, MachinePlug.sort_order == 0)
        )
        for m in mres.scalars().all():
            if "plug_ip"    in changes: m.plug_ip    = plug.plug_ip
            if "plug_token" in changes: m.plug_token = plug.plug_token
            if "plug_type"  in changes: m.plug_type  = PlugType(plug.plug_type)
    await db.commit()
    await db.refresh(plug)
    await log_svc.log(db, LogType.plug_updated, f"Plug {plug.name} bearbeitet",
                      user_id=current.id, meta={"changed": list(changes.keys())})
    return await _plug_out(plug, db)


@router.delete("/{plug_id}")
async def delete_plug(
    plug_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalars().first()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")
    assigned = await db.execute(select(MachinePlug.id).where(MachinePlug.plug_id == plug_id))
    if assigned.scalars().first():
        raise HTTPException(400, "Plug ist noch Maschinen zugewiesen — zuerst alle Zuweisungen aufheben")
    await log_svc.log(db, LogType.plug_deleted, f"Plug {plug.name} gelöscht", user_id=current.id)
    await db.delete(plug)
    await db.commit()
    return {"ok": True}


@router.post("/{plug_id}/assign")
async def assign_plug(
    plug_id: int,
    machine_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")

    mres = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = mres.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")

    # Idempotent: schon zugewiesen?
    existing = await db.execute(
        select(MachinePlug).where(MachinePlug.machine_id == machine_id, MachinePlug.plug_id == plug_id)
    )
    if existing.scalar_one_or_none():
        return {"ok": True}

    # sort_order bestimmen
    max_res = await db.execute(
        select(func.max(MachinePlug.sort_order)).where(MachinePlug.machine_id == machine_id)
    )
    max_order = max_res.scalar()
    sort_order = 0 if max_order is None else max_order + 1

    db.add(MachinePlug(machine_id=machine_id, plug_id=plug_id, sort_order=sort_order))

    # Primär-Plug: Machine-Felder aktualisieren
    if sort_order == 0:
        machine.plug_id    = plug_id
        machine.plug_type  = PlugType(plug.plug_type)
        machine.plug_ip    = plug.plug_ip
        machine.plug_token = plug.plug_token

    await db.commit()
    await log_svc.log(db, LogType.plug_assigned, f"Plug {plug.name} → {machine.name} zugewiesen",
                      machine_id=machine.id, user_id=current.id)
    return {"ok": True}


@router.post("/{plug_id}/unassign")
async def unassign_plug(
    plug_id: int,
    machine_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")

    target_machine_name = None
    if machine_id:
        tres = await db.execute(select(Machine.name).where(Machine.id == machine_id))
        target_machine_name = tres.scalar_one_or_none()

    if machine_id:
        mp_res = await db.execute(
            select(MachinePlug).where(MachinePlug.machine_id == machine_id, MachinePlug.plug_id == plug_id)
        )
        mp = mp_res.scalar_one_or_none()
        if mp:
            was_primary = (mp.sort_order == 0)
            await db.delete(mp)
            await db.flush()

            if was_primary:
                mres = await db.execute(select(Machine).where(Machine.id == machine_id))
                machine = mres.scalar_one_or_none()
                if machine:
                    # Nächsten Plug zum Primär-Plug befördern
                    next_res = await db.execute(
                        select(MachinePlug).where(MachinePlug.machine_id == machine_id)
                        .order_by(MachinePlug.sort_order)
                    )
                    next_mp = next_res.scalars().first()
                    if next_mp:
                        plug_res = await db.execute(select(Plug).where(Plug.id == next_mp.plug_id))
                        new_primary = plug_res.scalar_one_or_none()
                        next_mp.sort_order = 0
                        if new_primary:
                            machine.plug_id    = new_primary.id
                            machine.plug_type  = PlugType(new_primary.plug_type)
                            machine.plug_ip    = new_primary.plug_ip
                            machine.plug_token = new_primary.plug_token
                    else:
                        machine.plug_id    = None
                        machine.plug_type  = PlugType.none
                        machine.plug_ip    = None
                        machine.plug_token = None
    else:
        # Alle Zuweisungen dieses Plugs aufheben (Fallback)
        all_mp = (await db.execute(
            select(MachinePlug).where(MachinePlug.plug_id == plug_id)
        )).scalars().all()
        for mp in all_mp:
            if mp.sort_order == 0:
                mres = await db.execute(select(Machine).where(Machine.id == mp.machine_id))
                m = mres.scalar_one_or_none()
                if m:
                    # Prüfen ob andere Plugs vorhanden
                    other_res = await db.execute(
                        select(MachinePlug).where(
                            MachinePlug.machine_id == mp.machine_id,
                            MachinePlug.plug_id != plug_id
                        ).order_by(MachinePlug.sort_order)
                    )
                    other = other_res.scalars().first()
                    if not other:
                        m.plug_id = None; m.plug_type = PlugType.none
                        m.plug_ip = None; m.plug_token = None
            await db.delete(mp)

    await db.commit()
    msg = f"Plug {plug.name} entfernt von {target_machine_name}" if target_machine_name \
        else f"Plug {plug.name} von allen Maschinen entfernt"
    await log_svc.log(db, LogType.plug_unassigned, msg, user_id=current.id)
    return {"ok": True}


@router.post("/{plug_id}/switch")
async def test_switch_plug(
    plug_id: int,
    action: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    """Schaltet einen freien Plug zum Test — nur wenn noch keiner Maschine zugewiesen."""
    result = await db.execute(select(Plug).where(Plug.id == plug_id))
    plug = result.scalar_one_or_none()
    if not plug:
        raise HTTPException(404, "Plug nicht gefunden")

    assigned = await db.execute(select(MachinePlug.id).where(MachinePlug.plug_id == plug_id))
    if assigned.scalars().first():
        raise HTTPException(400, "Plug ist einer Maschine zugewiesen — Test nur für freie Plugs")

    if action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")

    proxy = SimpleNamespace(
        plug_type=plug.plug_type,
        plug_ip=plug.plug_ip,
        plug_token=plug.plug_token,
    )
    ok, msg = await switch_plug(proxy, action)
    log_type = (LogType.plug_on if action == "on" else LogType.plug_off) if ok else LogType.error
    await log_svc.log(db, log_type,
        f"Plug-Test {'EIN' if action == 'on' else 'AUS'}: {plug.name} — {msg}", user_id=current.id)
    return {"ok": ok, "message": msg}


class DiscoverRequest(BaseModel):
    cidr: str

@router.post("/discover")
async def discover_plugs(
    payload: DiscoverRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    """Scannt einen IP-Bereich nach myStrom/Shelly-Geraeten (aktiver HTTP-Probe, kein mDNS)."""
    try:
        found = await discover_devices(payload.cidr)
    except ValueError as e:
        raise HTTPException(400, str(e))

    existing = await db.execute(select(Plug.plug_ip))
    existing_ips = {ip for (ip,) in existing.all() if ip}

    excl = await db.execute(select(PlugScanExclusion.ip))
    excluded_ips = {ip for (ip,) in excl.all()}

    found = [d for d in found if d["ip"] not in excluded_ips]
    for device in found:
        device["already_registered"] = device["ip"] in existing_ips

    return {"cidr": payload.cidr, "found": found, "excluded_count": len(excluded_ips)}


class ExcludeRequest(BaseModel):
    ip: str
    mac: Optional[str] = None
    plug_type: Optional[str] = None
    name: Optional[str] = None

@router.post("/discover/exclude")
async def exclude_discovered_device(
    payload: ExcludeRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    """Blendet ein bei der Discovery gefundenes Geraet in kuenftigen Scans aus
    (z.B. Smart Plugs, die anderweitig im Netz genutzt werden)."""
    existing = await db.execute(select(PlugScanExclusion).where(PlugScanExclusion.ip == payload.ip))
    row = existing.scalar_one_or_none()
    if row:
        return {"ok": True, "id": row.id}
    row = PlugScanExclusion(ip=payload.ip, mac=payload.mac, plug_type=payload.plug_type, name=payload.name)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"ok": True, "id": row.id}


@router.get("/discover/exclusions")
async def list_scan_exclusions(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(PlugScanExclusion).order_by(PlugScanExclusion.created_at.desc()))
    rows = result.scalars().all()
    return [
        {"id": r.id, "ip": r.ip, "mac": r.mac, "plug_type": r.plug_type, "name": r.name, "note": r.note}
        for r in rows
    ]


@router.delete("/discover/exclusions/{exclusion_id}")
async def remove_scan_exclusion(
    exclusion_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(PlugScanExclusion).where(PlugScanExclusion.id == exclusion_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


class BulkAuthRequest(BaseModel):
    plug_ids: List[int]
    password: Optional[str] = None

@router.post("/bulk-set-auth")
async def bulk_set_plug_auth(
    payload: BulkAuthRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    """Setzt/aendert das Passwort auf mehreren Plugs gleichzeitig — ohne Angabe
    wird eines automatisch generiert und fuer den gesamten Batch verwendet."""
    if not payload.plug_ids:
        raise HTTPException(400, "Keine Plugs ausgewählt")

    if payload.password:
        password = payload.password.strip()
        if len(password) < 6:
            raise HTTPException(400, "Passwort muss mindestens 6 Zeichen haben")
    else:
        password = generate_password()

    results = []
    for plug_id in payload.plug_ids:
        res = await db.execute(select(Plug).where(Plug.id == plug_id))
        plug = res.scalar_one_or_none()
        if not plug:
            results.append({"id": plug_id, "name": None, "ok": False, "message": "Nicht gefunden"})
            continue

        proxy = SimpleNamespace(plug_type=plug.plug_type, plug_ip=plug.plug_ip, plug_token=plug.plug_token)
        ok, msg, new_token = await set_plug_auth(proxy, password)

        if ok:
            plug.plug_token = new_token
            # Sync auf alle Maschinen, wo dieser Plug PRIMÄR ist (sort_order=0) —
            # gleiches Muster wie beim regulaeren PATCH /plugs/{id}
            mres = await db.execute(
                select(Machine)
                .join(MachinePlug, MachinePlug.machine_id == Machine.id)
                .where(MachinePlug.plug_id == plug.id, MachinePlug.sort_order == 0)
            )
            for m in mres.scalars().all():
                m.plug_token = new_token

        results.append({"id": plug_id, "name": plug.name, "ok": ok, "message": msg})

    await db.commit()
    ok_count = sum(1 for r in results if r["ok"])
    await log_svc.log(db, LogType.plug_updated,
        f"Bulk-Passwortänderung: {ok_count}/{len(results)} Plugs erfolgreich",
        user_id=current.id, meta={"plug_ids": payload.plug_ids})

    return {"password": password, "results": results}


class BulkIdsRequest(BaseModel):
    plug_ids: List[int]

@router.post("/bulk-clear-auth")
async def bulk_clear_plug_auth(
    payload: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    """Entfernt das Passwort/Token auf mehreren Plugs gleichzeitig — Geraete
    sind danach wieder ohne Anmeldung erreichbar."""
    if not payload.plug_ids:
        raise HTTPException(400, "Keine Plugs ausgewählt")

    results = []
    for plug_id in payload.plug_ids:
        res = await db.execute(select(Plug).where(Plug.id == plug_id))
        plug = res.scalar_one_or_none()
        if not plug:
            results.append({"id": plug_id, "name": None, "ok": False, "message": "Nicht gefunden"})
            continue

        proxy = SimpleNamespace(plug_type=plug.plug_type, plug_ip=plug.plug_ip, plug_token=plug.plug_token)
        ok, msg = await clear_plug_auth(proxy)

        if ok:
            plug.plug_token = None
            mres = await db.execute(
                select(Machine)
                .join(MachinePlug, MachinePlug.machine_id == Machine.id)
                .where(MachinePlug.plug_id == plug.id, MachinePlug.sort_order == 0)
            )
            for m in mres.scalars().all():
                m.plug_token = None

        results.append({"id": plug_id, "name": plug.name, "ok": ok, "message": msg})

    await db.commit()
    ok_count = sum(1 for r in results if r["ok"])
    await log_svc.log(db, LogType.plug_updated,
        f"Bulk-Passwort entfernt: {ok_count}/{len(results)} Plugs erfolgreich",
        user_id=current.id, meta={"plug_ids": payload.plug_ids})

    return {"results": results}
