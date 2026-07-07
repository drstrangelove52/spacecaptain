import secrets
import logging
import io
import csv
import base64
import qrcode
from datetime import datetime, date

log = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.services.auth import require_admin, require_power_manager

from app.database import get_db
from app.models import User, Machine, MachinePlug, Permission, LogType, MachineCategory, MachineLocation, MachineOwner
from app.models import Plug as PlugModel
from app.schemas import MachineCreate, MachineUpdate, MachineOut
from app.services.auth import get_current_user
from app.services import logger as log_svc
from app.services.plug import get_plug_status, switch_plug, switch_all_machine_plugs
from app.config import APP_TIMEZONE

def _local_iso(dt):
    if dt is None: return None
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(APP_TIMEZONE).isoformat()
from app.services.session import idle_since_global
from app.services.session import start_session, end_session, start_manager_session
from app.models import Guest, MachineSession, SessionEndedBy

router = APIRouter(prefix="/machines", tags=["machines"])


def _gen_qr_token() -> str:
    return secrets.token_urlsafe(32)


async def _machine_out(machine: Machine, db: AsyncSession) -> MachineOut:
    count_res = await db.execute(
        select(func.count()).where(Permission.machine_id == machine.id)
    )
    out = MachineOut.model_validate(machine)
    out.user_count = count_res.scalar() or 0
    out.current_guest_id   = machine.current_guest_id
    out.session_manager_id = machine.session_manager_id
    out.session_started_at = machine.session_started_at
    # Multi-Plug: alle zugewiesenen Plugs laden
    mp_res = await db.execute(
        select(PlugModel.id, PlugModel.name, PlugModel.plug_ip, PlugModel.plug_type)
        .join(MachinePlug, MachinePlug.plug_id == PlugModel.id)
        .where(MachinePlug.machine_id == machine.id)
        .order_by(MachinePlug.sort_order)
    )
    out.plugs = [{"id": r[0], "name": r[1], "plug_ip": r[2], "plug_type": r[3]} for r in mp_res.all()]
    if machine.owner_id:
        owner = await db.get(MachineOwner, machine.owner_id)
        out.owner_name = owner.name if owner else None
    return out


@router.get("", response_model=List[MachineOut])
async def list_machines(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).order_by(Machine.created_at.desc()))
    machines = result.scalars().all()
    return [await _machine_out(m, db) for m in machines]


