from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from astock.dashboard.storage import DashboardStore


def create_backup(store: DashboardStore, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=False)
    store.backup(target / "server.db")
    bundle_target = target / "bundles"
    if store.bundle_root.exists():
        shutil.copytree(store.bundle_root, bundle_target)
    connection = sqlite3.connect(target / "server.db")
    try:
        rows = connection.execute("SELECT bundle_id FROM bundles").fetchall()
        for (bundle_id,) in rows:
            candidates = list(bundle_target.rglob(f"{bundle_id}.json"))
            if len(candidates) != 1:
                raise ValueError(f"backup bundle missing or duplicated: {bundle_id}")
            connection.execute("UPDATE bundles SET path=? WHERE bundle_id=?", (str(candidates[0]), bundle_id))
        connection.commit()
    finally:
        connection.close()
    _write_manifest(target)
    verify_backup(target)
    return target


def restore_backup(source: Path, target: Path) -> dict[str, int]:
    verify_backup(source)
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / "server.db", target / "server.db")
    shutil.copytree(source / "bundles", target / "bundles")
    connection = sqlite3.connect(target / "server.db")
    try:
        rows = connection.execute("SELECT bundle_id FROM bundles").fetchall()
        for (bundle_id,) in rows:
            candidates = list((target / "bundles").rglob(f"{bundle_id}.json"))
            if len(candidates) != 1:
                raise ValueError(f"restored bundle missing or duplicated: {bundle_id}")
            connection.execute("UPDATE bundles SET path=? WHERE bundle_id=?", (str(candidates[0]), bundle_id))
        connection.commit()
    finally:
        connection.close()
    _write_manifest(target)
    return verify_backup(target)


def verify_backup(target: Path) -> dict[str, int]:
    manifest_path = target / "manifest.sha256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, expected in manifest.items():
        path = target / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"backup hash mismatch: {relative}")
    connection = sqlite3.connect(target / "server.db")
    try:
        indexed = connection.execute("SELECT bundle_id,path,content_sha256 FROM bundles").fetchall()
    finally:
        connection.close()
    for bundle_id, restored_path, content_sha256 in indexed:
        candidates = list((target / "bundles").rglob(f"{bundle_id}.json"))
        if len(candidates) != 1:
            raise ValueError(f"backup bundle missing or duplicated: {bundle_id}")
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
        if payload.get("content_sha256") != content_sha256:
            raise ValueError(f"backup bundle index mismatch: {Path(restored_path).name}")
        if Path(restored_path).resolve() != candidates[0].resolve():
            raise ValueError(f"backup bundle path is not self-contained: {bundle_id}")
    return {"files": len(manifest), "bundles": len(indexed)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(root: Path) -> None:
    manifest = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(
            item for item in root.rglob("*") if item.is_file() and item.name != "manifest.sha256.json"
        )
    }
    (root / "manifest.sha256.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
