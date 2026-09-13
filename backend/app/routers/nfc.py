"""
NFC-Schreibgerät Proxy
======================
Leitet Schreibaufträge an den ESP32 (PN532) im lokalen Netz weiter.
Der ESP32 wartet auf einen NFC-Tag und schreibt die URL als NDEF URI Record.
"""
import asyncio
import ipaddress
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth import get_current_user, require_admin
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/nfc", tags=["nfc"])

TIMEOUT = 5.0  # Sekunden für Status/Result-Abfragen
DISCOVERY_TIMEOUT = 1.5
DISCOVERY_MAX_ADDRESSES = 1024
DISCOVERY_CONCURRENCY = 40


async def _base_url(db: AsyncSession) -> str:
    s = await get_system_settings(db)
    url = (s.nfc_writer_url or "").strip().rstrip("/")
    if not url:
        raise HTTPException(503, "NFC-Schreibgerät nicht konfiguriert (URL in Einstellungen setzen)")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


class WriteRequest(BaseModel):
    url: str
    label: str = ""


@router.get("/status")
async def nfc_status(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Prüft ob das NFC-Schreibgerät erreichbar ist."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{await _base_url(db)}/status")
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "NFC-Schreibgerät nicht erreichbar")
    except httpx.TimeoutException:
        raise HTTPException(504, "NFC-Schreibgerät antwortet nicht")
    except httpx.RequestError as e:
        raise HTTPException(503, f"NFC-Schreibgerät Verbindungsfehler: {e}")


@router.post("/write")
async def nfc_write(payload: WriteRequest, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Startet einen Schreibauftrag auf dem ESP32."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                f"{await _base_url(db)}/write",
                json={"url": payload.url, "label": payload.label},
            )
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "NFC-Schreibgerät nicht erreichbar")
    except httpx.TimeoutException:
        raise HTTPException(504, "NFC-Schreibgerät antwortet nicht")
    except httpx.RequestError as e:
        raise HTTPException(503, f"NFC-Schreibgerät Verbindungsfehler: {e}")


@router.get("/result")
async def nfc_result(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    """Fragt das Ergebnis des letzten Schreibauftrags ab (zum Pollen)."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{await _base_url(db)}/result")
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "NFC-Schreibgerät nicht erreichbar")
    except httpx.TimeoutException:
        raise HTTPException(504, "NFC-Schreibgerät antwortet nicht")
    except httpx.RequestError as e:
        raise HTTPException(503, f"NFC-Schreibgerät Verbindungsfehler: {e}")


# ── Netzwerk-Discovery ───────────────────────────────────────────────────────
# Analog zur Plug-Discovery (services/plug.py): aktiver HTTP-Probe-Scan, kein
# mDNS (Multicast erreicht den Backend-Container im Docker-Bridge-Netz nicht).
# Der NFC-Writer identifiziert sich selbst eindeutig über sein /status ("device":
# "SpaceCaptain NFC Writer", siehe firmware/nfc-writer/src/web_server.cpp) —
# kein Rätselraten über die Antwortform nötig wie bei myStrom/Shelly.

async def _probe_nfc_writer(ip: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT) as client:
            r = await client.get(f"http://{ip}/status")
            if r.status_code == 200:
                data = r.json()
                if data.get("device") == "SpaceCaptain NFC Writer":
                    return {"ip": ip, "status": data.get("status"), "version": data.get("version")}
    except Exception:
        pass
    return None


class DiscoverRequest(BaseModel):
    cidr: str


@router.post("/discover")
async def discover_nfc_writer(
    payload: DiscoverRequest,
    _: User = Depends(require_admin),
):
    """Scannt einen IP-Bereich nach einem SpaceCaptain-NFC-Writer."""
    try:
        network = ipaddress.ip_network(payload.cidr, strict=False)
    except ValueError:
        raise HTTPException(400, f"Ungültiges CIDR: {payload.cidr}")

    if network.num_addresses > DISCOVERY_MAX_ADDRESSES:
        raise HTTPException(400, f"Bereich zu gross (max. {DISCOVERY_MAX_ADDRESSES} Adressen, z.B. /22)")
    if not network.is_private:
        raise HTTPException(400, "Nur private Netzbereiche (RFC1918) erlaubt")

    hosts = list(network.hosts())
    sem = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def _bounded(ip):
        async with sem:
            return await _probe_nfc_writer(str(ip))

    results = await asyncio.gather(*(_bounded(ip) for ip in hosts))
    return {"found": [r for r in results if r]}
