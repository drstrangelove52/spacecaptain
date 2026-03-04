"""
NFC-Schreibgerät Proxy
======================
Leitet Schreibaufträge an den ESP32 (PN532) im lokalen Netz weiter.
Der ESP32 wartet auf einen NFC-Tag und schreibt die URL als NDEF URI Record.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth import get_current_user
from app.services.system_settings import get_system_settings

router = APIRouter(prefix="/nfc", tags=["nfc"])

TIMEOUT = 5.0  # Sekunden für Status/Result-Abfragen


async def _base_url(db: AsyncSession) -> str:
    s = await get_system_settings(db)
    url = s.nfc_writer_url.rstrip("/")
    if not url:
        raise HTTPException(503, "NFC-Schreibgerät nicht konfiguriert (URL in Einstellungen setzen)")
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
