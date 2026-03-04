"""
NFC-Schreibgerät Proxy
======================
Leitet Schreibaufträge an den ESP32 (PN532) im lokalen Netz weiter.
Der ESP32 wartet auf einen NFC-Tag und schreibt die URL als NDEF URI Record.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.models import User
from app.services.auth import get_current_user

router = APIRouter(prefix="/nfc", tags=["nfc"])

TIMEOUT = 5.0  # Sekunden für Status/Result-Abfragen


def _base_url() -> str:
    url = get_settings().nfc_writer_url.rstrip("/")
    if not url:
        raise HTTPException(503, "NFC-Schreibgerät nicht konfiguriert (NFC_WRITER_URL fehlt in .env)")
    return url


class WriteRequest(BaseModel):
    url: str
    label: str = ""


@router.get("/status")
async def nfc_status(_: User = Depends(get_current_user)):
    """Prüft ob das NFC-Schreibgerät erreichbar ist."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{_base_url()}/status")
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "NFC-Schreibgerät nicht erreichbar")
    except httpx.TimeoutException:
        raise HTTPException(504, "NFC-Schreibgerät antwortet nicht")


@router.post("/write")
async def nfc_write(payload: WriteRequest, _: User = Depends(get_current_user)):
    """Startet einen Schreibauftrag auf dem ESP32."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                f"{_base_url()}/write",
                json={"url": payload.url, "label": payload.label},
            )
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "NFC-Schreibgerät nicht erreichbar")
    except httpx.TimeoutException:
        raise HTTPException(504, "NFC-Schreibgerät antwortet nicht")


@router.get("/result")
async def nfc_result(_: User = Depends(get_current_user)):
    """Fragt das Ergebnis des letzten Schreibauftrags ab (zum Pollen)."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{_base_url()}/result")
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "NFC-Schreibgerät nicht erreichbar")
    except httpx.TimeoutException:
        raise HTTPException(504, "NFC-Schreibgerät antwortet nicht")
