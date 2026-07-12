from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from astock.dashboard.storage import DashboardStore


SHANGHAI = ZoneInfo("Asia/Shanghai")


def create_app(
    *,
    data_dir: Path | None = None,
    static_dir: Path | None = None,
    allowed_users: set[str] | None = None,
    ingest_token: str | None = None,
) -> FastAPI:
    root = data_dir or Path(os.getenv("ASTOCK_SERVER_DATA_DIR", "./server-data")).resolve()
    static = static_dir or Path(os.getenv("ASTOCK_WEB_STATIC_DIR", "./web/dist")).resolve()
    allowed = allowed_users if allowed_users is not None else {
        item.strip() for item in os.getenv("ASTOCK_ALLOWED_TAILSCALE_USERS", "").split(",") if item.strip()
    }
    token = ingest_token if ingest_token is not None else os.getenv("ASTOCK_SYNC_TOKEN", "")
    store = DashboardStore(root / "server.db", root / "bundles")
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store.close()

    app = FastAPI(title="astock private dashboard", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store = store

    def require_browser_user(tailscale_user_login: str | None = Header(default=None)) -> str:
        if not tailscale_user_login or tailscale_user_login not in allowed:
            raise HTTPException(status_code=403, detail="tailscale user is not allowed")
        return tailscale_user_login

    def require_ingest(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {token}"
        if not token or not authorization or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="invalid ingest credentials")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.put("/api/v1/ingest/bundles/{bundle_id}", dependencies=[Depends(require_ingest)])
    async def ingest_bundle(bundle_id: str, request: Request) -> dict[str, object]:
        bundle = await request.json()
        if bundle.get("bundle_id") != bundle_id:
            raise HTTPException(status_code=400, detail="bundle path id mismatch")
        try:
            created = store.save_bundle(bundle, datetime.now(SHANGHAI))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "created": created}

    @app.put("/api/v1/ingest/live-status/{source_id}", dependencies=[Depends(require_ingest)])
    async def ingest_status(source_id: str, request: Request) -> dict[str, bool]:
        payload = await request.json()
        try:
            store.save_live_status(source_id, payload, datetime.now(SHANGHAI))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    browser = [Depends(require_browser_user)]

    @app.get("/api/v1/overview", dependencies=browser)
    def overview() -> dict:
        bundle = store.latest_bundle()
        now = datetime.now(SHANGHAI)
        return {
            "bundle": bundle,
            "live_status": store.live_statuses(),
            "alerts": store.effective_alerts(now),
        }

    @app.get("/api/v1/accounts", dependencies=browser)
    def accounts() -> list[dict]:
        bundle = store.latest_bundle()
        return bundle.get("accounts", []) if bundle else []

    @app.get("/api/v1/accounts/{account_id}", dependencies=browser)
    def account(account_id: str) -> dict:
        bundle = store.latest_bundle()
        for item in bundle.get("accounts", []) if bundle else []:
            if item.get("account_id") == account_id:
                return item
        raise HTTPException(status_code=404, detail="account not found")

    @app.get("/api/v1/strategies", dependencies=browser)
    def strategies() -> dict:
        bundle = store.latest_bundle()
        return bundle.get("strategy_set", {}) if bundle else {}

    @app.get("/api/v1/orders", dependencies=browser)
    def orders() -> list[dict]:
        bundle = store.latest_bundle()
        return bundle.get("orders", []) if bundle else []

    @app.get("/api/v1/reviews", dependencies=browser)
    def reviews() -> list[dict]:
        return store.bundles()

    @app.get("/api/v1/reviews/{bundle_id}", dependencies=browser)
    def review(bundle_id: str) -> dict:
        bundle = store.load_bundle(bundle_id)
        if not bundle:
            raise HTTPException(status_code=404, detail="review bundle not found")
        return bundle

    @app.get("/api/v1/health", dependencies=browser)
    def health() -> dict:
        return {"sources": store.live_statuses(), "alerts": store.effective_alerts(datetime.now(SHANGHAI))}

    @app.get("/api/v1/alerts", dependencies=browser)
    def alerts() -> list[dict]:
        return store.effective_alerts(datetime.now(SHANGHAI))

    if static.exists():
        assets = static / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", dependencies=browser)
        def spa(path: str) -> FileResponse:
            candidate = static / path
            if path and candidate.is_file() and static in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app
