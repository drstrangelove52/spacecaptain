from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from app.config import get_settings, APP_VERSION
from app.database import engine, Base
from app.services.migrate import run_migrations
from app.routers import auth, users, guests, machines, permissions, qr, dashboard, guest_auth, backup, maintenance, nfc
from app.routers import settings as settings_router
from app.routers import queue as queue_router
from app.services.session import idle_watcher, plug_watcher, queue_watcher

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    for attempt in range(1, 11):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception as e:
            if attempt == 10:
                raise
            import logging
            logging.getLogger("uvicorn").warning(f"DB not ready (attempt {attempt}/10), retrying in 3s… ({e})")
            await asyncio.sleep(3)
    await run_migrations(engine)
    task1 = asyncio.create_task(idle_watcher(app))
    task2 = asyncio.create_task(plug_watcher(app))
    task3 = asyncio.create_task(queue_watcher(app))
    yield
    task1.cancel(); task2.cancel(); task3.cancel()
    for t in (task1, task2, task3):
        try:
            await t
        except asyncio.CancelledError:
            pass


from fastapi.security import OAuth2PasswordBearer
from fastapi.openapi.utils import get_openapi

app = FastAPI(title="SpaceCaptain API", version=APP_VERSION, lifespan=lifespan)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="SpaceCaptain API",
        version=APP_VERSION,
        description="SpaceCaptain Management API — Authorize mit E-Mail als Username",
        routes=app.routes,
    )
    # OAuth2 Password Flow auf /api/auth/token zeigen
    schema["components"]["securitySchemes"] = {
        "OAuth2PasswordBearer": {
            "type": "oauth2",
            "flows": {
                "password": {
                    "tokenUrl": "/api/auth/token",
                    "scopes": {}
                }
            }
        }
    }
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/version")
async def get_version():
    return {"version": APP_VERSION}

app.include_router(auth.router,         prefix="/api")
app.include_router(users.router,        prefix="/api")
app.include_router(guests.router,       prefix="/api")
app.include_router(machines.router,     prefix="/api")
app.include_router(permissions.router,  prefix="/api")
app.include_router(qr.router,           prefix="/api")
app.include_router(dashboard.router,    prefix="/api")
app.include_router(guest_auth.router,   prefix="/api")
app.include_router(backup.router,       prefix="/api")
app.include_router(maintenance.router,  prefix="/api")
app.include_router(nfc.router,          prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(queue_router.router,    prefix="/api")
