from fastapi import APIRouter, Depends, HTTPException, status, Form
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, Token, UserOut
from app.services.auth import verify_password, create_access_token, get_current_user
from app.services import logger as log_svc
from app.models import LogType

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email == payload.email, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Email oder Passwort",
        )

    token = create_access_token(user.id, user.role)
    await log_svc.log(db, LogType.login, f"Login: {user.name} ({user.email})", user_id=user.id)
    return Token(access_token=token)


@router.post("/token", response_model=Token, include_in_schema=False)
async def token_form(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """OAuth2-kompatibler Endpoint für Swagger UI — username = E-Mail."""
    result = await db.execute(
        select(User).where(User.email == form.username, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Email oder Passwort",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user.id, user.role)
    await log_svc.log(db, LogType.login, f"Login (Swagger): {user.name} ({user.email})", user_id=user.id)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


class LoginByTokenRequest(BaseModel):
    login_token: str

@router.post("/login-by-token", response_model=Token)
async def login_by_token(payload: LoginByTokenRequest, db: AsyncSession = Depends(get_db)):
    """Lab-Manager-Login per persönlichem Token-Link — kein Passwort nötig."""
    result = await db.execute(
        select(User).where(User.login_token == payload.login_token, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger oder abgelaufener Token-Link")
    token = create_access_token(user.id, user.role)
    await log_svc.log(db, LogType.login, f"Login per Token-Link: {user.name} ({user.email})", user_id=user.id)
    return Token(access_token=token)
