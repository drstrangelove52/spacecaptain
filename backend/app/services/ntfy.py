"""
ntfy.sh Notification Service
Unterstützt ntfy.sh Cloud und selbst gehostete Instanzen.
"""
import base64
import httpx
import logging

log = logging.getLogger(__name__)
TIMEOUT = 8.0


async def send_notification(
    server: str,
    token: str | None,
    topic: str,
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
) -> bool:
    """
    Sendet eine Benachrichtigung an ein ntfy-Topic.
    Gibt True zurück bei Erfolg, False bei Fehler.
    """
    if not server or not topic:
        log.warning("ntfy: server oder topic nicht konfiguriert")
        return False

    server = server.rstrip("/")
    url = f"{server}/{topic}"
    def _encode_header(value: str) -> str:
        """RFC 2047 Base64-Enkodierung für Non-ASCII Header-Werte."""
        try:
            value.encode("ascii")
            return value
        except UnicodeEncodeError:
            encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
            return f"=?utf-8?b?{encoded}?="

    headers = {
        "Title": _encode_header(title),
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(url, content=message.encode(), headers=headers)
            r.raise_for_status()
            log.info(f"ntfy: Nachricht an {topic} gesendet (Status {r.status_code})")
            return True
    except httpx.TimeoutException:
        log.warning(f"ntfy: Timeout beim Senden an {url}")
    except httpx.HTTPStatusError as e:
        log.warning(f"ntfy: HTTP-Fehler {e.response.status_code} beim Senden an {url}")
    except Exception as e:
        log.warning(f"ntfy: Fehler beim Senden: {e}")
    return False
