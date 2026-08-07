# DM Master — API

FastAPI backend for [dnd-master-app](https://github.com/lypta-cto/dnd-master-app). Built
on [admin-dashboard-template-back](https://github.com/lypta-cto/admin-dashboard-template-back):
JWT auth, Google sign-in, ranked roles, async Postgres.

> **Status:** MVP-1 backend complete — campaigns, the entity spine, `[[wiki links]]`,
> full-text search, per-entity visibility and the cast channel. See
> [the plan](https://github.com/lypta-cto/dnd-master-app/blob/main/docs/mvp.md).

Runs on **port 8001** with Postgres on **5434**, so it can sit alongside other local
stacks.

Stack: FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, Pydantic v2, PyJWT, Authlib,
Argon2 via pwdlib, pytest, ruff.

## Quick start

```bash
cp .env.example .env
python -m app.cli secret          # paste the output into SECRET_KEY
docker compose up -d db           # Postgres on :5434
uv venv && uv pip install -e ".[dev]"
alembic upgrade head
python -m app.cli seed            # creates the first owner account
python -m app.cli dev             # http://localhost:8001
```

API docs at http://localhost:8001/docs. Sign in with `FIRST_SUPERUSER_EMAIL` /
`FIRST_SUPERUSER_PASSWORD` from your `.env`.

Or run everything in containers: `docker compose up` (migrations run on boot).

## How auth works

Two tokens, on purpose:

| | Lifetime | Where it lives | Why |
| --- | --- | --- | --- |
| **Access** | 15 min | Response body → frontend memory | Short enough that a leak expires fast. Carries the role, so guards need no DB hit. |
| **Refresh** | 30 days | `httpOnly` cookie scoped to `/api/v1/auth` | JavaScript can't read it, so an XSS bug can't steal the long-lived credential. |

Refresh tokens are **rotated**: every call to `/auth/refresh` revokes the old token and
issues a new one. If someone steals a refresh token, it stops working the moment the real
user refreshes. Only a SHA-256 hash is stored, so a leaked database can't be replayed.

Sessions are rows in `refresh_tokens`, which is what makes `logout` real (not just
"forget the token client-side") and lets Settings list active sessions.

### Endpoints

```
POST   /api/v1/auth/register        create account, sets refresh cookie
POST   /api/v1/auth/login           email + password
POST   /api/v1/auth/refresh         rotate cookie → new access token
POST   /api/v1/auth/logout          revoke this session
GET    /api/v1/auth/me              current user
PATCH  /api/v1/auth/me              update own profile
POST   /api/v1/auth/me/avatar       upload a profile photo (multipart)
DELETE /api/v1/auth/me/avatar       remove it
POST   /api/v1/auth/me/password     change password (revokes all sessions)
GET    /api/v1/auth/sessions        where am I signed in
DELETE /api/v1/auth/sessions        sign out everywhere

GET    /api/v1/workspace            public — app name and tagline
PATCH  /api/v1/workspace            admin+ — rename the app

GET    /api/v1/auth/google/authorize    → redirects to Google
GET    /api/v1/auth/google/callback     ← Google redirects here

GET    /api/v1/users                admin+ — list, search, paginate
POST   /api/v1/users                admin+ — create
GET    /api/v1/users/{id}           admin+
PATCH  /api/v1/users/{id}           admin+
DELETE /api/v1/users/{id}           admin+
```

`/users` is also the reference CRUD shape — copy it for your own resources.

## Roles

`viewer < member < admin < owner`, ranked so `can(ADMIN)` is true for owners too. Same
ladder as the frontend's `can()`; keep the two in step.

```python
from app.api.deps import require_role
from app.models.user import Role

@router.delete("/{id}", dependencies=[Depends(require_role(Role.ADMIN))])
async def delete_thing(...): ...
```

Guard rails already in place: you can't change your own role, deactivate or delete your
own account, and only an owner can grant or revoke the owner role.

## Google sign-in

**You have to create the OAuth client — I can't do it for you.**

1. [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
   → Create OAuth client ID → Web application
2. Authorised redirect URI, exactly:
   `http://localhost:8001/api/v1/auth/google/callback`
   (add the production one too when you deploy)
3. Put the client ID and secret in `.env`

Leave them blank and the Google endpoints return `501` with an explanatory message — the
rest of the API works fine.

The flow: the browser hits `/auth/google/authorize` (a plain link, not `fetch`), comes
back to `/callback`, and the backend creates or links the account, sets the refresh
cookie, and redirects to `{FRONTEND_URL}/auth/callback`. The frontend then calls
`/auth/refresh` to get its access token. The access token is never put in a redirect URL,
because query strings end up in browser history and server logs.

Signing in with Google using an email that already has a password account **links** the
two rather than creating a duplicate — but only if Google reports the address as verified,
otherwise anyone able to make an unverified Google account for your address could take
over the local one.

## Workspace and uploads

**Workspace** is a single row holding the app name and tagline — the things that make an
installation *yours*. Reading it is public because the login screen needs the branding
before anyone has signed in; writing needs admin. Rename the app from Settings and the
sidebar, browser tab and login screen all follow, with no redeploy.

**Avatars** are validated by actually decoding them (a file that only *claims* to be an
image fails there, so nothing unexpected reaches disk), flattened onto white, resized to
512 px and re-encoded as WebP. Each upload gets a new filename so caches pick the change
up immediately, and the previous file is deleted.

The stored value is a **relative** path (`/uploads/avatars/x.webp`) so the database
survives a change of host — the frontend prefixes it with the API origin. For anything
running on more than one machine, replace `store_avatar` in
[`app/services/media.py`](app/services/media.py) with an S3 / R2 put that returns the
public URL; nothing else changes.

## Database

Plain Postgres. The only coupling is `DATABASE_URL`, so you can move hosts by changing
one variable.

For [Neon](https://neon.tech): copy the connection string, change the driver to
`postgresql+asyncpg`, and drop `?sslmode=require` — asyncpg negotiates TLS itself.

```
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx.eu-central-1.aws.neon.tech/dbname
```

`pool_pre_ping` is on because Neon suspends idle compute; it reopens connections that
died during a suspend instead of failing the request.

### Migrations

```bash
alembic revision --autogenerate -m "add campaigns"
alembic upgrade head
alembic downgrade -1
```

Always read the generated file before applying it — autogenerate misses renames and
guesses at type changes.

## Tests

```bash
pytest
```

33 tests. Auth (registration, login, token rotation, replay rejection, logout, roles) plus
campaigns, wiki-link resolution, search ranking, visibility leaks and the cast channel.

They run against **real Postgres**, not SQLite: the models depend on JSONB, ARRAY and a
generated `tsvector` column, none of which SQLite can express — a SQLite suite would pass
while telling you nothing about the code that ships. `docker compose up -d db` first; the
suite creates and rebuilds a `dnd_test` database on its own.

## Wiring up the frontend

The frontend's `useAuth()` is currently mocked. To connect it:

- `login()` → `POST /auth/login` with `credentials: 'include'`, keep `access_token` in
  memory (not localStorage — that's readable by XSS)
- `logout()` → `POST /auth/logout`
- On app start and on 401 → `POST /auth/refresh` to get a fresh access token
- Add `/auth/callback` page → calls `/auth/refresh`, then redirects to `/`

`allow_credentials=True` in the CORS config is what lets the cookie travel, and it forbids
the `*` origin — so `CORS_ORIGINS` must name the frontend explicitly.

## Before you deploy

- `COOKIE_SECURE=true` (required for HTTPS)
- `COOKIE_SAMESITE=none` **only** if the API and frontend are on different sites — and
  then `COOKIE_SECURE` must also be true
- A fresh `SECRET_KEY` — rotating it invalidates every access token
- `ENVIRONMENT=production`, `DEBUG=false`
- Change the seeded owner's password

## Not built yet

Email verification, password reset, rate limiting on login, and audit logging. All are
worth adding before this faces the public internet.
