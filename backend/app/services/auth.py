from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import bcrypt

from app.config import get_settings
from app.database import get_db
from app.models import User

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


def create_access_token(user_id: int, role: str, expire_minutes: int | None = None) -> str:
    mins = expire_minutes if expire_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.utcnow() + timedelta(minutes=mins)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültiger oder abgelaufener Token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id: int = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exception
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur Admins erlaubt")
    return current_user


def decode_guest_token(token: str) -> dict | None:
    """Dekodiert einen Gast-JWT und gibt das Payload zurück, oder None bei Fehler."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "guest":
            return None
        return {"guest_id": int(payload["sub"])}
    except (JWTError, TypeError, ValueError):
        return None
