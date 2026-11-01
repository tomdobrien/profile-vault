import hashlib
import base64
import json
import time
from io import BytesIO
from urllib.parse import quote, unquote

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.admin_auth import create_session, create_upload_session
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.upload_user import UploadUser, utcnow
from app.services.file_storage import original_filename
from app.services.media_preview import issue_video_ticket, verify_video_ticket


@pytest.fixture
def backups(tmp_path, monkeypatch):
    from app.services import video_preview
    monkeypatch.setattr(video_preview, "encoder_available", lambda: False)
    monkeypatch.setattr(settings, "photo_upload_dir", str(tmp_path / "backup"))
    monkeypatch.setattr(settings, "photo_upload_mount", None)
    monkeypatch.setattr(settings, "admin_password", "test-owner-password")
    monkeypatch.setattr(settings, "admin_session_secret", "test-session-secret-for-private-files-123456789")
    monkeypatch.setattr(settings, "frontend_origin", "https://site.example")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            UploadUser(id=1, email="alice@example.com", display_name="Alice", password_hash="unused", permissions=["files:upload", "files:view"]),
            UploadUser(id=2, email="bob@example.com", display_name=None, password_hash="unused", permissions=["files:upload", "files:view"]),
        ])
        db.commit()

    def database():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = database
    # No lifespan: use only the isolated in-memory database, never the site's database.
    client = TestClient(app)
    root = tmp_path / "backup"
    alice = root / "users" / "user-1"
    bob = root / "users" / "user-2"
    alice.mkdir(parents=True)
    bob.mkdir(parents=True)
    alice_name = "a" * 64 + "_family photo.jpg"
    (alice / alice_name).write_bytes(b"alice-private-file")
    (bob / ("b" * 64 + "_bob-only.txt")).write_bytes(b"bob-private-file")
    (root / ("c" * 64 + "_owner-only.txt")).write_bytes(b"owner-private-file")
    try:
        yield client, root, engine, {
            "owner": {"Authorization": f"Bearer {create_session()}"},
            "alice": {"Authorization": f"Bearer {create_upload_session(1)}"},
            "bob": {"Authorization": f"Bearer {create_upload_session(2)}"},
        }, alice_name
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_account_can_only_list_its_own_original_filenames(backups):
    client, _, _, tokens, _ = backups
    response = client.get("/api/upload/files?user_id=2", headers=tokens["alice"])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "accountName": "Alice", "email": "alice@example.com", "files": [{"filename": "family photo.jpg"}],
    }
    assert client.get("/api/upload/files", headers=tokens["bob"]).json()["accountName"] == "bob@example.com"


def test_downloads_and_all_account_lists_require_owner_session(backups):
    client, _, _, tokens, name = backups
    for headers in ({}, tokens["alice"]):
        assert client.get("/api/admin/files?user_id=2", headers=headers).status_code == 401
        assert client.get("/api/admin/files/download", params={"user_id": 1, "file_id": name}, headers=headers).status_code == 401
    assert client.get("/api/upload/files").status_code == 401
    assert client.get("/api/upload/files/download", params={"file_id": name}, headers=tokens["alice"]).status_code == 404


def test_owner_lists_named_accounts_and_downloads_attachments(backups):
    client, root, _, tokens, name = backups
    response = client.get("/api/admin/files?user_id=1", headers=tokens["owner"])
    assert response.status_code == 200
    data = response.json()
    assert data["accountName"] == "Alice"
    assert data["files"][0]["filename"] == "family photo.jpg"
    assert data["files"][0]["id"] == name
    download = client.get("/api/admin/files/download", params={"user_id": 1, "file_id": name}, headers=tokens["owner"])
    assert download.content == b"alice-private-file"
    assert download.headers["content-type"] == "application/octet-stream"
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert unquote(disposition).endswith("family photo.jpg")
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in download.headers["content-security-policy"]
    assert (root / "users" / "user-1" / name).exists()
    own = client.get("/api/admin/files", headers=tokens["owner"]).json()
    assert [file["filename"] for file in own["files"]] == ["owner-only.txt"]


