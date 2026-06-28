"""SpaceCaptain MCP Server — gibt Claude Zugriff auf FabLab-Funktionen."""
import os
import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

BACKEND_URL     = os.environ.get("BACKEND_URL", "http://backend:8000")
MCP_BACKEND_KEY = os.environ.get("MCP_BACKEND_KEY", "")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Prüft Authorization: Bearer <MCP_BACKEND_KEY> auf allen Requests."""
    async def dispatch(self, request, call_next):
        if not MCP_BACKEND_KEY:
            return Response("MCP_BACKEND_KEY nicht konfiguriert", status_code=503)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != MCP_BACKEND_KEY:
            return Response("Unauthorized", status_code=401)
        return await call_next(request)


mcp = FastMCP(
    "SpaceCaptain",
    host="0.0.0.0",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _h() -> dict:
    return {"X-MCP-Key": MCP_BACKEND_KEY}


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


if __name__ == "__main__":
    app = mcp.sse_app()
    app.add_middleware(BearerAuthMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=8080)
