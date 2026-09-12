"""
Smart Plug Integration — myStrom & Shelly
myStrom:     Token via "Token"-Header
Shelly Gen1: /relay/0, Digest-Auth via plug_token="admin:passwort"
Shelly Gen2+: RPC-API /rpc/Switch.Set, Digest-Auth via plug_token="admin:passwort"
              Gilt für Gen2, Gen3, Gen4 — alle nutzen dieselbe RPC-API.
"""
import asyncio
import hashlib
import ipaddress
import secrets
import string
import httpx
import logging
from types import SimpleNamespace
from typing import Optional, Tuple

log = logging.getLogger(__name__)

TIMEOUT = 5.0
DISCOVERY_TIMEOUT = 1.5
DISCOVERY_MAX_ADDRESSES = 1024
DISCOVERY_CONCURRENCY = 40


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


# ── Auth setzen/aendern ──────────────────────────────────────────────────────
# Alle drei Geraete-APIs live gegen echte Geraete verifiziert (2026-09), ausser
# Shelly Gen1 — dafuer stand kein Testgeraet zur Verfuegung, basiert nur auf
# dokumentiertem Verhalten.
#
# Passwort-Alphabet bewusst rein alphanumerisch: myStrom akzeptiert am Geraet
# selbst nur [a-zA-Z0-9] als Token (eigene Validierung im Geraete-JS gefunden),
# ein Bulk-Vorgang ueber gemischte Plug-Typen braucht also ein Passwort, das
# fuer alle Typen gleichzeitig gueltig ist.

def generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def set_plug_auth(machine, new_password: str) -> Tuple[bool, str, Optional[str]]:
    """Setzt/aendert die Auth auf einem Plug. Nutzt den aktuell in machine.plug_token
    hinterlegten Wert zur Authentifizierung, falls das Geraet schon gesichert ist
    (sonst wird die Aenderung selbst verweigert).
    Rueckgabe: (ok, message, neuer plug_token-Wert oder None bei Fehler)."""
    if machine.plug_type == "none" or not machine.plug_ip:
        return False, "Kein Smart Plug konfiguriert", None

    ip = machine.plug_ip

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:

            if machine.plug_type == "mystrom":
                r = await client.post(
                    f"http://{ip}/api/v1/settings",
                    json={"token": new_password},
                    headers=_mystrom_headers(machine),
                )
                r.raise_for_status()
                return True, "myStrom-Token gesetzt", new_password

            elif machine.plug_type == "shelly":
                # Gen1 — dokumentiertes Verhalten, nicht live verifiziert
                r = await client.post(
                    f"http://{ip}/settings/login",
                    params={"enabled": "1", "username": "admin", "password": new_password},
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                return True, "Shelly-Login gesetzt", f"admin:{new_password}"

            elif machine.plug_type == "shelly_gen2":
                info = await client.get(f"http://{ip}/shelly")
                info.raise_for_status()
                realm = info.json().get("id")
                if not realm:
                    return False, "Geraete-ID nicht ermittelbar", None
                ha1 = hashlib.sha256(f"admin:{realm}:{new_password}".encode()).hexdigest()
                r = await client.post(
                    f"http://{ip}/rpc",
                    json={"id": 1, "method": "Shelly.SetAuth",
                          "params": {"user": "admin", "realm": realm, "ha1": ha1}},
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    return False, data["error"].get("message", "Fehler vom Geraet"), None
                return True, "Shelly-Auth gesetzt", f"admin:{new_password}"

    except httpx.TimeoutException:
        return False, f"Timeout — Plug nicht erreichbar ({ip})", None
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = f" — {e.response.json().get('message', '')}"
        except Exception:
            pass
        return False, f"HTTP Fehler: {e.response.status_code}{detail}", None
    except Exception as e:
        return False, f"Fehler: {str(e)}", None

    return False, "Unbekannter Plug-Typ", None


async def clear_plug_auth(machine) -> Tuple[bool, str]:
    """Entfernt die Auth wieder (Geraet danach frei ohne Anmeldung erreichbar).
    Authentifiziert die Aenderung selbst mit dem aktuell hinterlegten Token —
    ist der bereits falsch/veraltet, schlaegt das Entfernen fehl (Geraet muesste
    dann manuell zurueckgesetzt werden)."""
    if machine.plug_type == "none" or not machine.plug_ip:
        return False, "Kein Smart Plug konfiguriert"

    ip = machine.plug_ip

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:

            if machine.plug_type == "mystrom":
                r = await client.post(
                    f"http://{ip}/api/v1/settings",
                    json={"token": ""},
                    headers=_mystrom_headers(machine),
                )
                r.raise_for_status()
                return True, "myStrom-Token entfernt"

            elif machine.plug_type == "shelly":
                # Gen1 — dokumentiertes Verhalten, nicht live verifiziert
                r = await client.post(
                    f"http://{ip}/settings/login",
                    params={"enabled": "0"},
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                return True, "Shelly-Login deaktiviert"

            elif machine.plug_type == "shelly_gen2":
                info = await client.get(f"http://{ip}/shelly")
                info.raise_for_status()
                realm = info.json().get("id")
                if not realm:
                    return False, "Geraete-ID nicht ermittelbar"
                r = await client.post(
                    f"http://{ip}/rpc",
                    json={"id": 1, "method": "Shelly.SetAuth",
                          "params": {"user": "admin", "realm": realm, "ha1": None}},
                    auth=_shelly_auth(machine),
                )
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    return False, data["error"].get("message", "Fehler vom Geraet")
                return True, "Shelly-Auth entfernt"

    except httpx.TimeoutException:
        return False, f"Timeout — Plug nicht erreichbar ({ip})"
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = f" — {e.response.json().get('message', '')}"
        except Exception:
            pass
        return False, f"HTTP Fehler: {e.response.status_code}{detail}"
    except Exception as e:
        return False, f"Fehler: {str(e)}"

    return False, "Unbekannter Plug-Typ"


# ── Netzwerk-Discovery ──────────────────────────────────────────────────────
# Identifiziert unkonfigurierte/erreichbare Plugs per HTTP-Probe — kein mDNS
# (Multicast erreicht den Backend-Container im Docker-Bridge-Netz nicht ohne
# host-Networking). Nutzt bewusst dieselben Endpunkte wie get_plug_status(),
# aber ohne bekannten plug_type: probiert alle drei durch, nur Requests mit
# einer zum jeweiligen Typ passenden Antwortform zaehlen als Treffer.

async def probe_device(ip: str) -> Optional[dict]:
    """Prüft eine einzelne IP auf myStrom/Shelly/Shelly-Gen2 — None wenn kein Treffer."""
    async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT) as client:
        # Shelly Gen2+ (RPC-API)
        try:
            r = await client.get(f"http://{ip}/rpc/Shelly.GetDeviceInfo")
            if r.status_code == 200:
                data = r.json()
                if "mac" in data and ("model" in data or "app" in data):
                    return {
                        "ip": ip, "plug_type": "shelly_gen2",
                        "name": data.get("name") or data.get("model") or data.get("id"),
                        "mac": data.get("mac"),
                    }
        except Exception:
            pass

        # Shelly Gen1
        try:
            r = await client.get(f"http://{ip}/shelly")
            if r.status_code == 200:
                data = r.json()
                if "mac" in data and "type" in data:
                    return {"ip": ip, "plug_type": "shelly", "name": data.get("type"), "mac": data.get("mac")}
        except Exception:
            pass

        # myStrom
        try:
            r = await client.get(f"http://{ip}/report")
            if r.status_code == 200:
                data = r.json()
                if "relay" in data or "power" in data:
                    mac = None
                    try:
                        r_info = await client.get(f"http://{ip}/info")
                        if r_info.status_code == 200:
                            mac = r_info.json().get("mac")
                    except Exception:
                        pass
                    return {"ip": ip, "plug_type": "mystrom", "name": None, "mac": mac}
        except Exception:
            pass

    return None


async def discover_devices(cidr: str) -> list[dict]:
    """Scannt ein Subnetz nach unkonfigurierten Smart Plugs. Wirft ValueError bei ungültigem/zu grossem/öffentlichem CIDR."""
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise ValueError(f"Ungültiges CIDR: {cidr}")

    if network.num_addresses > DISCOVERY_MAX_ADDRESSES:
        raise ValueError(f"Bereich zu gross (max. {DISCOVERY_MAX_ADDRESSES} Adressen, z.B. /22)")
    if not network.is_private:
        raise ValueError("Nur private Netzbereiche (RFC1918) erlaubt")

    hosts = list(network.hosts())
    sem = asyncio.Semaphore(DISCOVERY_CONCURRENCY)

    async def _bounded(ip: str):
        async with sem:
            return await probe_device(str(ip))

    results = await asyncio.gather(*(_bounded(ip) for ip in hosts))
    return [r for r in results if r]
