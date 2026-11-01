import asyncio
import errno
import hashlib
import hmac
import re
import secrets
from pathlib import Path
from datetime import timedelta, timezone
from urllib.parse import unquote
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from app.api.admin_auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    UploadAccess,
    create_session,
    create_upload_session,
    ensure_auth_is_configured,
    has_admin_session,
    require_admin,
    require_frontend_origin,
    require_upload_access,
    upload_session_user_id,
    check_auth_rate_limit,
    require_permission,
    public_permissions,
)
from app.api.upload_auth import hash_password, password_needs_rehash, verify_password
from app.config import settings
from app.database import get_db
from app.models.contact_message import ContactMessage
from app.models.upload_user import UploadInvitation, UploadUser, utcnow
from app.permissions import PERMISSIONS
from app.repositories.profile_repository import ProfileRepository
from app.schemas import ProfileResponse, ProfileUpdate
from app.services.profile_service import ProfileService
from app.services.file_storage import download_path, list_files, original_filename, upload_directory
from app.services.media_preview import image_preview, issue_video_ticket, media_type, text_preview, verify_video_ticket
from app.services.video_preview import cached_video, request_video_preview

router = APIRouter(prefix="/api")
secure_cookie = settings.app_env.lower() not in {"development", "dev", "test"}
cookie_samesite = "none" if secure_cookie else "strict"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
UPLOAD_LOCK = asyncio.Lock()


class AdminLoginRequest(BaseModel):
    password: SecretStr


class UploadLoginRequest(BaseModel):
    email: str
    password: SecretStr


class VideoPreviewRequest(BaseModel):
    file_id: str = Field(min_length=1, max_length=255)
    user_id: int | None = Field(default=None, gt=0)


class PermissionsRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("permissions")
    @classmethod
    def known_permissions(cls, value: list[str]) -> list[str]:
        if any(permission not in PERMISSIONS for permission in value):
            raise ValueError("Unknown permission")
        return sorted(set(value))


class PublicPermissionsRequest(PermissionsRequest):
    @field_validator("permissions")
    @classmethod
    def public_features_only(cls, value: list[str]) -> list[str]:
        if any(permission != "resume:view" for permission in value):
            raise ValueError("Only resume viewing can be granted to visitors")
        return value


class InvitationCreateRequest(PermissionsRequest):
    email: str
    display_name: str | None = None


class InvitationAcceptRequest(BaseModel):
    token: str = Field(max_length=128)
    password: SecretStr


class InvitationLookupRequest(BaseModel):
    token: str = Field(max_length=128)


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


def _user_response(user: UploadUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "displayName": user.display_name,
        "createdAt": user.created_at.isoformat(),
        "active": user.disabled_at is None,
        "permissions": user.permissions,
    }


@router.post("/admin/login", tags=["admin"])
def admin_login(data: AdminLoginRequest, request: Request, response: Response) -> dict[str, str]:
    ensure_auth_is_configured()
    require_frontend_origin(request)
    check_auth_rate_limit(request)
    if not hmac.compare_digest(data.password.get_secret_value(), settings.admin_password or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")
    session_token = create_session()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=secure_cookie,
        samesite=cookie_samesite,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"status": "authenticated", "token": session_token}


@router.get("/admin/session", tags=["admin"])
def admin_session(response: Response, _admin: None = Depends(require_admin)) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"status": "authenticated"}


