"""
Smart Plug Integration — myStrom & Shelly
myStrom: Token via "Token"-Header
Shelly:  Gen1-API (/relay/0), Digest-Auth via plug_token="admin:passwort"
"""
import httpx
from typing import Tuple

TIMEOUT = 5.0


def _mystrom_headers(machine) -> dict:
    token = (machine.plug_token or "").strip()
    return {"Token": token} if token else {}


def _shelly_auth(machine):
    """Gibt httpx.DigestAuth zurück wenn plug_token gesetzt (Format: 'admin:passwort')."""
    token = (machine.plug_token or "").strip()
    if token and ":" in token:
        user, pw = token.split(":", 1)
        return httpx.DigestAuth(user, pw)
    return None


async def switch_plug(machine, action: str) -> Tuple[bool, str]:
    if machine.plug_type == "none" or not machine.plug_ip:
        return True, "Kein Smart Plug konfiguriert"

    ip   = machine.plug_ip
    onoff = "on" if action == "on" else "off"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:

            if machine.plug_type == "mystrom":
                state = "1" if action == "on" else "0"
                r = await client.get(
                    f"http://{ip}/relay?state={state}",
                    headers=_mystrom_headers(machine)
                )
                r.raise_for_status()
                return True, f"myStrom: {'EIN' if action == 'on' else 'AUS'}"

            elif machine.plug_type == "shelly":
                r = await client.get(
                    f"http://{ip}/relay/0?turn={onoff}",
                    auth=_shelly_auth(machine)
                )
                r.raise_for_status()
                return True, f"Shelly: {'EIN' if action == 'on' else 'AUS'}"

    except httpx.TimeoutException:
        return False, f"Timeout — Plug nicht erreichbar ({ip})"
    except httpx.HTTPStatusError as e:
        return False, f"HTTP Fehler: {e.response.status_code}"
    except Exception as e:
        return False, f"Fehler: {str(e)}"

    return False, "Unbekannter Plug-Typ"


async def get_plug_status(machine) -> dict:
    if machine.plug_type == "none" or not machine.plug_ip:
        return {"supported": False, "on": None, "power_w": None}

    ip = machine.plug_ip

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:

            if machine.plug_type == "mystrom":
                r = await client.get(
                    f"http://{ip}/report",
                    headers=_mystrom_headers(machine)
                )
                r.raise_for_status()
                data = r.json()
                return {
                    "supported": True,
                    "on":      data.get("relay", False),
                    "power_w": data.get("power", None),
                }

            elif machine.plug_type == "shelly":
                r = await client.get(
                    f"http://{ip}/relay/0",
                    auth=_shelly_auth(machine)
                )
                r.raise_for_status()
                relay = r.json()
                # Verbrauch kommt vom separaten /meter/0 Endpoint
                power_w = None
                try:
                    rm = await client.get(
                        f"http://{ip}/meter/0",
                        auth=_shelly_auth(machine)
                    )
                    if rm.status_code == 200:
                        power_w = rm.json().get("power", None)
                except Exception:
                    pass
                return {
                    "supported": True,
                    "on":      relay.get("ison", False),
                    "power_w": power_w,
                }

    except Exception:
        return {"supported": True, "on": None, "power_w": None, "error": "unreachable"}

    return {"supported": False, "on": None, "power_w": None}
