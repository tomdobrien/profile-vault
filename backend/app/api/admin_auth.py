import hashlib
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.upload_user import UploadUser
from app.permissions import PERMISSIONS

SESSION_COOKIE = "profile_admin_session"
SESSION_MAX_AGE = 8 * 60 * 60
AUTH_WINDOW_SECONDS = 15 * 60
AUTH_MAX_ATTEMPTS = 10
_auth_attempts: dict[str, deque[float]] = defaultdict(deque)
_auth_lock = Lock()


@dataclass(frozen=True)
class UploadAccess:
    user_id: int | None
    is_owner: bool
    permissions: frozenset[str] = frozenset()


def _session_secret() -> bytes:
    secret = settings.admin_session_secret
    if not secret or len(secret) < 32:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin authentication is not configured")
    return secret.encode("utf-8")


def ensure_auth_is_configured() -> None:
    if not settings.admin_password or len(settings.admin_password) < 8:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin authentication is not configured")
    _session_secret()


def create_session() -> str:
    issued_at = str(int(time.time()))
    signature = hmac.new(_session_secret(), issued_at.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{issued_at}.{signature}"


def _bearer_or_cookie(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    return bearer_token or request.cookies.get(SESSION_COOKIE)


def is_valid_session(value: str | None) -> bool:
    if not value:
        return False
    try:
        issued_at, supplied_signature = value.split(".", 1)
        if not issued_at.isascii() or not issued_at.isdigit() or not supplied_signature.isascii():
            return False
        issued = int(issued_at)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if issued > now + 60 or now - issued > SESSION_MAX_AGE:
        return False
    expected = hmac.new(_session_secret(), issued_at.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied_signature)


def has_admin_session(request: Request) -> bool:
    return is_valid_session(_bearer_or_cookie(request))


def require_admin(request: Request) -> None:
    ensure_auth_is_configured()
    if not has_admin_session(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required")


def create_upload_session(user_id: int) -> str:
    issued_at = str(int(time.time()))
    message = f"upload:{user_id}:{issued_at}".encode("ascii")
    signature = hmac.new(_session_secret(), message, hashlib.sha256).hexdigest()
    return f"upload.{user_id}.{issued_at}.{signature}"


def upload_session_user_id(value: str | None) -> int | None:
    if not value:
        return None
    try:
        role, user_id_text, issued_at, supplied_signature = value.split(".", 3)
        if role != "upload" or not user_id_text.isascii() or not user_id_text.isdigit():
            return None
        if not issued_at.isascii() or not issued_at.isdigit() or not supplied_signature.isascii():
            return None
        user_id = int(user_id_text)
        issued = int(issued_at)
    except (ValueError, TypeError):
        return None
    now = int(time.time())
    if issued > now + 60 or now - issued > SESSION_MAX_AGE:
        return None
    message = f"upload:{user_id}:{issued_at}".encode("ascii")
    expected = hmac.new(_session_secret(), message, hashlib.sha256).hexdigest()
    return user_id if hmac.compare_digest(expected, supplied_signature) else None


def require_upload_access(request: Request, db: Session = Depends(get_db)) -> UploadAccess:
    ensure_auth_is_configured()
    token = _bearer_or_cookie(request)
    if is_valid_session(token):
        return UploadAccess(user_id=None, is_owner=True, permissions=frozenset(PERMISSIONS))
    user_id = upload_session_user_id(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to upload")
    user = db.get(UploadUser, user_id)
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Upload account is unavailable")
    return UploadAccess(user_id=user.id, is_owner=False, permissions=frozenset(user.permissions or []) & PERMISSIONS.keys())


def require_permission(permission: str):
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")

    def check(access: UploadAccess = Depends(require_upload_access)) -> UploadAccess:
        if not access.is_owner and permission not in access.permissions:
            raise HTTPException(status_code=403, detail="Your account does not have access to this feature")
        return access

    return check


def public_permissions(db: Session) -> list[str]:
    # The personal profile is public; only file features have account grants.
    return ["resume:view"]


def require_frontend_origin(request: Request) -> None:
    if request.headers.get("origin") not in settings.allowed_frontend_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Request origin is not allowed")

def check_auth_rate_limit(request: Request, *, contact: bool = False) -> None:
    key = request.client.host if request.client else "unknown"
    if contact:
        key = "contact/" + key
    now = time.monotonic()
    # Single-process protection; a trusted proxy may group visitors under one address.
    with _auth_lock:
        for source, history in list(_auth_attempts.items()):
            if not history or now - history[-1] >= AUTH_WINDOW_SECONDS:
                del _auth_attempts[source]
        if key not in _auth_attempts and len(_auth_attempts) >= 4096:
            raise HTTPException(status_code=429, detail="Too many requests. Try again later.", headers={"Retry-After": str(AUTH_WINDOW_SECONDS)})
        attempts = _auth_attempts[key]
        while attempts and now - attempts[0] >= AUTH_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= AUTH_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many requests. Try again later.", headers={"Retry-After": str(AUTH_WINDOW_SECONDS)})
        attempts.append(now)
