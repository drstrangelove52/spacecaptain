from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ActivityLog, MaintenanceRecord, MachineSession, User, LogType
from app.services.auth import require_admin
from app.services.logger import log as activity_log

router = APIRouter(prefix="/data", tags=["data-management"])


@router.get("/summary")
async def get_data_summary(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    log_count = await db.scalar(select(func.count()).select_from(ActivityLog))
    session_count = await db.scalar(
        select(func.count()).select_from(MachineSession)
        .where(MachineSession.ended_at.isnot(None))
    )
    maintenance_count = await db.scalar(select(func.count()).select_from(MaintenanceRecord))
    return {
        "activity_log": log_count,
        "sessions": session_count,
        "maintenance_records": maintenance_count,
    }


@router.delete("/activity-log")
async def clear_activity_log(
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(select(func.count()).select_from(ActivityLog))
    await db.execute(delete(ActivityLog))
    await db.commit()
    await activity_log(db, LogType.system, f"Aktivitätslog gelöscht ({count} Einträge)", user_id=current.id)
    await db.commit()
    return {"deleted": count}


@router.delete("/sessions")
async def clear_sessions(
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(
        select(func.count()).select_from(MachineSession)
        .where(MachineSession.ended_at.isnot(None))
    )
    await db.execute(
        delete(MachineSession).where(MachineSession.ended_at.isnot(None))
    )
    await db.commit()
    await activity_log(db, LogType.system, f"Sessionhistorie gelöscht ({count} Einträge)", user_id=current.id)
    await db.commit()
    return {"deleted": count}


@router.delete("/maintenance-records")
async def clear_maintenance_records(
    current: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    count = await db.scalar(select(func.count()).select_from(MaintenanceRecord))
    await db.execute(delete(MaintenanceRecord))
    await db.commit()
    await activity_log(db, LogType.system, f"Wartungshistorie gelöscht ({count} Einträge)", user_id=current.id)
    await db.commit()
    return {"deleted": count}
