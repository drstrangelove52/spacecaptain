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


@mcp.tool()
async def get_status() -> dict:
    """Aktueller SpaceCaptain-Status: Raum offen/zu, Notfall-Alarm, ausstehende Gast-Anmeldungen, Wartung fällig."""
    return await _get("/status")


@mcp.tool()
async def list_machines() -> list:
    """Alle Maschinen mit aktuellem Betriebsstatus (wer nutzt gerade welche Maschine)."""
    return await _get("/machines")


@mcp.tool()
async def set_room(open: bool) -> dict:
    """Raum öffnen (open=True) oder schliessen (open=False)."""
    return await _post("/room", {"open": open})


@mcp.tool()
async def list_pending_guests() -> list:
    """Gäste, die auf Freischaltung warten."""
    return await _get("/guests/pending")


@mcp.tool()
async def approve_guest(guest_id: int) -> dict:
    """Gast-Registrierung freischalten."""
    return await _post(f"/guests/{guest_id}/approve")


@mcp.tool()
async def get_activity_log(limit: int = 20) -> list:
    """Letzte Aktivitätslog-Einträge (Standard: 20, max 100)."""
    limit = min(max(1, limit), 100)
    result = await _get(f"/log?limit={limit}")
    return result.get("logs", result)


@mcp.tool()
async def trigger_update() -> dict:
    """System-Update auslösen (git pull + Docker rebuild)."""
    return await _post("/update")


@mcp.tool()
async def trigger_restart_backend() -> dict:
    """Backend (+ MCP-Server falls aktiv) ohne Rebuild neu starten."""
    return await _post("/restart-backend")


@mcp.tool()
async def trigger_restart_all() -> dict:
    """Alle Container (nginx, db, backend, MCP) ohne Rebuild neu starten."""
    return await _post("/restart-all")


@mcp.tool()
async def trigger_backup() -> dict:
    """Manuelles Backup der Datenbank auslösen."""
    return await _post("/backup")


# ── Wartung ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_maintenance_due() -> list:
    """Alle fälligen und warnenden Wartungsintervalle mit Maschinennamen und Details."""
    return await _get("/maintenance/due")


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


# ── Gäste ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_guests() -> list:
    """Alle Gäste mit Status (aktiv, gesperrt, ausstehend)."""
    return await _get("/guests")


@mcp.tool()
async def set_guest_blocked(guest_id: int, blocked: bool) -> dict:
    """Gast sperren (blocked=True) oder entsperren (blocked=False)."""
    return await _patch(f"/guests/{guest_id}/block", {"blocked": blocked})


@mcp.tool()
async def list_guest_permissions(guest_id: int) -> dict:
    """Maschinenberechtigungen eines Gastes anzeigen."""
    return await _get(f"/guests/{guest_id}/permissions")


@mcp.tool()
async def set_permission(guest_id: int, machine_id: int, grant: bool) -> dict:
    """Maschinenberechtigung vergeben (grant=True) oder entziehen (grant=False)."""
    return await _post(f"/guests/{guest_id}/permissions/{machine_id}", {"grant": grant})


# ── Maschinen ──────────────────────────────────────────────────────────────────

@mcp.tool()
async def set_machine_status(machine_id: int, status: str) -> dict:
    """Maschinenstatus setzen: 'online', 'offline' oder 'maintenance'."""
    return await _patch(f"/machines/{machine_id}/status", {"status": status})


# ── Notfall ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def set_emergency(active: bool) -> dict:
    """Notfall-Alarm auslösen (active=True) oder beenden (active=False)."""
    return await _post("/emergency", {"active": active})


# ── Push-Nachrichten ───────────────────────────────────────────────────────────

@mcp.tool()
async def list_notify_topics() -> list:
    """Alle konfigurierten ntfy Push-Nachrichten-Topics."""
    return await _get("/notify/topics")


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
