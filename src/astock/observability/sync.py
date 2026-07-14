from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import requests

from astock.observability.repository import ObservabilityRepository


class SyncClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def upload_bundle(self, bundle: dict) -> None:
        response = requests.put(
            f"{self.base_url}/api/v1/ingest/bundles/{bundle['bundle_id']}",
            json=bundle,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def upload_live_status(self, status: dict) -> None:
        response = requests.put(
            f"{self.base_url}/api/v1/ingest/live-status/{status['source_id']}",
            json=status,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def upload_research_bundle(self, bundle: dict) -> None:
        response = requests.put(
            f"{self.base_url}/api/v1/ingest/research/{bundle['report_id']}",
            json=bundle,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()


def dispatch_sync(repository: ObservabilityRepository, client: SyncClient, now: datetime) -> int:
    sent = 0
    for item in repository.pending_sync(now):
        try:
            payload = json.loads(Path(item["payload_path"]).read_text(encoding="utf-8"))
            if item["object_type"] == "BUNDLE":
                client.upload_bundle(payload)
            elif item["object_type"] == "LIVE_STATUS":
                client.upload_live_status(payload)
            elif item["object_type"] == "RESEARCH_BUNDLE":
                client.upload_research_bundle(payload)
            else:
                raise ValueError(f"unsupported sync object type: {item['object_type']}")
        except Exception as exc:
            delay = min(300, 2 ** min(int(item["attempts"]) + 1, 8))
            repository.mark_sync_failed(item["outbox_id"], str(exc), now + timedelta(seconds=delay))
        else:
            repository.mark_sync_sent(item["outbox_id"], now)
            sent += 1
    return sent
