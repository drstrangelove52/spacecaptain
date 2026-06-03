"""
Automationen — kombiniertes Regelwerk mit Trigger-Bedingungen.

Jede Regel hat eine Ziel-Maschine (ein-/ausschalten) und beliebig viele
Bedingungen (AND-verknüpft). Bedingungstypen:
  power          – Quell-Maschine überschreitet Watt-Schwelle
  schedule       – Wochentag + Zeitfenster
  room_open      – Raum ist geöffnet
  session_active – mindestens eine aktive Maschinen-Session
"""
from datetime import time as TimeType
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, AutomationRule, RuleCondition, Machine, LogType
from app.services.auth import require_admin
from app.services import logger as log_svc

router = APIRouter(prefix="/automations", tags=["automations"])


# ── Pydantic ──────────────────────────────────────────────────────────────────

class ConditionIn(BaseModel):
    type: str
    source_machine_id: Optional[int]   = None
    power_on_w:        Optional[float] = None
    power_off_w:       Optional[float] = None
    days:              Optional[str]   = None
    time_on:           Optional[str]   = None
    time_off:          Optional[str]   = None


class RuleIn(BaseModel):
    name:              str           = ""
    action_type:       str           = "machine"  # machine | room_open | room_close
    target_machine_id: Optional[int] = None
    off_delay_sec:     int           = 0
    enabled:           bool          = True
    conditions:        List[ConditionIn] = []


