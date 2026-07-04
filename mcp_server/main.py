"""SpaceCaptain MCP Server — gibt Claude Zugriff auf FabLab-Funktionen.

Auth-Architektur:
- Port 8080 ist NUR im Docker-internen Netz / LAN erreichbar (nicht via nginx exponiert)
- Eigentliche Auth: Backend prüft X-MCP-Key gegen mcp_api_token in DB
- Token wird beim Start via Bootstrap-Call vom Backend geladen
"""
import os
import asyncio
import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

# Wird beim Start per Bootstrap-Call vom Backend geladen
_token: str = ""


mcp = FastMCP(
    "SpaceCaptain",
    host="0.0.0.0",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    stateless_http=True,
)


def _h() -> dict:
    return {"X-MCP-Key": _token}


async def _get(path: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BACKEND_URL}/api/mcp{path}", headers=_h())
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict = {}):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{BACKEND_URL}/api/mcp{path}", json=body, headers=_h())
        r.raise_for_status()
        return r.json()


async def _patch(path: str, body: dict = {}):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{BACKEND_URL}/api/mcp{path}", json=body, headers=_h())
        r.raise_for_status()
        return r.json()


# ── get_ ───────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_activity_log(
    limit: int | None = None,
    offset: int = 0,
    from_date: str | None = None,
    to_date: str | None = None,
    log_type: str | None = None,
) -> dict:
    """Aktivitätslog-Einträge. Kein Limit-Cap — voller Zugriff auf alle Einträge.
    limit: Einträge pro Seite (ohne Angabe: alle). offset: für Pagination.
    from_date / to_date: ISO-Datum (z.B. '2026-01-01'). log_type: Typ-Filter (z.B. 'session_start')."""
    params = f"?offset={offset}"
    if limit is not None:
        params += f"&limit={limit}"
    if from_date:
        params += f"&from_date={from_date}"
    if to_date:
        params += f"&to_date={to_date}"
    if log_type:
        params += f"&log_type={log_type}"
    return await _get(f"/log{params}")


@mcp.tool()
async def get_guest(guest_id: int) -> dict:
    """Einzelner Gast mit Berechtigungen und letzter Aktivität."""
    return await _get(f"/guests/{guest_id}")


@mcp.tool()
async def get_machine(machine_id: int) -> dict:
    """Einzelne Maschine mit laufender Session, Plug-Status und Wartungshistorie."""
    return await _get(f"/machines/{machine_id}")


@mcp.tool()
async def get_stats() -> dict:
    """Nutzungsstatistiken: Gäste, Maschinen, Sessions, Top-Maschinen nach Stunden."""
    return await _get("/stats")


@mcp.tool()
async def get_inventory_value() -> dict:
    """Gesamtwert des Maschinenparks (Summe Neuwert) für Buchhaltung/Versicherung, inkl. Währung."""
    return await _get("/inventory/value")