@router.get("/live")
async def list_machines_live(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Gibt Maschinenlist mit aktiver Session-Info zurück (Gastnamen, Laufzeit, Plug-Status)."""
    result = await db.execute(select(Machine).order_by(Machine.created_at.desc()))
    machines = result.scalars().all()

    # Alle Gäste + Manager in einem Query laden
    guests_res = await db.execute(select(Guest))
    guest_map = {g.id: g.name for g in guests_res.scalars().all()}
    users_res = await db.execute(select(User))
    user_map = {u.id: u.name for u in users_res.scalars().all()}
    owners_res = await db.execute(select(MachineOwner))
    owner_map = {o.id: o.name for o in owners_res.scalars().all()}

    out = []
    for m in machines:
        try:
            count_res = await db.execute(select(func.count()).where(Permission.machine_id == m.id))
            user_count = count_res.scalar() or 0

            # Session-Info
            current_guest_name = guest_map.get(m.current_guest_id) if m.current_guest_id else None
            session_owner = None
            if m.current_guest_id:
                session_owner = current_guest_name
            elif m.session_manager_id:
                session_owner = user_map.get(m.session_manager_id, 'Unbekannt')
            elif m.session_started_at:
                # Keine guest_id, keine manager_id → kann nur Automation sein
                # (externe Plug-Detektionen setzen immer eine session_manager_id)
                session_owner = "Automation"
            session_duration_min = None
            if m.session_started_at:
                session_duration_min = round((datetime.utcnow() - m.session_started_at).total_seconds() / 60, 1)

            # Plug-Status (nur wenn konfiguriert)
            plug_info = {"on": None, "power_w": None, "supported": False}
            if m.plug_type != "none" and m.plug_ip:
                try:
                    plug_info = await get_plug_status(m)
                except Exception:
                    plug_info = {"on": None, "power_w": None, "supported": True, "error": "unreachable"}

            # Leerlauf-Status berechnen
            idle_state = None
            idle_since_min = None
            power_w = plug_info.get("power_w")
            session_age_sec = (
                (datetime.utcnow() - m.session_started_at).total_seconds()
                if m.session_started_at else 0
            )
            if (m.session_started_at and m.idle_power_w is not None
                    and m.idle_timeout_min is not None and power_w is not None
                    and session_age_sec >= 60):  # 60s Anlaufzeit nach Session-Start
                if power_w <= m.idle_power_w:
                    if m.id in idle_since_global:
                        idle_since_min = round(
                            (datetime.utcnow() - idle_since_global[m.id]).total_seconds() / 60, 1
                        )
                        remaining = m.idle_timeout_min - idle_since_min
                        idle_state = 'idle_warning' if remaining <= 2 else 'idle'
                    else:
                        idle_state = 'idle'
                else:
                    idle_state = 'active'

            mp_res = await db.execute(
                select(PlugModel.id, PlugModel.name, PlugModel.plug_ip, PlugModel.plug_type)
                .join(MachinePlug, MachinePlug.plug_id == PlugModel.id)
                .where(MachinePlug.machine_id == m.id)
                .order_by(MachinePlug.sort_order)
            )
            machine_plugs_list = [{"id": r[0], "name": r[1], "plug_ip": r[2], "plug_type": r[3]} for r in mp_res.all()]

            out.append({
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "manufacturer": m.manufacturer,
                "model": m.model,
                "serial_number": m.serial_number,
                "location": m.location,
                "status": m.status,
                "comment": m.comment,
                "safety_notes": m.safety_notes,
                "doc_url": m.doc_url,
                "plug_id": m.plug_id,
                "plug_type": m.plug_type,
                "plug_ip": m.plug_ip,
                "plug_token": m.plug_token,
                "plug_poll_interval_sec": m.plug_poll_interval_sec,
                "plugs": machine_plugs_list,
                "qr_token": m.qr_token,
                "user_count": user_count,
                "idle_power_w": m.idle_power_w,
                "idle_timeout_min": m.idle_timeout_min,
                "training_required": m.training_required,
                "force_off_on_close": m.force_off_on_close,
                "total_hours": round(m.total_hours or 0, 1),
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "purchase_date": m.purchase_date.isoformat() if m.purchase_date else None,
                "value_new": m.value_new,
                "owner_id": m.owner_id,
                "owner_name": owner_map.get(m.owner_id) if m.owner_id else None,
                # Session
                "in_use": m.session_started_at is not None,
                "current_guest_id": m.current_guest_id,
                "current_guest_name": session_owner or current_guest_name,
                "session_manager_id": m.session_manager_id,
                "session_started_at": _local_iso(m.session_started_at),
                "session_duration_min": session_duration_min,
                # Plug live
                "plug_on": plug_info.get("on"),
                "power_w": power_w,
                "plug_supported": plug_info.get("supported", False),
                "plug_error": plug_info.get("error"),
                # Leerlauf
                "idle_state": idle_state,
                "idle_since_min": idle_since_min,
            })
        except Exception as e:
            log.error(f"Live-Endpoint Fehler für Maschine {m.id}: {e}")
            # Nur Plug-Daten fehlen — Session-State aus DB korrekt zurückgeben
            out.append({
                "id": m.id, "name": m.name, "category": m.category,
                "manufacturer": m.manufacturer, "model": m.model, "serial_number": m.serial_number,
                "location": m.location, "status": m.status,
                "comment": m.comment, "safety_notes": m.safety_notes, "doc_url": m.doc_url, "plug_id": m.plug_id, "plug_type": m.plug_type,
                "plugs": [],
                "qr_token": m.qr_token,
                "user_count": 0,
                "idle_power_w": m.idle_power_w,
                "idle_timeout_min": m.idle_timeout_min,
                "training_required": m.training_required,
                "force_off_on_close": m.force_off_on_close,
                "total_hours": round(m.total_hours or 0, 1),
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "purchase_date": m.purchase_date.isoformat() if m.purchase_date else None,
                "value_new": m.value_new,
                "owner_id": m.owner_id,
                "owner_name": owner_map.get(m.owner_id) if m.owner_id else None,
                "in_use": m.session_started_at is not None,
                "current_guest_id": m.current_guest_id,
                "current_guest_name": None,
                "session_manager_id": m.session_manager_id,
                "session_started_at": _local_iso(m.session_started_at),
                "session_duration_min": None,
                "plug_on": None, "power_w": None,
                "plug_supported": True, "plug_error": "unreachable",
                "idle_state": None, "idle_since_min": None,
            })
    return out


@router.post("", response_model=MachineOut)
async def create_machine(
    payload: MachineCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    dup = await db.execute(select(Machine).where(Machine.name == payload.name))
    if dup.scalar_one_or_none():
        raise HTTPException(400, f"Maschinen-Name '{payload.name}' bereits vergeben")
    machine = Machine(**payload.model_dump(), qr_token=_gen_qr_token())
    db.add(machine)
    await db.commit()
    await db.refresh(machine)
    await log_svc.log(
        db, LogType.machine_created,
        f"Maschine {machine.name} ({machine.category}) hinzugefügt",
        machine_id=machine.id, user_id=current.id
    )
    return await _machine_out(machine, db)


@router.get("/{machine_id}", response_model=MachineOut)
async def get_machine(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    return await _machine_out(machine, db)


@router.patch("/{machine_id}", response_model=MachineOut)
async def update_machine(
    machine_id: int,
    payload: MachineUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Maschine nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        dup = await db.execute(select(Machine).where(Machine.name == changes["name"], Machine.id != machine_id))
        if dup.scalar_one_or_none():
            raise HTTPException(400, f"Maschinen-Name '{changes['name']}' bereits vergeben")
    for field, value in changes.items():
        setattr(machine, field, value)
    await db.commit()
    await db.refresh(machine)
    await log_svc.log(db, LogType.machine_updated,
                      f"Maschine {machine.name} bearbeitet",
                      machine_id=machine.id, user_id=current.id,
                      meta={"changed": list(changes.keys())})
    return await _machine_out(machine, db)


@router.delete("/{machine_id}")
async def delete_machine(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    await log_svc.log(db, LogType.machine_deleted, f"Maschine {machine.name} gelöscht", user_id=current.id)
    await db.delete(machine)
    await db.commit()
    return {"ok": True}


@router.post("/{machine_id}/regenerate-qr", response_model=MachineOut)
async def regenerate_qr(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    """Neuen QR-Token für die Maschine generieren (invalidiert alte QR-Codes)."""
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    machine.qr_token = _gen_qr_token()
    await db.commit()
    await db.refresh(machine)
    return await _machine_out(machine, db)


@router.get("/{machine_id}/qr.png")
async def get_qr_image(
    machine_id: int,
    request: Request,
    token: str = None,  # Query param fallback für <img> tags
    db: AsyncSession = Depends(get_db),
):
    # Auth: entweder Bearer Header oder ?token= Query-Param
    from app.services.auth import get_settings as _gs
    from jose import jwt as _jwt
    settings = _gs()
    auth_token = token
    if not auth_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            auth_token = auth_header[7:]
    if not auth_token:
        raise HTTPException(401, "Nicht authentifiziert")
    try:
        _jwt.decode(auth_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        raise HTTPException(401, "Ungültiger Token")

    """Gibt das QR-Code Bild als PNG zurück (zum Drucken)."""
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")

    # QR-Code enthält die vollständige Gäste-URL
    # Der Hostname wird aus dem Request-Header ermittelt
    base_url = str(request.base_url).rstrip("/")
    guest_url = f"{base_url}/?m={machine.qr_token}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(guest_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="qr_{machine_id}.png"'},
    )


@router.get("/{machine_id}/plug-status")
async def plug_status(
    machine_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    status = await get_plug_status(machine)
    # Aktiven Gast hinzufügen
    current_guest_name = None
    if machine.current_guest_id:
        g = await db.get(Guest, machine.current_guest_id)
        current_guest_name = g.name if g else None
    session_duration_min = None
    if machine.session_started_at:
        session_duration_min = round((datetime.utcnow() - machine.session_started_at).total_seconds() / 60, 1)
    return {
        **status,
        "current_guest_name": current_guest_name,
        "current_guest_id": machine.current_guest_id,
        "session_started_at": _local_iso(machine.session_started_at),
        "session_duration_min": session_duration_min,
    }


@router.post("/{machine_id}/switch")
async def manager_switch(
    machine_id: int,
    action: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Manager kann Maschine direkt ein/ausschalten."""
    result = await db.execute(select(Machine).where(Machine.id == machine_id))
    machine = result.scalar_one_or_none()
    if not machine:
        raise HTTPException(404, "Nicht gefunden")
    if action not in ("on", "off"):
        raise HTTPException(400, "action muss 'on' oder 'off' sein")

    # Energie VOR dem Ausschalten messen (danach liefert der Plug 0W)
    energy_wh = None
    if action == "off" and machine.session_started_at:
        pre_status = await get_plug_status(machine)
        if pre_status.get("power_w") is not None and pre_status["power_w"] > 0:
            duration_h = (datetime.utcnow() - machine.session_started_at).total_seconds() / 3600
            energy_wh = round(pre_status["power_w"] * duration_h, 3)

    ok, msg = await switch_all_machine_plugs(machine, action, db)

    if ok:
        if action == "on":
            try:
                await start_manager_session(db, machine, current.id)
            except Exception as e:
                log.error(f"start_manager_session Fehler: {e}", exc_info=True)
                raise HTTPException(500, f"Session-Start fehlgeschlagen: {str(e)}")
        else:
            await end_session(db, machine, ended_by=SessionEndedBy.manager, energy_wh=energy_wh)

    log_type = LogType.plug_on if action == "on" else LogType.plug_off
    await log_svc.log(db, log_type if ok else LogType.error,
        f"Manager {'EIN' if action == 'on' else 'AUS'}: {machine.name} — {msg}",
        machine_id=machine.id, user_id=current.id)

    return {"ok": ok, "action": action, "machine": machine.name, "message": msg}


# ── CSV-Import ────────────────────────────────────────────────────────────────

_STATUS_MAP = {
    "online": "online", "offline": "offline",
    "maintenance": "maintenance", "wartung": "maintenance",
    # Neue Bezeichnungen im UI (Freigegeben/Gesperrt/In Wartung statt Online/Offline/Wartung)
    "freigegeben": "online", "gesperrt": "offline", "in wartung": "maintenance",
}

def _parse_csv_row(row: dict, existing_names: set[str], existing_by_id: dict[int, str], row_nr: int) -> dict:
    """Validiert eine CSV-Zeile und gibt ein result-dict zurück.

    Action-Ermittlung: Passt die ID-Spalte zu einer vorhandenen Maschine, wird
    die Zeile als "update"-Kandidat markiert (angewendet nur wenn der Import
    mit aktivierter "Bestehende aktualisieren"-Option bestätigt wird). Ohne
    ID-Match: neuer Name -> "import", vorhandener Name -> "skip" (wie bisher).
    """
    name = (row.get("Name") or "").strip()
    if not name:
        return {"row": row_nr, "action": "error", "reason": "Name fehlt"}

    machine_id = None
    id_raw = (row.get("ID") or "").strip()
    if id_raw.isdigit():
        machine_id = int(id_raw)
    existing_name_for_id = existing_by_id.get(machine_id) if machine_id is not None else None

    status_raw = (row.get("Status") or "online").strip().lower()
    status = _STATUS_MAP.get(status_raw, "online")

    schulung = (row.get("Schulung") or "Ja").strip().lower()
    training = schulung not in ("nein", "no", "false", "0")

    purchase_date = (row.get("Kaufdatum") or "").strip() or None
    if purchase_date:
        try:
            date.fromisoformat(purchase_date)
        except ValueError:
            purchase_date = None

    value_new_raw = (row.get("Neuwert") or "").strip()
    value_new = None
    if value_new_raw:
        try:
            value_new = float(value_new_raw.replace(",", "."))
        except ValueError:
            value_new = None

    if machine_id is not None and existing_name_for_id is not None:
        if name != existing_name_for_id and name in existing_names:
            action, reason = "error", f"Name '{name}' bereits von anderer Maschine belegt"
        else:
            action, reason = "update", None
    elif name in existing_names:
        action, reason = "skip", "Bereits vorhanden"
    else:
        action, reason = "import", None

    return {
        "row": row_nr,
        "id": machine_id,
        "name": name,
        "category": (row.get("Kategorie") or "Sonstiges").strip() or "Sonstiges",
        "manufacturer": (row.get("Hersteller") or "").strip() or None,
        "model": (row.get("Modell") or "").strip() or None,
        "serial_number": (row.get("Seriennummer") or "").strip() or None,
        "location": (row.get("Standort") or "").strip() or None,
        "status": status,
        "training_required": training,
        "comment": (row.get("Kommentar") or "").strip() or None,
        "purchase_date": purchase_date,
        "value_new": value_new,
        "owner": (row.get("Eigentümer") or "").strip() or None,
        "action": action,
        "reason": reason,
    }


@router.post("/import/preview")
async def import_machines_preview(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # strips BOM if present
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames or "Name" not in reader.fieldnames:
        raise HTTPException(400, "Ungültiges CSV-Format — Spalte 'Name' nicht gefunden")

    res = await db.execute(select(Machine.id, Machine.name))
    rows_db = res.all()
    existing_names = {r[1] for r in rows_db}
    existing_by_id = {r[0]: r[1] for r in rows_db}

    rows = []
    for i, row in enumerate(reader, start=2):
        rows.append(_parse_csv_row(row, existing_names, existing_by_id, i))

    to_import = sum(1 for r in rows if r["action"] == "import")
    to_update = sum(1 for r in rows if r["action"] == "update")
    skipped   = sum(1 for r in rows if r["action"] == "skip")
    errors    = sum(1 for r in rows if r["action"] == "error")

    return {
        "total": len(rows),
        "to_import": to_import,
        "to_update": to_update,
        "skipped": skipped,
        "errors": errors,
        "rows": rows,
    }


@router.post("/import/confirm")
async def import_machines_confirm(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_power_manager),
):
    rows = payload.get("rows", [])
    if not rows:
        raise HTTPException(400, "Keine Zeilen übergeben")
    update_existing = bool(payload.get("update_existing", False))

    res = await db.execute(select(Machine.id, Machine.name))
    rows_db = res.all()
    existing_names = {r[1] for r in rows_db}
    existing_by_id = {r[0]: r[1] for r in rows_db}

    # Fehlende Kategorien, Standorte und Eigentümer automatisch anlegen
    # (Update-Zeilen nur wenn Update tatsächlich bestätigt wurde — sonst
    # würden unnötig Lookup-Einträge für verworfene Zeilen entstehen)
    relevant_rows = [
        r for r in rows
        if r.get("action") == "import" or (r.get("action") == "update" and update_existing)
    ]
    # select(Model.column) + .scalars() liefert bereits die rohen Werte (Strings),
    # nicht Model-Instanzen - .name waere hier ein AttributeError auf str.
    existing_cats = set((await db.execute(select(MachineCategory.name))).scalars().all())
    existing_locs = set((await db.execute(select(MachineLocation.name))).scalars().all())
    existing_owner_names = set((await db.execute(select(MachineOwner.name))).scalars().all())
    for row in relevant_rows:
        cat = (row.get("category") or "Sonstiges").strip() or "Sonstiges"
        if cat not in existing_cats:
            db.add(MachineCategory(name=cat, icon="🔧", sort_order=len(existing_cats)))
            existing_cats.add(cat)
        loc = (row.get("location") or "").strip() or None
        if loc and loc not in existing_locs:
            db.add(MachineLocation(name=loc, sort_order=len(existing_locs)))
            existing_locs.add(loc)
        owner = (row.get("owner") or "").strip() or None
        if owner and owner not in existing_owner_names:
            db.add(MachineOwner(name=owner, sort_order=len(existing_owner_names)))
            existing_owner_names.add(owner)
    await db.flush()
    owner_id_map = {o.name: o.id for o in (await db.execute(select(MachineOwner))).scalars().all()}

    imported = 0
    updated  = 0
    skipped  = 0
    from app.models import MachineStatus

    for row in rows:
        action = row.get("action")
        name = (row.get("name") or "").strip()
        status_val = row.get("status", "online")
        try:
            status_enum = MachineStatus(status_val)
        except ValueError:
            status_enum = MachineStatus.online
        purchase_date = row.get("purchase_date")

        if action == "import":
            if not name or name in existing_names:
                skipped += 1
                continue
            machine = Machine(
                name=name,
                category=row.get("category") or "Sonstiges",
                manufacturer=row.get("manufacturer"),
                model=row.get("model"),
                serial_number=row.get("serial_number"),
                location=row.get("location"),
                status=status_enum,
                training_required=bool(row.get("training_required", True)),
                comment=row.get("comment"),
                qr_token=_gen_qr_token(),
                purchase_date=date.fromisoformat(purchase_date) if purchase_date else None,
                value_new=row.get("value_new"),
                owner_id=owner_id_map.get(row.get("owner")) if row.get("owner") else None,
            )
            db.add(machine)
            existing_names.add(name)
            imported += 1

        elif action == "update":
            if not update_existing:
                skipped += 1
                continue
            machine_id = row.get("id")
            current_name = existing_by_id.get(machine_id)
            if machine_id is None or current_name is None:
                skipped += 1
                continue
            if name != current_name and name in existing_names:
                skipped += 1
                continue
            machine = await db.get(Machine, machine_id)
            if not machine:
                skipped += 1
                continue
            if name != current_name:
                existing_names.discard(current_name)
                existing_names.add(name)
                existing_by_id[machine_id] = name
            machine.name = name
            machine.category = row.get("category") or "Sonstiges"
            machine.manufacturer = row.get("manufacturer")
            machine.model = row.get("model")
            machine.serial_number = row.get("serial_number")
            machine.location = row.get("location")
            machine.status = status_enum
            machine.training_required = bool(row.get("training_required", True))
            machine.comment = row.get("comment")
            machine.purchase_date = date.fromisoformat(purchase_date) if purchase_date else None
            machine.value_new = row.get("value_new")
            machine.owner_id = owner_id_map.get(row.get("owner")) if row.get("owner") else None
            updated += 1

        else:
            skipped += 1

    await db.commit()

    if imported > 0 or updated > 0:
        await log_svc.log(
            db, LogType.machine_created if imported else LogType.machine_updated,
            f"CSV-Import: {imported} Maschine(n) importiert, {updated} aktualisiert, {skipped} übersprungen",
            user_id=current.id,
        )

    return {"imported": imported, "updated": updated, "skipped": skipped}