def test_download_rejects_paths_hidden_files_and_missing_accounts(backups):
    client, _, _, tokens, name = backups
    for filename in ("../owner-only.txt", "..\\owner-only.txt", ".secret", "x\x00.txt", "x\n.txt"):
        response = client.get("/api/admin/files/download", params={"file_id": filename, "user_id": 1}, headers=tokens["owner"])
        assert response.status_code == 400
    assert client.get("/api/admin/files?user_id=999", headers=tokens["owner"]).status_code == 404
    assert client.get("/api/admin/files/download", params={"file_id": name, "user_id": 2}, headers=tokens["owner"]).status_code == 404


def test_disabled_accounts_cannot_list_but_owner_can_still_browse(backups):
    client, _, engine, tokens, _ = backups
    with Session(engine) as db:
        db.get(UploadUser, 1).disabled_at = utcnow()
        db.commit()
    assert client.get("/api/upload/files", headers=tokens["alice"]).status_code == 401
    assert client.get("/api/admin/files?user_id=1", headers=tokens["owner"]).status_code == 200


def test_uploads_keep_hash_prefix_and_duplicate_detection(backups):
    client, root, _, tokens, _ = backups
    content = b"new file contents"
    headers = {**tokens["alice"], "Origin": "https://site.example", "X-File-Name": quote("budget.txt")}
    response = client.post("/api/admin/photos", content=content, headers=headers)
    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    stored = root / "users" / "user-1" / f"{hashlib.sha256(content).hexdigest()}_budget.txt"
    assert stored.read_bytes() == content
    headers["X-File-Name"] = quote("another name.txt")
    duplicate = client.post("/api/admin/photos", content=content, headers=headers)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert len(list(stored.parent.iterdir())) == 2


def test_linked_files_are_not_listed_or_downloaded(backups):
    client, root, _, tokens, _ = backups
    path = root / "users" / "user-1" / "linked.txt"
    try:
        path.symlink_to(root / ("c" * 64 + "_owner-only.txt"))
    except OSError:
        pytest.skip("This environment cannot create symbolic links")
    listing = client.get("/api/admin/files?user_id=1", headers=tokens["owner"]).json()
    assert not any(item["filename"] == "linked.txt" for item in listing["files"])
    assert client.get("/api/admin/files/download", params={"user_id": 1, "file_id": "linked.txt"}, headers=tokens["owner"]).status_code == 404


def test_display_strips_only_a_recognized_storage_prefix():
    assert original_filename("f" * 64 + "_report_final.pdf") == "report_final.pdf"
    assert original_filename("20261024T123456Z_ab12cd34_photo.jpg") == "photo.jpg"
    assert original_filename("20261024_notes.txt") == "20261024_notes.txt"
    assert original_filename("notes_with_underscores.txt") == "notes_with_underscores.txt"


@pytest.fixture
def media_files(backups):
    _, root, _, _, _ = backups
    directory = root / "users" / "user-1"
    photo = directory / ("d" * 64 + "_portrait.jpg")
    exif = Image.Exif()
    exif[274] = 6  # Phone orientation must survive resizing, while metadata must not.
    exif[271] = "private-camera-metadata"
    with Image.new("RGB", (2400, 1200), "blue") as image:
        image.save(photo, "JPEG", exif=exif)
    movie = directory / ("e" * 64 + "_clip.mp4")
    # Header fixture tests HTTP transport/authorization, not video codec decoding.
    movie.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + bytes(range(128)))
    return photo, movie


def test_supported_media_list_is_scoped_to_the_account(backups, media_files):
    client, _, _, tokens, _ = backups
    photo, movie = media_files
    listing = client.get("/api/upload/files", headers=tokens["alice"]).json()
    items = {item["filename"]: item for item in listing["files"]}
    assert items["portrait.jpg"] == {"filename": "portrait.jpg", "id": photo.name, "mediaType": "image"}
    assert items["clip.mp4"] == {"filename": "clip.mp4", "id": movie.name, "mediaType": "video"}
    assert "portrait.jpg" not in str(client.get("/api/upload/files", headers=tokens["bob"]).json())