@router.get("/session", tags=["auth"])
def site_session(response: Response, db: Session = Depends(get_db),
                 access: UploadAccess = Depends(require_upload_access)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    user = db.get(UploadUser, access.user_id) if not access.is_owner else None
    return {"isAdmin": access.is_owner, "email": user.email if user else None,
            "displayName": user.display_name if user else "Administrator",
            "permissions": sorted(access.permissions)}


@router.get("/access", tags=["auth"])
def visitor_access(response: Response, db: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"permissions": public_permissions(db)}


@router.put("/admin/public-access", tags=["admin"])
def update_public_access(data: PublicPermissionsRequest, response: Response,
                         db: Session = Depends(get_db), _admin: None = Depends(require_admin),
                         _origin: None = Depends(require_frontend_origin)) -> dict:
    if data.permissions != ["resume:view"]:
        raise HTTPException(status_code=409, detail="The intro and resume are public. File access always requires sign-in.")
    response.headers["Cache-Control"] = "no-store"
    return {"permissions": public_permissions(db)}


@router.get("/admin/permissions", tags=["admin"])
def permission_catalog(response: Response, _admin: None = Depends(require_admin)) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    return [{"key": key, "label": label} for key, label in PERMISSIONS.items()]


@router.put("/admin/upload-users/{user_id}/permissions", tags=["admin"])
def update_user_permissions(user_id: int, data: PermissionsRequest, response: Response,
                           db: Session = Depends(get_db), _admin: None = Depends(require_admin),
                           _origin: None = Depends(require_frontend_origin)) -> dict:
    user = db.get(UploadUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    user.permissions = data.permissions
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _user_response(user)


@router.post("/admin/invitations", tags=["admin"])
def create_upload_invitation(
    data: InvitationCreateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
    _origin: None = Depends(require_frontend_origin),
) -> dict[str, str | int]:
    email = _normalize_email(data.email)
    if db.scalar(select(UploadUser.id).where(UploadUser.email == email)):
        raise HTTPException(status_code=409, detail="An upload account already uses this email")
    now = utcnow()
    db.execute(
        update(UploadInvitation)
        .where(UploadInvitation.email == email, UploadInvitation.accepted_at.is_(None), UploadInvitation.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    invitation = UploadInvitation(
        email=email,
        display_name=(data.display_name or "").strip()[:160] or None,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_at=now,
        expires_at=now + timedelta(days=7),
        permissions=data.permissions,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    response.headers["Cache-Control"] = "no-store"
    return {"id": invitation.id, "email": email, "token": token, "expiresAt": invitation.expires_at.isoformat()}


@router.get("/admin/invitations", tags=["admin"])
def list_upload_invitations(
    response: Response,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    invitations = db.scalars(select(UploadInvitation).order_by(UploadInvitation.created_at.desc())).all()
    now = utcnow()
    return [{
        "id": invite.id,
        "email": invite.email,
        "displayName": invite.display_name,
        "expiresAt": invite.expires_at.isoformat(),
        "accepted": invite.accepted_at is not None,
        "revoked": invite.revoked_at is not None,
        "permissions": invite.permissions,
        "expired": invite.expires_at.replace(tzinfo=timezone.utc) <= now if invite.expires_at.tzinfo is None else invite.expires_at <= now,
    } for invite in invitations]


@router.post("/admin/invitations/{invitation_id}/revoke", tags=["admin"])
def revoke_upload_invitation(
    invitation_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
    _origin: None = Depends(require_frontend_origin),
) -> dict[str, str]:
    invitation = db.get(UploadInvitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at is None:
        invitation.revoked_at = utcnow()
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"status": "revoked"}


@router.get("/admin/upload-users", tags=["admin"])
def list_upload_users(
    response: Response,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    users = db.scalars(select(UploadUser).order_by(UploadUser.created_at.desc())).all()
    return [_user_response(user) for user in users]


@router.post("/admin/upload-users/{user_id}/disable", tags=["admin"])
def disable_upload_user(
    user_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
    _origin: None = Depends(require_frontend_origin),
) -> dict[str, str]:
    user = db.get(UploadUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Upload account not found")
    user.disabled_at = user.disabled_at or utcnow()
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"status": "disabled"}


@router.post("/upload/invitations/accept", tags=["upload"])
def accept_upload_invitation(
    data: InvitationAcceptRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _origin: None = Depends(require_frontend_origin),
) -> dict[str, str | int]:
    check_auth_rate_limit(request)
    password = data.password.get_secret_value()
    if len(password) < 12 or len(password) > 256:
        raise HTTPException(status_code=422, detail="Choose a password between 12 and 256 characters")
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    invitation = db.scalar(select(UploadInvitation).where(UploadInvitation.token_hash == token_hash))
    now = utcnow()
    if invitation is None or invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise HTTPException(status_code=400, detail="This invitation is invalid or has already been used")
    expires_at = invitation.expires_at.replace(tzinfo=timezone.utc) if invitation.expires_at.tzinfo is None else invitation.expires_at
    if expires_at <= now:
        raise HTTPException(status_code=400, detail="This invitation has expired")
    if db.scalar(select(UploadUser.id).where(UploadUser.email == invitation.email)):
        raise HTTPException(status_code=409, detail="An upload account already exists for this invitation")
    claimed = db.execute(
        update(UploadInvitation)
        .where(
            UploadInvitation.id == invitation.id,
            UploadInvitation.accepted_at.is_(None),
            UploadInvitation.revoked_at.is_(None),
            UploadInvitation.expires_at > now,
        )
        .values(accepted_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This invitation is invalid or has already been used")
    user = UploadUser(
        email=invitation.email,
        display_name=invitation.display_name,
        password_hash=hash_password(password),
        created_at=now,
        permissions=list(invitation.permissions),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "created", "email": user.email, "userId": user.id}


@router.post("/upload/invitations/validate", tags=["upload"])
def get_upload_invitation(
    data: InvitationLookupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _origin: None = Depends(require_frontend_origin),
) -> dict:
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    invitation = db.scalar(select(UploadInvitation).where(UploadInvitation.token_hash == token_hash))
    if invitation is None or invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise HTTPException(status_code=404, detail="This invitation is invalid, expired, or already used")
    expires_at = invitation.expires_at.replace(tzinfo=timezone.utc) if invitation.expires_at.tzinfo is None else invitation.expires_at
    if expires_at <= utcnow():
        raise HTTPException(status_code=404, detail="This invitation is invalid, expired, or already used")
    response.headers["Cache-Control"] = "no-store"
    return {"email": invitation.email, "displayName": invitation.display_name, "expiresAt": expires_at.isoformat(), "permissions": invitation.permissions}


@router.post("/upload/login", tags=["upload"])
def upload_user_login(
    data: UploadLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _origin: None = Depends(require_frontend_origin),
) -> dict[str, str | int | None]:
    email = _normalize_email(data.email)
    check_auth_rate_limit(request)
    password = data.password.get_secret_value()
    if len(password) > 256:
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    user = db.scalar(select(UploadUser).where(UploadUser.email == email))
    if user is None or user.disabled_at is not None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {"status": "authenticated", "token": create_upload_session(user.id), "email": user.email, "displayName": user.display_name}


@router.get("/upload/session", tags=["upload"])
def upload_user_session(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str | int | None]:
    user_id = upload_session_user_id(request.headers.get("authorization", "")[7:].strip() if request.headers.get("authorization", "").lower().startswith("bearer ") else None)
    user = db.get(UploadUser, user_id) if user_id is not None else None
    if user is None or user.disabled_at is not None:
        raise HTTPException(status_code=401, detail="Sign in to upload")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "authenticated", "email": user.email, "displayName": user.display_name}


@router.post("/admin/logout", tags=["admin"])
def admin_logout(request: Request, response: Response) -> dict[str, str]:
    require_frontend_origin(request)
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=secure_cookie,
        samesite=cookie_samesite,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"status": "logged out"}


@router.post("/admin/photos", tags=["admin"])
async def upload_admin_photo(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    access: UploadAccess = Depends(require_permission("files:upload")),
    _origin: None = Depends(require_frontend_origin),
) -> dict[str, str | int | bool]:
    filename = unquote(request.headers.get("x-file-name", "")).strip()
    if (not filename or filename in {".", ".."} or "/" in filename or "\\" in filename or "\x00" in filename
            or any(ord(character) < 32 or ord(character) == 127 for character in filename)
            or len(filename.encode("utf-8")) > 180):
        raise HTTPException(status_code=400, detail="A valid file name is required")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Files must be 500 MB or smaller")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid content length") from exc

    user = None if access.is_owner else db.get(UploadUser, access.user_id)
    directory = upload_directory(user, create=True)
    upload_id = uuid4().hex
    temporary = directory / f".{upload_id}.uploading"
    total_bytes = 0
    content_hash = hashlib.sha256()
    try:
        with temporary.open("xb") as output:
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Files must be 500 MB or smaller")
                content_hash.update(chunk)
                output.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty")
        digest = content_hash.hexdigest()
        async with UPLOAD_LOCK:
            duplicate = any(path.is_file() and not path.is_symlink() for path in directory.glob(f"{digest}_*"))
            if not duplicate:
                destination = directory / f"{digest}_{filename}"
                temporary.replace(destination)
    except HTTPException:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise HTTPException(status_code=507, detail="The photo drive is full") from exc
        raise HTTPException(status_code=503, detail="Could not save the file to photo storage") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)

    response.headers["Cache-Control"] = "no-store"
    return {"filename": filename, "bytes": total_bytes, "duplicate": duplicate}


def _storage_account(user_id: int | None, db: Session) -> UploadUser | None:
    if user_id is None:
        return None
    user = db.get(UploadUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Upload account not found")
    return user


@router.get("/admin/files", tags=["admin"])
def admin_files(response: Response, user_id: int | None = None,
                db: Session = Depends(get_db), _admin: None = Depends(require_admin)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return list_files(_storage_account(user_id, db), admin=True)


@router.get("/upload/files", tags=["upload"])
def uploader_files(response: Response, db: Session = Depends(get_db),
                   access: UploadAccess = Depends(require_permission("files:view"))) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return list_files(_storage_account(access.user_id, db), admin=False)


def _download(user: UploadUser | None, file_id: str) -> FileResponse:
    path = download_path(user, file_id)
    return FileResponse(path, filename=original_filename(file_id), media_type="application/octet-stream", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })


@router.get("/admin/files/download", tags=["admin"])
def admin_download(file_id: str, user_id: int | None = None, db: Session = Depends(get_db),
                   _admin: None = Depends(require_admin)) -> FileResponse:
    return _download(_storage_account(user_id, db), file_id)


def _preview_account(access: UploadAccess, db: Session, user_id: int | None) -> UploadUser | None:
    if access.is_owner:
        return _storage_account(user_id, db)
    if "files:view" not in access.permissions:
        raise HTTPException(status_code=403, detail="Your account does not have access to file previews")
    if user_id is not None and user_id != access.user_id:
        raise HTTPException(status_code=403, detail="You can only view your own media")
    return _storage_account(access.user_id, db)


def _preview_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, noarchive"}


@router.get("/files/image", tags=["media"])
def preview_image(file_id: str, thumbnail: bool = False, user_id: int | None = None,
                  db: Session = Depends(get_db), access: UploadAccess = Depends(require_upload_access)) -> FileResponse:
    user = _preview_account(access, db, user_id)
    path = image_preview(download_path(user, file_id), thumbnail=thumbnail)
    return FileResponse(path, media_type="image/webp", headers=_preview_headers(),
                        filename="preview.webp", content_disposition_type="inline")

@router.get("/files/text", tags=["media"])
def preview_text(response: Response, file_id: str, user_id: int | None = None,
                 db: Session = Depends(get_db), access: UploadAccess = Depends(require_upload_access)) -> dict:
    user = _preview_account(access, db, user_id)
    path = download_path(user, file_id)
    if not (media := media_type(path)) or media[0] != "text":
        raise HTTPException(status_code=415, detail="Text preview is not available for this file")
    response.headers.update(_preview_headers())
    return text_preview(path)

@router.get("/files/pdf", tags=["media"])
def preview_pdf(file_id: str, user_id: int | None = None, db: Session = Depends(get_db), access: UploadAccess = Depends(require_upload_access)) -> FileResponse:
    user = _preview_account(access, db, user_id)
    path = download_path(user, file_id)
    if not (media := media_type(path)) or media[0] != "pdf":
        raise HTTPException(status_code=415, detail="PDF preview is not available for this file")
    if path.stat().st_size > 32 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF previews are limited to 32 MB")
    return FileResponse(path, media_type="application/pdf", headers=_preview_headers(), filename=original_filename(file_id), content_disposition_type="inline")


@router.post("/files/video-ticket", tags=["media"])
def video_preview_ticket(data: VideoPreviewRequest, request: Request, response: Response,
                         db: Session = Depends(get_db), access: UploadAccess = Depends(require_upload_access),
                         _origin: None = Depends(require_frontend_origin)) -> dict:
    user = _preview_account(access, db, data.user_id)
    path = download_path(user, data.file_id)
    media = media_type(path)
    if not media or media[0] not in {"video", "audio"}:
        raise HTTPException(status_code=415, detail="Video playback is not available for this file")
    authorization = request.headers.get("authorization", "")
    session = (authorization[7:].strip() if authorization.lower().startswith("bearer ") else "") or request.cookies.get(SESSION_COOKIE, "")
    session_expires = int(session.split(".")[-2]) + SESSION_MAX_AGE
    optimized, preparing = request_video_preview(path) if media[0] == "video" else (False, False)
    ticket, expires = issue_video_ticket(data.file_id, user.id if user else None, access.user_id, session_expires,
                                         "optimized" if optimized else "original")
    response.headers["Cache-Control"] = "no-store"
    return {"ticket": ticket, "expiresAt": expires, "optimized": optimized, "preparing": preparing}


@router.api_route("/files/video", methods=["GET", "HEAD"], tags=["media"])
def preview_video(request: Request, ticket: str = Query(max_length=2048), db: Session = Depends(get_db)) -> FileResponse:
    # Keep limited playback capabilities out of Uvicorn's request logs.
    request.scope["query_string"] = b"ticket=redacted"
    scope = verify_video_ticket(ticket)
    if scope["viewer"] is not None:
        viewer = db.get(UploadUser, scope["viewer"])
        if viewer is None or viewer.disabled_at is not None:
            raise HTTPException(status_code=401, detail="Upload account is unavailable")
        if "files:view" not in (viewer.permissions or []):
            raise HTTPException(status_code=403, detail="File viewing permission has been revoked")
    path = download_path(_storage_account(scope["target"], db), scope["file"])
    media = media_type(path)
    if not media or media[0] not in {"video", "audio"}:
        raise HTTPException(status_code=415, detail="Video playback is not available for this file")
    if scope.get("variant", "original") == "optimized":
        path = cached_video(path)
        if path is None:
            raise HTTPException(status_code=410, detail="This preview has expired; reopen the video")
        media = ("video", "video/mp4")
    return FileResponse(path, media_type=media[1], headers=_preview_headers(),
                        filename="preview" + path.suffix.lower(), content_disposition_type="inline")

@router.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "healthy"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "database": "unavailable"}) from exc

@router.get("/published-resume", response_model=ProfileResponse, tags=["profile"])
def published_resume(response: Response) -> ProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        data = Path(settings.published_resume_path).read_bytes()
    except FileNotFoundError:
        return ProfileResponse()
    profile = ProfileResponse.model_validate_json(data)
    profile.display_name = next(iter((profile.display_name or "").split()), None)
    profile.contact_email = None
    profile.contact_phone = None
    return profile


@router.get("/contact", tags=["profile"])
def public_contact(response: Response) -> dict[str, str | None]:
    response.headers["Cache-Control"] = "no-store"
    return {"contactEmail": None}


@router.get("/profile", response_model=ProfileResponse, response_model_by_alias=True, tags=["profile"])
def get_profile(request: Request, response: Response, db: Session = Depends(get_db)) -> ProfileResponse:
    response.headers["Cache-Control"] = "no-store"
    if has_admin_session(request):
        return ProfileService(ProfileRepository(db)).get_profile()
    return published_resume(response)

@router.put("/profile", response_model=ProfileResponse, response_model_by_alias=True, tags=["profile"])
def update_profile(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
    _origin: None = Depends(require_frontend_origin),
) -> ProfileResponse:
    return ProfileService(ProfileRepository(db)).update_profile(data)


class ContactSubmission(BaseModel):
    sender: str = Field(default="", max_length=120)
    body: str = Field(min_length=1, max_length=4000)


@router.post("/contact/messages", status_code=201)
def send_contact_message(data: ContactSubmission, request: Request, db: Session = Depends(get_db),
                         _origin: None = Depends(require_frontend_origin)):
    if not data.body.strip():
        raise HTTPException(status_code=422, detail="Enter a message.")
    check_auth_rate_limit(request, contact=True)
    db.add(ContactMessage(sender=data.sender.strip(), body=data.body.strip()))
    db.commit()
    return {"sent": True}


@router.get("/admin/contact/messages")
def unread_messages(response: Response, db: Session = Depends(get_db), _admin: None = Depends(require_admin)):
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(select(ContactMessage).where(ContactMessage.is_read.is_(False))
                      .order_by(ContactMessage.id).limit(50))
    return [{"id": row.id, "sender": row.sender, "body": row.body} for row in rows]


@router.put("/admin/contact/messages/{message_id}/read")
def read_contact_message(message_id: int, db: Session = Depends(get_db), _admin: None = Depends(require_admin),
                         _origin: None = Depends(require_frontend_origin)):
    message = db.get(ContactMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    message.is_read = True
    db.commit()
    return {"read": True}
