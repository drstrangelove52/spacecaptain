"""SpaceCaptain MCP Server — gibt Claude Zugriff auf FabLab-Funktionen."""
import os
import asyncio
import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import Response

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

# Wird beim Start per Bootstrap-Call vom Backend geladen
_token: str = ""


def _make_auth_app(inner):
    """Reines ASGI-Middleware — prüft Bearer-Token auf GET /sse.

    POST /messages/ wird nicht geprüft: Claude Code sendet den Authorization-Header
    nur auf dem initialen SSE-GET, nicht auf Folge-POSTs. Die Session-ID ist
    implizite Auth (nur nach erfolgreichem GET /sse erhältlich). Eigentliche
    Sicherheit liegt beim Backend-Check (X-MCP-Key).
    """
    async def auth_app(scope, receive, send):
        if scope["type"] == "http":
            method = scope.get("method", "")
            path = scope.get("path", "")
            if method != "POST" or not path.startswith("/messages"):
                headers = {k.lower(): v for k, v in scope.get("headers", [])}
                auth = headers.get(b"authorization", b"").decode()
                if not _token or not auth.startswith("Bearer ") or auth[7:] != _token:
                    resp = Response("Unauthorized", status_code=401)
                    await resp(scope, receive, send)
                    return
        await inner(scope, receive, send)
    return auth_app


mcp = FastMCP(
    "SpaceCaptain",
    host="0.0.0.0",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
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
    uvicorn.run(_make_auth_app(mcp.sse_app()), host="0.0.0.0", port=8080)
