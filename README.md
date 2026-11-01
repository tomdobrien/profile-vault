# Profile Vault

A local-first personal profile and resume site: FastAPI + SQLAlchemy + SQLite behind a Next.js / TypeScript frontend. Profile fields start empty; add real owner-provided content before sharing the site.

## Requirements

- Python 3.10+ (tested with Python 3.12)
- Node.js 18.18+ and npm

## Run locally

Run the services from the repository root with npm:

```powershell
npm run backend   # Backend only
npm run frontend  # Frontend only
npm run dev       # Both services; Ctrl+C stops both
```

In VS Code, open **Explorer** in the left sidebar, then expand **NPM Scripts** near the bottom. Under `frontend\package.json`, run `dev` for the frontend, `backend` for the API, or `dev:all` for both. These entries run in VS Code's integrated terminal; press `Ctrl+C` there to stop them.

### Backend

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload --port 8001
```

Startup creates the tables, applies pending Alembic migrations, and uses `./data/profile.db` by default. Set `DATABASE_URL` in a root `.env` file (copy `.env.example`) to configure the database. A standard `postgresql://...` URL is normalized to the included psycopg 3 driver; supply credentials via environment settings.

The `/admin` editor requires `ADMIN_PASSWORD` (at least 8 characters) and `ADMIN_SESSION_SECRET` (at least 32 random characters) in the root `.env` file. Generate values with `python -c "import secrets; print('ADMIN_PASSWORD=' + secrets.token_urlsafe(24)); print('ADMIN_SESSION_SECRET=' + secrets.token_urlsafe(48))"`, then paste both lines into `.env`. The password is never stored in the database. Admin and uploader sign-ins use signed bearer tokens that expire after eight hours. Browser tab session storage retains the token across refreshes and navigation; logout clears it. Closing the tab normally ends local persistence, though browser session restoration may retain it until expiry. If storage is blocked, login works in memory until refresh. Tokens are accessible to site JavaScript, so preventing script injection remains essential. On a production deployment, set `APP_ENV=production`, use HTTPS, and set `FRONTEND_ORIGIN` to the allowed frontend origin(s), comma-separated when needed.

- Health: <http://localhost:8001/api/health>
- Profile JSON: <http://localhost:8001/api/profile>
- OpenAPI docs: <http://localhost:8001/docs>

### Frontend

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

Visit <http://localhost:3000>. Configure `NEXT_PUBLIC_API_URL` in `frontend/.env.local` if the API is elsewhere. The résumé route reads a curated document from the API while it is reachable. Put the public fields in `data/published-resume.json` on the API host (override with `PUBLISHED_RESUME_PATH` if needed). The file follows the profile API schema and stays out of Git. Removing it withdraws the published copy. The owner editor at `/admin/` manages the separate private database profile.

The authenticated `/admin` page also accepts files of any type. Uploads are written to `PHOTO_UPLOAD_DIR` (default `./data/photos`), are limited to 500 MB per file, and are not served publicly. Exact duplicate contents in the destination folder are skipped. Set `PHOTO_UPLOAD_MOUNT` to the mounted external-drive root in production; uploads return an unavailable error if that drive is not mounted.

The owner invites accounts from `/admin` and selects their file upload and browse permissions. New invitations default to no permissions. Invitations are single-use links that expire after seven days; share the link yourself because no email delivery service is configured. The recipient sets a password and signs in on the homepage or protected page. Only the owner admin can change account permissions, revoke invitations, or disable accounts. New features require an explicit grant; ordinary users cannot become admins or modify permissions. Each uploader still writes only to its own `users/user-<id>` subfolder under `PHOTO_UPLOAD_DIR`. Sessions expire after eight hours.

Visitors can read the published résumé without signing in while the Pi is online. Only the first name is served. Public responses clear both phone and email. Visitors can send a message through the Contact page while the Pi is online. Unread messages appear in the private owner dashboard after sign-in. No résumé or email is bundled with the static frontend. The owner can still read the complete stored profile while signed in. Protected file operations check current database permissions on each request.

The upload page lists the signed-in account's original filenames, without displaying the generated storage prefix. In `/admin`, **Browse backup files** identifies accounts by name/email and lets the owner list and download their files. Stored filenames, content hashes, and folder identifiers remain unchanged, including for existing uploads. Downloads require an owner session and are served as attachments; files are never published as public assets.

Accounts can preview their own supported images, videos, audio, text/code files, and PDFs. Text is detected from content, including extensionless files and UTF-8 or BOM-marked UTF-16/32. Only the first 1 MB is displayed, with a truncation notice; HTML, SVG, Markdown, and code appear as literal text and are never executed. PDFs up to 32 MB open in the browser's built-in viewer; larger PDFs can still be uploaded. The native PDF toolbar is requested hidden, but behavior and available controls depend on the browser. JPEG, PNG, WebP, and GIF images get cached WebP thumbnails and display-sized previews (up to 2048 pixels); GIF previews show the first frame. Image derivatives are stored in a hidden `.media-previews` folder next to the originals and exclude the original metadata. Image decoding is serialized and limited to 40 megapixels to protect Pi memory. MP4/M4V, MOV, WebM, and Ogg video plus MP3, WAV, FLAC, M4A, OGA, and Opus audio use the browser's native player; codec support varies. HEIC conversion, Office document rendering, and archive browsing are not included. Unsupported files remain available in the filename list.

