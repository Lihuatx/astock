from __future__ import annotations

import html
import json
from pathlib import Path

from astock.observability.bundle import validate_review_bundle


def build_offline_report(bundle_path: Path, assets_dir: Path, target: Path) -> Path:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    validate_review_bundle(bundle)
    script = (assets_dir / "report.js").read_text(encoding="utf-8")
    css_files = list(assets_dir.glob("*.css"))
    if len(css_files) != 1:
        raise ValueError("offline report build must contain exactly one CSS file")
    css = css_files[0].read_text(encoding="utf-8")
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>astock 交易日复盘 {html.escape(bundle['trading_day'])}</title><style>{css}</style></head>
<body><div id="root"></div><script id="review-bundle" type="application/json">{payload}</script><script>{script}</script></body></html>"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    return target
