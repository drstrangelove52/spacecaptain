"""
Tests gegen eine In-Memory-SQLite-Datenbank (kein MariaDB noetig).
Ausfuehren:  cd backend && pytest
Benoetigt zusaetzlich zu requirements.txt:  aiosqlite pytest pytest-asyncio
"""
import os
import sys

os.environ.setdefault("SPACECAPTAIN_SKIP_SECRET_CHECK", "1")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-0123456789")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
import app.models  # noqa: F401
import app.models_inventory  # noqa: F401
from app.models import User, UserRole, SystemSettings
from app.services.auth import create_access_token


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(session_factory):
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(session_factory):
    from app.main import app

    async def _get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_user(session_factory, role: UserRole, name: str) -> dict:
    async with session_factory() as s:
        u = User(name=name, email=f"{name}@test.local", password_hash="x", role=role)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return {"Authorization": f"Bearer {create_access_token(u.id, role.value)}"}


@pytest_asyncio.fixture
async def admin(session_factory):
    return await _make_user(session_factory, UserRole.admin, "admin")


@pytest_asyncio.fixture
async def power(session_factory):
    return await _make_user(session_factory, UserRole.power_manager, "power")


@pytest_asyncio.fixture
async def manager(session_factory):
    return await _make_user(session_factory, UserRole.manager, "manager")


@pytest_asyncio.fixture
async def enabled(session_factory):
    """Inventar-Modul eingeschaltet."""
    async with session_factory() as s:
        s.add(SystemSettings(id=1, inventory_enabled=True))
        await s.commit()
