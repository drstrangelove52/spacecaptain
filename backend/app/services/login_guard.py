"""
Schutz gegen Passwort-Raten: zählt Fehlversuche je Client-IP und je Benutzerkennung im Arbeitsspeicher.
Nach `MAX_FAILS` Fehlversuchen im Fenster `WINDOW_SEC` antworten Login-Endpoints mit 429, bis das Fenster abgelaufen ist.
Ein erfolgreicher Login setzt den Zähler der Kennung zurück. Der Zustand geht beim Neustart verloren (bewusst: kein DB-Zugriff nötig).
Die Kennung wird zusätzlich zur IP gezählt, weil `X-Forwarded-For` vom Client mitgeschickt werden kann.
"""
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException

WINDOW_SEC = 600
MAX_FAILS_IP = 30
MAX_FAILS_IDENT = 8

_fails: dict = defaultdict(deque)
_ident_ips: dict = defaultdict(set)      # Kennung → IPs, von denen Fehlversuche kamen (zum gemeinsamen Entsperren)


def _keys(ip: str, ident: Optional[str]) -> list:
    keys = [("ip", ip, MAX_FAILS_IP)]
    if ident:
        keys.append(("id", ident.strip().lower(), MAX_FAILS_IDENT))
    return keys


def _prune(q: deque, now: float) -> None:
    while q and now - q[0] > WINDOW_SEC:
        q.popleft()


def is_blocked(ip: str, ident: Optional[str] = None) -> bool:
    now = time.monotonic()
    for kind, val, limit in _keys(ip, ident):
        q = _fails[(kind, val)]
        _prune(q, now)
        if len(q) >= limit:
            return True
    return False


def check(ip: str, ident: Optional[str] = None) -> None:
    """Vor der Passwortprüfung aufrufen."""
    if is_blocked(ip, ident):
        raise HTTPException(429, "Zu viele Fehlversuche. Bitte in 10 Minuten erneut versuchen.")


def record_failure(ip: str, ident: Optional[str] = None) -> bool:
    """Zählt einen Fehlversuch. Gibt True zurück, wenn dadurch gerade die Sperre erreicht wurde (zum einmaligen Loggen)."""
    now = time.monotonic()
    reached = False
    if ident:
        _ident_ips[ident.strip().lower()].add(ip)
    for kind, val, limit in _keys(ip, ident):
        q = _fails[(kind, val)]
        _prune(q, now)
        q.append(now)
        if len(q) == limit:
            reached = True
    return reached


def record_success(ident: Optional[str]) -> None:
    if ident:
        _fails.pop(("id", ident.strip().lower()), None)
        _ident_ips.pop(ident.strip().lower(), None)


def blocked() -> dict:
    """Aktuell gesperrte Kennungen und IPs (für die Anzeige in der Verwaltung)."""
    now = time.monotonic()
    out = {"idents": [], "ips": []}
    for (kind, val), q in list(_fails.items()):
        _prune(q, now)
        if kind == "id" and len(q) >= MAX_FAILS_IDENT:
            out["idents"].append(val)
        elif kind == "ip" and len(q) >= MAX_FAILS_IP:
            out["ips"].append(val)
    return out


def unlock(kind: str, value: str) -> bool:
    """Sperre aufheben. Bei einer Kennung auch die IPs, von denen ihre Fehlversuche kamen (sonst bliebe die IP-Sperre)."""
    value = value.strip().lower()
    if kind == "ip":
        return _fails.pop(("ip", value), None) is not None
    found = _fails.pop(("id", value), None) is not None
    for ip in _ident_ips.pop(value, set()):
        _fails.pop(("ip", ip), None)
    return found


def reset() -> None:
    _fails.clear()
    _ident_ips.clear()


async def note_failure(db, ip: str, ident: Optional[str] = None) -> None:
    """Fehlversuch zählen; beim Erreichen der Sperre einmalig ins Aktivitätslog schreiben."""
    if record_failure(ip, ident):
        from app.models import LogType
        from app.services import logger as log_svc
        what = f" für {ident}" if ident else ""
        await log_svc.log(db, LogType.login_blocked,
                          f"Login gesperrt{what} von {ip}: zu viele Fehlversuche (10 Minuten)",
                          meta={"ip": ip, "ident": ident})