Videos opened in the viewer can generate a smaller **480p H.264/AAC MP4** playback copy (24 fps, roughly 4–6 MB/minute). The original remains available while preparation runs; the player checks every 15 seconds and switches to the optimized copy while retaining position and play/pause state. Preparation can be slower than playback on the Pi. Already compact originals are not re-encoded, and failures fall back to original playback. Original downloads, hashes and filenames never change.

The hidden `.video-previews` directory under `PHOTO_UPLOAD_DIR` is a shared **5,000,000,000-byte video cache**, not preallocated space. Only requested videos are processed, one at a time. Old unused derivatives are removed as needed; previews touched within 11 minutes are pinned so active tickets/range requests are not disrupted. One conversion reserves up to 512 MiB within that same budget and requires an additional 256 MiB free on the drive. If all entries are pinned or space is low, original playback continues. Image caches are separate. Partial outputs and zero-copy hard-link input aliases are cleaned up; only generated video-cache files are eligible for eviction.

Conversion requires `/usr/bin/ffmpeg`, `/usr/bin/ffprobe`, and a systemd user manager running `profile-api.service`. Transient workers run at low priority, with 384 MiB memory, no swap, half of one CPU core, 32 tasks, and a 30-minute conversion timeout. A separate namespace exposes only read-only input and writable preview output; home/app secrets, upload storage, process metadata and user-bus sockets are hidden. Network/socket creation, new namespaces and privilege escalation are blocked. Workers stop when the API service stops. No unsandboxed encoding fallback is used on unsupported systems. Inputs over 4K-sized frame limits, corrupt/oversized outputs, or truncated conversions keep the original player path. Each signed ticket fixes either the original or optimized variant, preserving consistent byte ranges. Expired/evicted previews require reopening; authentication, per-account scope and current permissions are checked before serving either variant.

Invited users have no download controls and cannot use the owner download API. Image preview requests require their session; video playback uses file-specific signed tickets that expire within ten minutes and never outlive the login session. Tickets cannot authorize downloads or access another account; disabled accounts lose playback access. The player supports range requests for seeking and renews playback tickets while open. It hides native download controls and suppresses the media context menu. Viewing necessarily transfers preview/video data to the browser, so these UI restrictions do not prevent capture or saving through browser tools. The Pi must be online for previews.

### GitHub Pages deployment

The repository is `tomdobrien/profile-vault` (formerly `AI_Fun`). The Pages frontend is published at <https://tomdobrien.github.io/profile-vault/>. Repository links under the old name redirect, but update bookmarks to the new Pages address.

An existing Pi checkout can remain at `~/AI_Fun`: `deploy/profile-api.service` deliberately retains that on-disk path. Renaming the GitHub repository does not move the server folder. For that existing checkout, update its remote with `git remote set-url origin https://github.com/tomdobrien/profile-vault.git`; a fresh deployment must align the service paths with its actual checkout location.

The workflow in `.github/workflows/pages.yml` builds the frontend as static files and deploys it to GitHub Pages whenever `main` changes. In the repository settings, set **Pages → Build and deployment → Source** to **GitHub Actions**. Add a repository variable named `NEXT_PUBLIC_API_URL` with `https://conradspi4.tailb5b410.ts.net` before deploying. The Pi API is published through Tailscale Funnel and allows the Pages site's origin through `FRONTEND_ORIGIN`.

The frontend uses the Pages base path automatically, including when the repository is published at `https://<owner>.github.io/<repository>/`. The admin editor uses a signed bearer token rather than depending on cross-site cookies, so a custom domain is optional. The Pi service definition is in `deploy/profile-api.service`; it listens only on the Pi's loopback interface. Tailscale Funnel publishes it at `https://conradspi4.tailb5b410.ts.net`.

If the Pi disconnects, the homepage, Guild Bounty and policy text remain available. The UI clears personal details on disconnect or a failed check, and rechecks every 30 seconds while visible, on focus and on reconnect. Protected pages show an unavailable state.

## Database and migrations

Default URL: `sqlite:///./data/profile.db`. SQLAlchemy models, repositories, and services are in `backend/app/`. Alembic is configured in `backend/alembic.ini`; create/apply migrations with `python -m alembic -c backend/alembic.ini revision --autogenerate -m "describe schema change"` and `python -m alembic -c backend/alembic.ini upgrade head` (run with the project environment active). The app creates missing tables on startup for easy local setup. Never add secrets to checked-in environment examples.

## Checks

```powershell
backend/.venv/Scripts/python -m pytest backend/tests
npm --prefix frontend run typecheck
npm --prefix frontend run build
```
