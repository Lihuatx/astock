from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from astock.dashboard.storage import DashboardStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIVITY_SUMMARY_KEYS = ("message", "code", "reason", "status")


def _overview_bundle(bundle: dict | None) -> dict | None:
    if bundle is None:
        return None
    projected = dict(bundle)
    activity = []
    for event in bundle.get("activity", []):
        item = dict(event)
        payload = event.get("payload", {})
        item["payload"] = (
            {key: payload[key] for key in ACTIVITY_SUMMARY_KEYS if key in payload}
            if isinstance(payload, dict)
            else {}
        )
        activity.append(item)
    projected["activity"] = activity
    return projected


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
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.store = DashboardStore(root / "server.db", root / "bundles")
        try:
            yield
        finally:
            application.state.store.close()

    app = FastAPI(
        title="astock private dashboard",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def store(request: Request) -> DashboardStore:
        return request.app.state.store

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
            created = store(request).save_bundle(bundle, datetime.now(SHANGHAI))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "created": created}

    @app.put("/api/v1/ingest/live-status/{source_id}", dependencies=[Depends(require_ingest)])
    async def ingest_status(source_id: str, request: Request) -> dict[str, bool]:
        payload = await request.json()
        try:
            store(request).save_live_status(source_id, payload, datetime.now(SHANGHAI))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.put("/api/v1/ingest/research/{report_id}", dependencies=[Depends(require_ingest)])
    async def ingest_research(report_id: str, request: Request) -> dict[str, object]:
        payload = await request.json()
        if payload.get("report_id") != report_id:
            raise HTTPException(status_code=400, detail="research path id mismatch")
        try:
            created = store(request).save_research_bundle(payload, datetime.now(SHANGHAI))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "created": created}

    browser = [Depends(require_browser_user)]

    @app.get("/api/v1/overview", dependencies=browser)
    def overview(request: Request) -> dict:
        current = store(request)
        bundle = _overview_bundle(current.latest_bundle())
        now = datetime.now(SHANGHAI)
        return {
            "bundle": bundle,
            "live_status": current.live_statuses(),
            "alerts": current.effective_alerts(now),
            "research": current.research_reports(),
        }

    @app.get("/api/v1/accounts", dependencies=browser)
    def accounts(request: Request) -> list[dict]:
        bundle = store(request).latest_bundle()
        return bundle.get("accounts", []) if bundle else []

    @app.get("/api/v1/accounts/{account_id}", dependencies=browser)
    def account(account_id: str, request: Request) -> dict:
        bundle = store(request).latest_bundle()
        for item in bundle.get("accounts", []) if bundle else []:
            if item.get("account_id") == account_id:
                return item
        raise HTTPException(status_code=404, detail="account not found")

    @app.get("/api/v1/strategies", dependencies=browser)
    def strategies(request: Request) -> dict:
        bundle = store(request).latest_bundle()
        return bundle.get("strategy_set", {}) if bundle else {}

    @app.get("/api/v1/orders", dependencies=browser)
    def orders(request: Request) -> list[dict]:
        bundle = store(request).latest_bundle()
        return bundle.get("orders", []) if bundle else []

    @app.get("/api/v1/reviews", dependencies=browser)
    def reviews(request: Request) -> list[dict]:
        return store(request).bundles()

    @app.get("/api/v1/reviews/{bundle_id}", dependencies=browser)
    def review(bundle_id: str, request: Request) -> dict:
        bundle = store(request).load_bundle(bundle_id)
        if not bundle:
            raise HTTPException(status_code=404, detail="review bundle not found")
        return bundle

    @app.get("/api/v1/health", dependencies=browser)
    def health(request: Request) -> dict:
        current = store(request)
        return {"sources": current.live_statuses(), "alerts": current.effective_alerts(datetime.now(SHANGHAI))}

    @app.get("/api/v1/alerts", dependencies=browser)
    def alerts(request: Request) -> list[dict]:
        return store(request).effective_alerts(datetime.now(SHANGHAI))

    @app.get("/api/v1/research", dependencies=browser)
    def research(request: Request) -> list[dict]:
        return store(request).research_reports()

    @app.get("/api/v1/research/{report_id}", dependencies=browser)
    def research_detail(report_id: str, request: Request) -> dict:
        report = store(request).load_research_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="research report not found")
        return report

    if static.exists():
        @app.get("/{path:path}", dependencies=browser)
        def spa(path: str) -> FileResponse:
            candidate = static / path
            if path and candidate.is_file() and static in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app
