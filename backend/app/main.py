from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from app.config import get_settings
from app.database import engine, Base
from app.services.migrate import run_migrations
from app.routers import auth, users, guests, machines, permissions, qr, dashboard, guest_auth, backup, maintenance
from app.services.session import idle_watcher, plug_watcher

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations(engine)
    task1 = asyncio.create_task(idle_watcher(app))
    task2 = asyncio.create_task(plug_watcher(app))
    yield
    task1.cancel(); task2.cancel()
    for t in (task1, task2):
        try:
            await t
        except asyncio.CancelledError:
            pass


from fastapi.security import OAuth2PasswordBearer
from fastapi.openapi.utils import get_openapi

app = FastAPI(title="SpaceCaptain API", version="1.01", lifespan=lifespan)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title="SpaceCaptain API",
        version="1.01",
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