def test_image_previews_resize_orient_strip_metadata_and_preserve_original(backups, media_files):
    client, root, _, tokens, _ = backups
    photo, _ = media_files
    before = photo.read_bytes()
    for thumbnail, edge in ((True, 320), (False, 2048)):
        response = client.get("/api/files/image", params={"file_id": photo.name, "thumbnail": thumbnail}, headers=tokens["alice"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert response.headers["content-disposition"].startswith("inline;")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        with Image.open(BytesIO(response.content)) as preview:
            assert max(preview.size) <= edge
            assert preview.height > preview.width
            assert not preview.getexif()
        assert b"private-camera-metadata" not in response.content
    assert photo.read_bytes() == before
    cache = photo.parent / ".media-previews"
    assert len(list(cache.glob("*.webp"))) == 2
    repeat = client.get("/api/files/image", params={"file_id": photo.name}, headers=tokens["alice"])
    assert repeat.status_code == 200
    assert len(list(cache.glob("*.webp"))) == 2
    listing = client.get("/api/admin/files?user_id=1", headers=tokens["owner"]).json()
    assert not any(".media-previews" in file["filename"] for file in listing["files"])


def test_image_preview_authorization_and_owner_account_selection(backups, media_files):
    client, _, _, tokens, _ = backups
    photo, _ = media_files
    assert client.get("/api/files/image", params={"file_id": photo.name}).status_code == 401
    assert client.get("/api/files/image", params={"file_id": photo.name}, headers=tokens["bob"]).status_code == 404
    assert client.get("/api/files/image", params={"file_id": photo.name, "user_id": 1}, headers=tokens["bob"]).status_code == 403
    assert client.get("/api/files/image", params={"file_id": photo.name, "user_id": 1}, headers=tokens["owner"]).status_code == 200
    assert client.get("/api/files/image", params={"file_id": "../owner-only.txt"}, headers=tokens["alice"]).status_code == 400


def _video_ticket(client, tokens, movie, account="alice", user_id=None):
    response = client.post("/api/files/video-ticket", json={"file_id": movie.name, "user_id": user_id},
                           headers={**tokens[account], "Origin": "https://site.example"})
    assert response.status_code == 200
    return response.json()["ticket"]


def test_video_stream_supports_ranges_head_and_cannot_authorize_download(backups, media_files):
    client, _, _, tokens, _ = backups
    _, movie = media_files
    ticket = _video_ticket(client, tokens, movie)
    response = client.get("/api/files/video", params={"ticket": ticket}, headers={"Range": "bytes=4-15"})
    assert response.status_code == 206
    assert response.content == movie.read_bytes()[4:16]
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 4-15/{movie.stat().st_size}"
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    head = client.head("/api/files/video", params={"ticket": ticket})
    assert head.status_code == 200 and head.content == b""
    for authorization in (tokens["alice"], {"Authorization": "Bearer " + ticket}):
        assert client.get("/api/admin/files/download", params={"file_id": movie.name, "user_id": 1}, headers=authorization).status_code == 401


def test_video_tickets_reject_other_accounts_bad_origins_and_unsupported_files(backups, media_files):
    client, _, _, tokens, _ = backups
    photo, movie = media_files
    body = {"file_id": movie.name, "user_id": 1}
    assert client.post("/api/files/video-ticket", json=body, headers={**tokens["bob"], "Origin": "https://site.example"}).status_code == 403
    assert client.post("/api/files/video-ticket", json=body, headers={**tokens["alice"], "Origin": "https://bad.example"}).status_code == 403
    assert client.post("/api/files/video-ticket", json={"file_id": photo.name}, headers={**tokens["alice"], "Origin": "https://site.example"}).status_code == 415
    assert client.get("/api/files/video", params={"ticket": "not-a-ticket"}).status_code == 401
    owner_ticket = _video_ticket(client, tokens, movie, "owner", 1)
    assert client.get("/api/files/video", params={"ticket": owner_ticket}).status_code == 200


def test_video_ticket_tampering_expiration_and_account_disabling(backups, media_files):
    client, _, engine, tokens, _ = backups
    _, movie = media_files
    ticket = _video_ticket(client, tokens, movie)
    encoded, signature = ticket.split(".")
    scope = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    scope["target"] = 2
    changed = base64.urlsafe_b64encode(json.dumps(scope).encode()).rstrip(b"=").decode()
    assert client.get("/api/files/video", params={"ticket": changed + "." + signature}).status_code == 401
    expired, _ = issue_video_ticket(movie.name, 1, 1, int(time.time()) - 1)
    assert client.get("/api/files/video", params={"ticket": expired}).status_code == 401
    session_end = int(time.time()) + 30
    bounded, expires = issue_video_ticket(movie.name, 1, 1, session_end)
    assert expires == session_end and verify_video_ticket(bounded)["expires"] == session_end
    with Session(engine) as db:
        db.get(UploadUser, 1).disabled_at = utcnow()
        db.commit()
    assert client.get("/api/files/video", params={"ticket": ticket}).status_code == 401


def test_active_file_types_are_never_previewed_and_large_images_are_rejected(backups, media_files, monkeypatch):
    client, _, _, tokens, _ = backups
    photo, _ = media_files
    for name in ("disguised.jpg", "script.svg", "page.html"):
        path = photo.parent / name
        path.write_text('<svg onload="alert(1)"></svg>', encoding="utf-8")
        response = client.get("/api/files/image", params={"file_id": name}, headers=tokens["alice"])
        assert response.status_code == 415
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    response = client.get("/api/files/image", params={"file_id": photo.name}, headers=tokens["alice"])
    assert response.status_code == 413


def test_text_previews_are_bounded_inert_and_account_scoped(backups):
    from app.services.media_preview import TEXT_PREVIEW_BYTES

    client, root, _, tokens, _ = backups
    directory = root / "users" / "user-1"
    samples = {"Makefile": b"all:\n\techo hello", "source.unusual": b"print('hello')",
               "page.html": b'<script>alert("unsafe")</script>',
               "unicode.txt": "hello \u2603".encode("utf-16"), "binary.txt": b"\x00\xff\x01"}
    for name, content in samples.items():
        (directory / name).write_bytes(content)
    items = {item["filename"]: item for item in client.get("/api/upload/files", headers=tokens["alice"]).json()["files"]}
    assert items["Makefile"]["mediaType"] == "text"
    assert items["source.unusual"]["mediaType"] == "text"
    assert "mediaType" not in items["binary.txt"]
    for name in ("Makefile", "source.unusual", "page.html", "unicode.txt"):
        response = client.get("/api/files/text", params={"file_id": name}, headers=tokens["alice"])
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["text"] == samples[name].decode("utf-16" if name == "unicode.txt" else "utf-8")
        assert response.json()["truncated"] is False
    assert client.get("/api/files/text", params={"file_id": "Makefile"}).status_code == 401
    assert client.get("/api/files/text", params={"file_id": "Makefile"}, headers=tokens["bob"]).status_code == 404
    assert client.get("/api/files/text", params={"file_id": "Makefile", "user_id": 1}, headers=tokens["bob"]).status_code == 403
    assert client.get("/api/files/text", params={"file_id": "binary.txt"}, headers=tokens["alice"]).status_code == 415
    (directory / "large.log").write_bytes(b"a" * (TEXT_PREVIEW_BYTES + 100))
    result = client.get("/api/files/text", params={"file_id": "large.log"}, headers=tokens["alice"]).json()
    assert len(result["text"]) == TEXT_PREVIEW_BYTES and result["truncated"] is True


def test_pdf_and_audio_access_and_pdf_size_bound(backups):
    client, root, _, tokens, _ = backups
    directory = root / "users" / "user-1"
    (directory / "document.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    (directory / "sound.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 32)
    assert client.get("/api/files/pdf", params={"file_id": "document.pdf"}).status_code == 401
    assert client.get("/api/files/pdf", params={"file_id": "document.pdf"}, headers=tokens["bob"]).status_code == 404
    assert client.get("/api/files/pdf", params={"file_id": "document.pdf"}, headers=tokens["alice"]).headers["content-type"] == "application/pdf"
    ticket = _video_ticket(client, tokens, directory / "sound.wav")
    response = client.get("/api/files/video", params={"ticket": ticket}, headers={"Range": "bytes=0-3"})
    assert response.status_code == 206 and response.content == b"RIFF"
    with (directory / "document.pdf").open("r+b") as source:
        source.truncate(32 * 1024 * 1024 + 1)
    assert client.get("/api/files/pdf", params={"file_id": "document.pdf"}, headers=tokens["alice"]).status_code == 413


def test_upload_limit_checks_headers_and_stream_and_removes_partial_files(backups, monkeypatch):
    from app.api import routes

    client, root, _, tokens, _ = backups
    assert routes.MAX_UPLOAD_BYTES == 500 * 1024 * 1024
    monkeypatch.setattr(routes, "MAX_UPLOAD_BYTES", 8)
    headers = {**tokens["alice"], "Origin": "https://site.example", "X-File-Name": "boundary.txt"}
    assert client.post("/api/admin/photos", content=b"12345678", headers=headers).status_code == 200
    assert client.post("/api/admin/photos", content=b"123456789", headers=headers).status_code == 413
    streamed = client.post("/api/admin/photos", content=iter([b"1234", b"56789"]), headers=headers)
    assert streamed.status_code == 413
    assert not list((root / "users" / "user-1").glob("*.uploading"))


def test_permission_changes_apply_to_existing_sessions_and_playback_tickets(backups, media_files):
    client, _, _, tokens, _ = backups
    photo, movie = media_files
    ticket = _video_ticket(client, tokens, movie)
    owner = {**tokens["owner"], "Origin": "https://site.example"}
    assert client.put("/api/admin/upload-users/1/permissions", json={"permissions": []}, headers=owner).status_code == 200
    assert client.get("/api/session", headers=tokens["alice"]).json()["permissions"] == []
    assert client.get("/api/profile", headers=tokens["alice"]).status_code == 200
    assert client.get("/api/upload/files", headers=tokens["alice"]).status_code == 403
    for route in ("image", "text", "pdf"):
        assert client.get(f"/api/files/{route}", params={"file_id": photo.name}, headers=tokens["alice"]).status_code == 403
    assert client.post("/api/admin/photos", content=b"private", headers={**tokens["alice"], "Origin": "https://site.example", "X-File-Name": "blocked.txt"}).status_code == 403
    assert client.get("/api/files/video", params={"ticket": ticket}).status_code == 403
    assert client.post("/api/files/video-ticket", json={"file_id": movie.name}, headers={**tokens["alice"], "Origin": "https://site.example"}).status_code == 403
    assert client.get("/api/admin/files?user_id=1", headers=tokens["owner"]).status_code == 200
    for permissions, may_upload, may_view in [(["files:upload"], True, False), (["files:view"], False, True), (["resume:view"], False, False)]:
        assert client.put("/api/admin/upload-users/1/permissions", json={"permissions": permissions}, headers=owner).status_code == 200
        assert client.get("/api/upload/files", headers=tokens["alice"]).status_code == (200 if may_view else 403)
        upload = client.post("/api/admin/photos", content=b"allowed", headers={**tokens["alice"], "Origin": "https://site.example", "X-File-Name": "allowed.txt"})
        assert upload.status_code == (200 if may_upload else 403)
        assert client.get("/api/profile", headers=tokens["alice"]).status_code == 200


def test_published_resume_only_exposes_public_contact(backups, tmp_path, monkeypatch):
    client, _, _, tokens, _ = backups
    published = tmp_path / "resume.json"
    monkeypatch.setattr(settings, "published_resume_path", str(published))
    published.write_text(json.dumps({"displayName": "Test Surname", "contactPhone": "555-0100",
                                     "contactEmail": "contact@example.com"}))
    for path, headers in [("/api/published-resume", {}), ("/api/profile", {}), ("/api/profile", tokens["alice"])]:
        response = client.get(path, headers=headers)
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["displayName"] == "Test"
        assert response.json()["contactPhone"] is None
    assert client.get("/api/contact").json() == {"contactEmail": "contact@example.com"}
    owner_headers = {**tokens["owner"], "Origin": "https://site.example"}
    private = {"displayName": "Private Surname", "contactPhone": "555-0199"}
    assert client.put("/api/profile", headers=owner_headers, json=private).status_code == 200
    assert client.get("/api/profile", headers=tokens["owner"]).json()["contactPhone"] == private["contactPhone"]
    published.unlink()
    assert client.get("/api/contact").json() == {"contactEmail": None}
    assert client.get("/api/profile").json()["displayName"] is None


def test_only_admin_can_change_permissions_and_public_access(backups):
    client, _, _, tokens, _ = backups
    for headers in ({"Origin": "https://site.example"}, {**tokens["alice"], "Origin": "https://site.example"}):
        assert client.put("/api/admin/upload-users/1/permissions", json={"permissions": ["resume:view"]}, headers=headers).status_code == 401
        assert client.put("/api/admin/public-access", json={"permissions": ["resume:view"]}, headers=headers).status_code == 401
        assert client.get("/api/admin/permissions", headers=headers).status_code == 401
    owner = {**tokens["owner"], "Origin": "https://site.example"}
    assert client.put("/api/admin/upload-users/1/permissions", json={"permissions": ["admin"]}, headers=owner).status_code == 422
    assert client.put("/api/admin/public-access", json={"permissions": ["files:view"]}, headers=owner).status_code == 422
    assert client.put("/api/admin/public-access", json={"permissions": ["files:upload"]}, headers=owner).status_code == 422
    assert client.put("/api/admin/upload-users/1/permissions", json={"permissions": []}, headers={**tokens["owner"], "Origin": "https://bad.example"}).status_code == 403
    assert client.put("/api/admin/public-access", json={"permissions": []}, headers={**tokens["owner"], "Origin": "https://bad.example"}).status_code == 403
    assert client.get("/api/access").json() == {"permissions": ["resume:view"]}
    assert client.get("/api/profile").status_code == 200
    assert client.put("/api/admin/public-access", json={"permissions": ["resume:view"]}, headers=owner).status_code == 200
    assert client.get("/api/access").json() == {"permissions": ["resume:view"]}
    public = client.get("/api/profile")
    assert public.status_code == 200 and public.headers["cache-control"] == "no-store"
    assert client.get("/api/upload/files").status_code == 401
    assert client.put("/api/admin/public-access", json={"permissions": []}, headers=owner).status_code == 409
    assert client.get("/api/profile").status_code == 200
    assert client.get("/api/profile", headers=tokens["owner"]).status_code == 200


def test_invitation_permissions_cannot_be_chosen_or_escalated_by_recipient(backups, monkeypatch):
    from app.api import admin_auth

    client, _, engine, tokens, _ = backups
    monkeypatch.setattr(admin_auth, "_auth_attempts", admin_auth.defaultdict(admin_auth.deque))
    owner = {**tokens["owner"], "Origin": "https://site.example"}
    catalog = client.get("/api/admin/permissions", headers=tokens["owner"]).json()
    assert {item["key"] for item in catalog} == {"resume:view", "files:upload", "files:view"}
    for index, selected in enumerate(([], ["files:view"])):
        email = f"invited{index}@example.com"
        created = client.post("/api/admin/invitations", json={"email": email, "display_name": "Friend", "permissions": selected}, headers=owner)
        assert created.status_code == 200
        token = created.json()["token"]
        lookup = client.post("/api/upload/invitations/validate", json={"token": token}, headers={"Origin": "https://site.example"})
        assert lookup.json()["permissions"] == selected
        acceptance = {"token": token, "password": "a-long-test-password", "permissions": ["resume:view", "files:upload", "admin"]}
        assert client.post("/api/upload/invitations/accept", json=acceptance, headers={"Origin": "https://site.example"}).status_code == 200
        assert client.post("/api/upload/invitations/accept", json=acceptance, headers={"Origin": "https://site.example"}).status_code == 400
        with Session(engine) as db:
            from sqlalchemy import select
            user = db.scalar(select(UploadUser).where(UploadUser.email == email))
            assert user.permissions == selected and user.display_name == "Friend"
        login = client.post("/api/upload/login", json={"email": email, "password": acceptance["password"]}, headers={"Origin": "https://site.example"})
        session = client.get("/api/session", headers={"Authorization": "Bearer " + login.json()["token"]}).json()
        assert session["permissions"] == selected and session["isAdmin"] is False
    assert client.post("/api/admin/invitations", json={"email": "x@example.com", "permissions": ["admin"]}, headers=owner).status_code == 422


def test_disabled_account_cannot_use_site_session_or_profile(backups):
    client, _, engine, tokens, _ = backups
    with Session(engine) as db:
        user = db.get(UploadUser, 1)
        user.permissions = ["resume:view"]
        user.disabled_at = utcnow()
        db.commit()
    assert client.get("/api/session", headers=tokens["alice"]).status_code == 401
    assert client.get("/api/profile", headers=tokens["alice"]).status_code == 200


def test_cached_video_tickets_keep_variants_stable_and_permissions_enforced(backups, media_files):
    from app.services import video_preview

    client, _, engine, tokens, _ = backups
    _, movie = media_files
    original_ticket = _video_ticket(client, tokens, movie)
    cache = video_preview._cache() / f"v1-{video_preview._key(movie)}.mp4"
    cache.write_bytes(b"optimized-private-preview-contents")
    response = client.post("/api/files/video-ticket", json={"file_id": movie.name}, headers={**tokens["alice"], "Origin": "https://site.example"})
    assert response.json()["optimized"] is True and response.json()["preparing"] is False
    ticket = response.json()["ticket"]
    assert verify_video_ticket(ticket)["variant"] == "optimized"
    encoded, signature = original_ticket.split(".")
    scope = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    scope["variant"] = "optimized"
    changed = base64.urlsafe_b64encode(json.dumps(scope).encode()).rstrip(b"=").decode()
    assert client.get("/api/files/video", params={"ticket": changed + "." + signature}).status_code == 401
    assert client.get("/api/files/video", params={"ticket": original_ticket}).content == movie.read_bytes()
    assert client.get("/api/files/video", params={"ticket": ticket}, headers={"Range": "bytes=0-8"}).content == cache.read_bytes()[:9]
    assert client.head("/api/files/video", params={"ticket": ticket}).headers["content-type"] == "video/mp4"
    assert client.get("/api/files/video-ticket", headers=tokens["bob"]).status_code == 405
    with Session(engine) as db:
        db.get(UploadUser, 1).permissions = []
        db.commit()
    assert client.get("/api/files/video", params={"ticket": ticket}).status_code == 403
    assert client.get("/api/admin/files/download", params={"file_id": movie.name, "user_id": 1}, headers=tokens["alice"]).status_code == 401
    with Session(engine) as db:
        db.get(UploadUser, 1).permissions = ["files:view"]
        db.commit()
    cache.unlink()
    assert client.get("/api/files/video", params={"ticket": ticket}).status_code == 410
    assert client.get("/api/files/video", params={"ticket": original_ticket}).content == movie.read_bytes()
