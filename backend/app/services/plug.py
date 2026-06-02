"""
Smart Plug Integration — myStrom & Shelly
myStrom:     Token via "Token"-Header
Shelly Gen1: /relay/0, Digest-Auth via plug_token="admin:passwort"
Shelly Gen2+: RPC-API /rpc/Switch.Set, Digest-Auth via plug_token="admin:passwort"
              Gilt für Gen2, Gen3, Gen4 — alle nutzen dieselbe RPC-API.
"""
import httpx
import logging
from types import SimpleNamespace
from typing import Tuple

log = logging.getLogger(__name__)

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

    ip    = machine.plug_ip
    onoff = "on" if action == "on" else "off"
    label = "EIN" if action == "on" else "AUS"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:

            if machine.plug_type == "mystrom":
                state = "1" if action == "on" else "0"
                r = await client.get(
                    f"http://{ip}/relay?state={state}",
                    headers=_mystrom_headers(machine),
                )
                r.raise_for_status()
                return True, f"myStrom: {label}"

            elif machine.plug_type == "shelly":
                r = await client.get(
                    f"http://{ip}/relay/0?turn={onoff}",
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                return True, f"Shelly: {label}"

            elif machine.plug_type == "shelly_gen2":
                r = await client.post(
                    f"http://{ip}/rpc/Switch.Set",
                    json={"id": 0, "on": action == "on"},
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                return True, f"Shelly Gen2+: {label}"

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
                    headers=_mystrom_headers(machine),
                )
                r.raise_for_status()
                data = r.json()
                return {
                    "supported": True,
                    "on":      data.get("relay", False),
                    "power_w": data.get("power", None),
                }

            elif machine.plug_type == "shelly":
                r = await client.get(f"http://{ip}/relay/0", auth=_shelly_auth(machine))
                r.raise_for_status()
                relay = r.json()
                power_w = None
                try:
                    rm = await client.get(f"http://{ip}/meter/0", auth=_shelly_auth(machine))
                    if rm.status_code == 200:
                        power_w = rm.json().get("power", None)
                except Exception:
                    pass
                return {
                    "supported": True,
                    "on":      relay.get("ison", False),
                    "power_w": power_w,
                }

            elif machine.plug_type == "shelly_gen2":
                r = await client.get(
                    f"http://{ip}/rpc/Switch.GetStatus",
                    params={"id": 0},
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                data = r.json()
                return {
                    "supported": True,
                    "on":      data.get("output", False),
                    "power_w": data.get("apower", None),
                }

    except Exception:
        return {"supported": True, "on": None, "power_w": None, "error": "unreachable"}

    return {"supported": False, "on": None, "power_w": None}


async def switch_all_machine_plugs(machine, action: str, db) -> Tuple[bool, str]:
    """Schaltet Primär-Plug (machine.plug_ip) + alle Sekundär-Plugs aus machine_plugs."""
    from sqlalchemy import select as _sel
    from app.models import MachinePlug, Plug as PlugModel

    msgs: list[str] = []
    all_ok = True

    ok, msg = await switch_plug(machine, action)
    msgs.append(msg)
    if not ok:
        all_ok = False

    try:
        res = await db.execute(
            _sel(PlugModel).join(MachinePlug, MachinePlug.plug_id == PlugModel.id)
            .where(MachinePlug.machine_id == machine.id, MachinePlug.sort_order > 0)
        )
        for plug in res.scalars().all():
            proxy = SimpleNamespace(
                plug_type=plug.plug_type,
                plug_ip=plug.plug_ip,
                plug_token=plug.plug_token,
            )
            ok2, msg2 = await switch_plug(proxy, action)
            msgs.append(msg2)
            if not ok2:
                all_ok = False
    except Exception as e:
        log.error(f"switch_all_machine_plugs Sekundär-Fehler: {e}")
        all_ok = False
        msgs.append(f"Sekundär-Plug Fehler: {e}")

    return all_ok, "; ".join(msgs)
