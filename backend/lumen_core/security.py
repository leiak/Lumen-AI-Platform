from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from lumen_core.config import settings
from lumen_core.tenant import TenantContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# M39 nitpick 2026-10-04 C4: ``algorithms`` / ``algorithm`` 硬编码 HS256,
# 防止运维误把 ALGORITHM 配成 ``none`` / RS256 之类 → alg confusion
# attack (用公钥当 secret 的 HMAC key)。decode 严格白名单
# ``["HS256"]``;encode 一并硬编码保持对称。历史 ``settings.ALGORITHM``
# 字段已删,``.env`` 残留值被忽略。
_JWT_ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "tenant_id": TenantContext.get_tenant_id()})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=_JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[_JWT_ALGORITHM])
    except JWTError:
        return None
