"""SpaceCaptain MCP Server — gibt Claude Zugriff auf FabLab-Funktionen."""
import os
import httpx
from mcp.server.fastmcp import FastMCP

BACKEND_URL    = os.environ.get("BACKEND_URL", "http://backend:8000")
MCP_API_TOKEN  = os.environ.get("MCP_API_TOKEN", "")
MCP_BACKEND_KEY = os.environ.get("MCP_BACKEND_KEY", "")

mcp = FastMCP("SpaceCaptain")


def _headers() -> dict:
    return {"X-MCP-Key": MCP_BACKEND_KEY}


async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BACKEND_URL}/api/mcp{path}", headers=_headers())
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict = {}) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{BACKEND_URL}/api/mcp{path}", json=body, headers=_headers())
        r.raise_for_status()
        return r.json()


# ── Tools ──────────────────────────────────────────────────────────────────────

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
    """Letzten Aktivitätslog-Einträge (Standard: 20, max 100)."""
    limit = min(max(1, limit), 100)
    result = await _get(f"/log?limit={limit}")
    return result.get("logs", result)


@mcp.tool()
async def trigger_update() -> dict:
    """System-Update auslösen (git pull + Docker rebuild)."""
    return await _post("/update")


# ── Auth-Middleware ─────────────────────────────────────────────────────────────

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route


def _check_token(request: Request) -> bool:
    if not MCP_API_TOKEN:
        return False
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {MCP_API_TOKEN}"


async def handle_sse(request: Request) -> Response:
    if not _check_token(request):
        return Response("Unauthorized", status_code=401)
    sse = SseServerTransport("/mcp/messages/")
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await mcp._mcp_server.run(
            streams[0], streams[1], mcp._mcp_server.create_initialization_options()
        )
    return Response()


async def handle_messages(request: Request) -> Response:
    if not _check_token(request):
        return Response("Unauthorized", status_code=401)
    sse = SseServerTransport("/mcp/messages/")
    await sse.handle_post_message(request.scope, request.receive, request._send)
    return Response()


app = Starlette(routes=[
    Route("/sse",       handle_sse),
    Mount("/messages/", app=Starlette(routes=[Route("/{path:path}", handle_messages, methods=["POST"])])),
])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