class RulePatch(BaseModel):
    name:              Optional[str]             = None
    action_type:       Optional[str]             = None
    off_delay_sec:     Optional[int]             = None
    enabled:           Optional[bool]            = None
    conditions:        Optional[List[ConditionIn]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_time(s: str) -> TimeType:
    try:
        parts = s.split(":")
        return TimeType(int(parts[0]), int(parts[1]))
    except Exception:
        raise HTTPException(400, f"Ungültiges Zeitformat: {s!r}")


def _time_str(t) -> Optional[str]:
    return t.strftime("%H:%M") if t else None


def _validate_condition(c: ConditionIn) -> None:
    if c.type == "power":
        if c.source_machine_id is None or c.power_on_w is None or c.power_off_w is None:
            raise HTTPException(400, "power: source_machine_id, power_on_w und power_off_w erforderlich")
        if c.power_on_w <= c.power_off_w:
            raise HTTPException(400, "Einschaltschwelle muss höher sein als Ausschaltschwelle")
    elif c.type == "schedule":
        if not c.days or not c.time_on or not c.time_off:
            raise HTTPException(400, "schedule: days, time_on und time_off erforderlich")
        if c.time_off <= c.time_on:
            raise HTTPException(400, "Ausschaltzeit muss nach Einschaltzeit liegen")
    elif c.type not in ("room_open", "session_active"):
        raise HTTPException(400, f"Unbekannter Bedingungstyp: {c.type!r}")


def _build_condition_obj(c: ConditionIn, rule_id: int) -> RuleCondition:
    _validate_condition(c)
    cond = RuleCondition(rule_id=rule_id, type=c.type)
    if c.type == "power":
        cond.source_machine_id = c.source_machine_id
        cond.power_on_w  = c.power_on_w
        cond.power_off_w = c.power_off_w
    elif c.type == "schedule":
        cond.days    = c.days
        cond.time_on  = _parse_time(c.time_on)
        cond.time_off = _parse_time(c.time_off)
    return cond


def _cond_out(c: RuleCondition, machines: dict) -> dict:
    d: dict = {"id": c.id, "type": c.type}
    if c.type == "power":
        d["source_machine_id"]   = c.source_machine_id
        d["source_machine_name"] = machines.get(c.source_machine_id, "?")
        d["power_on_w"]  = c.power_on_w
        d["power_off_w"] = c.power_off_w
    elif c.type == "schedule":
        d["days"]     = c.days
        d["time_on"]  = _time_str(c.time_on)
        d["time_off"] = _time_str(c.time_off)
    return d


async def _rule_out(rule: AutomationRule, db: AsyncSession) -> dict:
    conds_res = await db.execute(
        select(RuleCondition).where(RuleCondition.rule_id == rule.id)
    )
    conds = conds_res.scalars().all()
    # Maschinen-Namen für power-conditions bulk-laden
    machine_ids = {c.source_machine_id for c in conds if c.type == "power" and c.source_machine_id}
    machines: dict = {}
    if machine_ids:
        mres = await db.execute(select(Machine.id, Machine.name).where(Machine.id.in_(machine_ids)))
        machines = {r[0]: r[1] for r in mres.all()}
    tm_name = rule.target_machine.name if hasattr(rule, "target_machine") and rule.target_machine else None
    return {
        "id":                  rule.id,
        "name":                rule.name,
        "action_type":         rule.action_type,
        "target_machine_id":   rule.target_machine_id,
        "target_machine_name": tm_name,
        "off_delay_sec":       rule.off_delay_sec,
        "enabled":             rule.enabled,
        "conditions":          [_cond_out(c, machines) for c in conds],
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    res = await db.execute(select(AutomationRule).order_by(AutomationRule.id))
    rules = res.scalars().all()
    tm_ids = {r.target_machine_id for r in rules}
    tm_map: dict = {}
    if tm_ids:
        tmres = await db.execute(select(Machine).where(Machine.id.in_(tm_ids)))
        for m in tmres.scalars().all():
            tm_map[m.id] = m
    for r in rules:
        r.target_machine = tm_map.get(r.target_machine_id)
    return [await _rule_out(r, db) for r in rules]


@router.post("")
async def create_rule(
    payload: RuleIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    if payload.action_type not in ("machine", "room_open", "room_close"):
        raise HTTPException(400, "action_type muss 'machine', 'room_open' oder 'room_close' sein")
    tm = None
    if payload.action_type == "machine":
        if not payload.target_machine_id:
            raise HTTPException(400, "Ziel-Maschine erforderlich für action_type 'machine'")
        tm = (await db.execute(select(Machine).where(Machine.id == payload.target_machine_id))).scalar_one_or_none()
        if not tm:
            raise HTTPException(404, "Ziel-Maschine nicht gefunden")
    if not payload.conditions:
        raise HTTPException(400, "Mindestens eine Bedingung erforderlich")

    rule = AutomationRule(
        name=payload.name.strip(),
        action_type=payload.action_type,
        target_machine_id=payload.target_machine_id if payload.action_type == "machine" else None,
        off_delay_sec=max(0, payload.off_delay_sec),
        enabled=payload.enabled,
    )
    db.add(rule)
    await db.flush()

    for ci in payload.conditions:
        db.add(_build_condition_obj(ci, rule.id))

    await db.commit()
    await db.refresh(rule)
    rule.target_machine = tm
    result = await _rule_out(rule, db)
    uid = current.id
    target = tm.name if tm else rule.action_type
    await log_svc.log(db, LogType.rule_created,
                      f"Regel '{rule.name or rule.id}' für {target} erstellt",
                      user_id=uid)
    return result


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: int,
    payload: RulePatch,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    rule = (await db.execute(select(AutomationRule).where(AutomationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Regel nicht gefunden")

    if payload.name is not None:
        rule.name = payload.name.strip()
    if payload.action_type is not None:
        rule.action_type = payload.action_type
    if payload.off_delay_sec is not None:
        rule.off_delay_sec = max(0, payload.off_delay_sec)
    if payload.enabled is not None:
        rule.enabled = payload.enabled

    if payload.conditions is not None:
        old = (await db.execute(select(RuleCondition).where(RuleCondition.rule_id == rule_id))).scalars().all()
        for c in old:
            await db.delete(c)
        await db.flush()
        for ci in payload.conditions:
            db.add(_build_condition_obj(ci, rule_id))

    await db.commit()
    await db.refresh(rule)
    tm = (await db.execute(select(Machine).where(Machine.id == rule.target_machine_id))).scalar_one_or_none()
    rule.target_machine = tm
    result = await _rule_out(rule, db)
    uid = current.id
    await log_svc.log(db, LogType.rule_updated,
                      f"Regel '{rule.name or rule.id}' aktualisiert",
                      user_id=uid)
    return result


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin),
):
    rule = (await db.execute(select(AutomationRule).where(AutomationRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Regel nicht gefunden")
    tm = (await db.execute(select(Machine).where(Machine.id == rule.target_machine_id))).scalar_one_or_none()
    label = rule.name or str(rule.id)
    uid = current.id
    await db.delete(rule)
    await db.commit()
    await log_svc.log(db, LogType.rule_deleted,
                      f"Regel '{label}' für {tm.name if tm else '?'} gelöscht",
                      user_id=uid)
    return {"ok": True}


@router.get("/states")
async def rule_states(_: User = Depends(require_admin)):
    from app.services.rule_watcher import get_rule_states
    return get_rule_states()