@mcp.tool()
async def get_session_stats(
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Zeitraum-Auswertung aller Sessions: Gesamtstunden, Durchschnittsdauer, Top-Maschinen, Top-Gäste.
    from_date / to_date als ISO-Datum (z.B. '2026-01-01'). Ohne Angabe: alle Sessions."""
    params = ""
    if from_date:
        params += f"?from_date={from_date}"
    if to_date:
        params += ("&" if params else "?") + f"to_date={to_date}"
    return await _get(f"/stats/sessions{params}")


@mcp.tool()
async def get_machine_stats(
    machine_id: int,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Detaillierte Auslastungsauswertung einer Maschine: Wochentrend, Top-Gäste, Avg-Dauer.
    from_date / to_date als ISO-Datum optional."""
    params = ""
    if from_date:
        params += f"?from_date={from_date}"
    if to_date:
        params += ("&" if params else "?") + f"to_date={to_date}"
    return await _get(f"/stats/machines/{machine_id}{params}")


@mcp.tool()
async def get_guest_stats(
    guest_id: int,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Aktivitätsprofil eines Gastes: genutzte Maschinen, Stunden pro Maschine, monatliche Aktivität.
    from_date / to_date als ISO-Datum optional."""
    params = ""
    if from_date:
        params += f"?from_date={from_date}"
    if to_date:
        params += ("&" if params else "?") + f"to_date={to_date}"
    return await _get(f"/stats/guests/{guest_id}{params}")


@mcp.tool()
async def get_status() -> dict:
    """Aktueller SpaceCaptain-Status: Raum offen/zu, Notfall-Alarm, ausstehende Gast-Anmeldungen, Wartung fällig."""
    return await _get("/status")


# ── list_ ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_announcements() -> list:
    """Alle Aushänge (aktiv und inaktiv)."""
    return await _get("/announcements")


@mcp.tool()
async def list_automations() -> list:
    """Alle Automationsregeln mit Bedingungen und Ziel-Maschinen."""
    return await _get("/automations")


@mcp.tool()
async def list_categories() -> list:
    """Alle Maschinenkategorien."""
    return await _get("/categories")


@mcp.tool()
async def list_locations() -> list:
    """Alle Maschinenstandorte."""
    return await _get("/locations")


@mcp.tool()
async def list_owners() -> list:
    """Alle Maschinen-Eigentümer."""
    return await _get("/owners")


@mcp.tool()
async def list_batteries() -> list:
    """Alle erfassten Akkus (Hersteller, Modell, Kaufdatum, Neupreis, Status)."""
    return await _get("/batteries")


@mcp.tool()
async def list_guest_permissions(guest_id: int) -> dict:
    """Maschinenberechtigungen eines Gastes anzeigen."""
    return await _get(f"/guests/{guest_id}/permissions")


@mcp.tool()
async def list_guests() -> list:
    """Alle Gäste mit Status (aktiv, gesperrt, ausstehend)."""
    return await _get("/guests")


@mcp.tool()
async def list_machines() -> list:
    """Alle Maschinen mit aktuellem Betriebsstatus (wer nutzt gerade welche Maschine)."""
    return await _get("/machines")


@mcp.tool()
async def list_queue() -> list:
    """Aktuelle Warteliste — wer wartet auf welche Maschine."""
    return await _get("/queue")


@mcp.tool()
async def list_maintenance_due() -> list:
    """Alle fälligen und warnenden Wartungsintervalle mit Maschinennamen und Details."""
    return await _get("/maintenance/due")


@mcp.tool()
async def list_plugs() -> list:
    """Plug-Pool mit zugewiesenen Maschinen."""
    return await _get("/plugs")


@mcp.tool()
async def list_notify_topics() -> list:
    """Alle konfigurierten ntfy Push-Nachrichten-Topics."""
    return await _get("/notify/topics")


@mcp.tool()
async def list_maintenance_history(machine_id: int, limit: int = 20) -> dict:
    """Wartungshistorie einer Maschine (neueste zuerst, max 100)."""
    return await _get(f"/maintenance/history?machine_id={machine_id}&limit={min(limit, 100)}")


@mcp.tool()
async def list_pending_guests() -> list:
    """Gäste, die auf Freischaltung warten."""
    return await _get("/guests/pending")


@mcp.tool()
async def list_users() -> list:
    """Alle Lab-Manager-Konten (Name, Username, Rolle)."""
    return await _get("/users")


# ── log_ ───────────────────────────────────────────────────────────────────────

@mcp.tool()
async def log_maintenance(
    interval_id: int | None = None,
    machine_id: int | None = None,
    name: str | None = None,
    notes: str = "",
) -> dict:
    """Wartung erfassen. Entweder interval_id (bevorzugt) oder machine_id + name angeben."""
    return await _post("/maintenance/record", {
        "interval_id": interval_id,
        "machine_id":  machine_id,
        "name":        name,
        "notes":       notes,
    })


# ── create_ / delete_ / update_ ────────────────────────────────────────────────

@mcp.tool()
async def create_announcement(
    title: str,
    content: str,
    start_at: str,
    end_at: str,
) -> dict:
    """Aushang erstellen. start_at und end_at als ISO-8601 (z.B. '2026-06-29T08:00:00')."""
    return await _post("/announcements", {
        "title":    title,
        "content":  content,
        "start_at": start_at,
        "end_at":   end_at,
    })


@mcp.tool()
async def delete_announcement(announcement_id: int) -> dict:
    """Aushang löschen."""
    from mcp.server.fastmcp import Context
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.delete(f"{BACKEND_URL}/api/mcp/announcements/{announcement_id}", headers=_h())
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def update_announcement(
    announcement_id: int,
    text: str | None = None,
    is_active: bool | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    """Aushang bearbeiten. Nur angegebene Felder werden geändert."""
    body = {k: v for k, v in {"text": text, "is_active": is_active, "start_at": start_at, "end_at": end_at}.items() if v is not None}
    return await _patch(f"/announcements/{announcement_id}", body)


# ── end_ ───────────────────────────────────────────────────────────────────────

@mcp.tool()
async def end_session(machine_id: int) -> dict:
    """Laufende Session einer Maschine manuell beenden."""
    return await _post(f"/sessions/{machine_id}/end")


# ── send_ ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def send_notification(
    message: str,
    title: str = "SpaceCaptain",
    topic_id: int | None = None,
    topic_key: str | None = None,
    priority: str = "default",
) -> dict:
    """Push-Nachricht senden. topic_id oder topic_key erforderlich. priority: min/low/default/high/urgent."""
    return await _post("/notify", {
        "topic_id":  topic_id,
        "topic_key": topic_key,
        "title":     title,
        "message":   message,
        "priority":  priority,
    })


# ── set_ / switch_ ─────────────────────────────────────────────────────────────

@mcp.tool()
async def set_emergency(active: bool) -> dict:
    """Notfall-Alarm auslösen (active=True) oder beenden (active=False)."""
    return await _post("/emergency", {"active": active})


@mcp.tool()
async def set_guest_blocked(guest_id: int, blocked: bool) -> dict:
    """Gast sperren (blocked=True) oder entsperren (blocked=False)."""
    return await _patch(f"/guests/{guest_id}/block", {"blocked": blocked})


@mcp.tool()
async def set_machine_status(machine_id: int, status: str) -> dict:
    """Maschinenstatus setzen: 'online', 'offline' oder 'maintenance'."""
    return await _patch(f"/machines/{machine_id}/status", {"status": status})


@mcp.tool()
async def set_permission(guest_id: int, machine_id: int, grant: bool) -> dict:
    """Maschinenberechtigung vergeben (grant=True) oder entziehen (grant=False)."""
    return await _post(f"/guests/{guest_id}/permissions/{machine_id}", {"grant": grant})


@mcp.tool()
async def set_room(open: bool) -> dict:
    """Raum öffnen (open=True) oder schliessen (open=False)."""
    return await _post("/room", {"open": open})


@mcp.tool()
async def switch_plug(plug_id: int, action: str) -> dict:
    """Plug schalten: action = 'on' oder 'off'."""
    return await _post(f"/plugs/{plug_id}/switch", {"action": action})


@mcp.tool()
async def update_guest(guest_id: int, name: str | None = None, email: str | None = None) -> dict:
    """Gast-Stammdaten bearbeiten (name, email)."""
    body = {k: v for k, v in {"name": name, "email": email}.items() if v is not None}
    return await _patch(f"/guests/{guest_id}", body)


# ── trigger_ ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def trigger_backup() -> dict:
    """Manuelles Backup der Datenbank auslösen."""
    return await _post("/backup")


@mcp.tool()
async def trigger_restart_all() -> dict:
    """Alle Container (nginx, db, backend, MCP) ohne Rebuild neu starten."""
    return await _post("/restart-all")


@mcp.tool()
async def trigger_restart_backend() -> dict:
    """Backend (+ MCP-Server falls aktiv) ohne Rebuild neu starten."""
    return await _post("/restart-backend")


@mcp.tool()
async def trigger_update() -> dict:
    """System-Update auslösen (git pull + Docker rebuild)."""
    return await _post("/update")


# ── approve_ ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def approve_guest(guest_id: int) -> dict:
    """Gast-Registrierung freischalten."""
    return await _post(f"/guests/{guest_id}/approve")


async def _bootstrap() -> None:
    """Token beim Start vom Backend laden — wartet bis Backend bereit ist."""
    global _token
    for attempt in range(20):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{BACKEND_URL}/api/mcp/bootstrap-token")
                if r.status_code == 200:
                    _token = r.json()["token"]
                    print(f"MCP: Token geladen ({_token[:8]}...)", flush=True)
                    return
                print(f"MCP Bootstrap: HTTP {r.status_code}, retry in 3s...", flush=True)
        except Exception as e:
            print(f"MCP Bootstrap attempt {attempt + 1}/20: {e}, retry in 3s...", flush=True)
        await asyncio.sleep(3)
    raise RuntimeError("MCP: Token-Bootstrap fehlgeschlagen — Backend nicht erreichbar oder MCP deaktiviert")


if __name__ == "__main__":
    asyncio.run(_bootstrap())
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=8080)
