from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import auth, campaigns, cast, combat, entities, oauth, users, workspace
from app.core.config import settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Authlib keeps the OAuth state/nonce here between the redirect out and back
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        same_site="lax",
        https_only=settings.COOKIE_SECURE,
    )

    # allow_credentials is what lets the refresh cookie travel; it forbids the
    # "*" origin, so CORS_ORIGINS has to list the frontend explicitly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
    app.include_router(oauth.router, prefix=settings.API_V1_PREFIX)
    app.include_router(users.router, prefix=settings.API_V1_PREFIX)
    app.include_router(workspace.router, prefix=settings.API_V1_PREFIX)
    app.include_router(campaigns.router, prefix=settings.API_V1_PREFIX)
    app.include_router(entities.router, prefix=settings.API_V1_PREFIX)
    app.include_router(cast.router, prefix=settings.API_V1_PREFIX)
    app.include_router(combat.router, prefix=settings.API_V1_PREFIX)

    # Uploaded avatars. Behind a CDN or object store in production — see
    # app/services/media.py.
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.UPLOAD_URL_PREFIX,
        StaticFiles(directory=upload_dir),
        name="uploads",
    )

    # An unhandled exception is re-raised above the CORS middleware, so the
    # browser reports "blocked by CORS policy" and hides the real cause.
    # Turning a dead database into a handled 503 keeps the headers — and tells
    # you what actually went wrong.
    # Only connection-level failures. DBAPIError is deliberately NOT here: it
    # is the base class for every database error, so catching it would dress a
    # genuine SQL bug up as "database unavailable" and hide it.
    # ConnectionError is, because asyncpg raises a bare ConnectionRefusedError
    # when the server isn't listening — SQLAlchemy never gets to wrap it.
    @app.exception_handler(ConnectionError)
    @app.exception_handler(OperationalError)
    async def database_unavailable(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Database unavailable. Is Postgres running? "
                "Try: docker compose up -d db"
            },
        )

    @app.get("/health", tags=["meta"])
    async def health() -> JSONResponse:
        """Reports the database too, so `curl /health` answers the first
        question you'd ask when something 503s."""
        database = "ok"

        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            database = "unavailable"

        return JSONResponse(
            status_code=status.HTTP_200_OK
            if database == "ok"
            else status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "ok" if database == "ok" else "degraded",
                "database": database,
                "environment": settings.ENVIRONMENT,
            },
        )

    return app


app = create_app()
