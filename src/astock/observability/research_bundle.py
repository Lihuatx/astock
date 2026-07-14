from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from astock.observability.bundle import canonical_json, sha256_bytes


SCHEMA_VERSION = 1


RESEARCH_SOURCES = (
    {
        "path": "docs/STRATEGY_RESEARCH_V3.md",
        "category": "STRATEGY",
        "title": "V3 多策略候选与稳健性复核",
        "summary": "使用双验证表现、相关性软约束、参数平坦度和成交置信度复核当前观察策略。",
        "conclusion": "当前候选仅用于前向执行链观察，没有策略达到双验证目标。",
        "status": "OBSERVE",
    },
    {
        "path": "docs/STRATEGY_RESEARCH_V6_INDUSTRY.md",
        "category": "INDUSTRY",
        "title": "申万一级行业中性与轮动研究",
        "summary": "按申万 2021 一级行业点时成分复核行业中性因子和行业轮动。",
        "conclusion": "行业轮动稳定性不足，暂不进入模拟盘候选。",
        "status": "REJECT",
    },
    {
        "path": "docs/INTRADAY_EXECUTION_REVIEW_RESULT.md",
        "category": "TOPIC",
        "title": "100 日 5 分钟成交质量专题",
        "summary": "使用 100 个交易日 5 分钟行情检查计划订单可成交率、滑点和证据覆盖。",
        "conclusion": "三个策略均未通过冻结阈值，结论保留为每日后验质量诊断。",
        "status": "OBSERVE",
    },
    {
        "path": "docs/P4_REAUDIT_2026-07-13.md",
        "category": "TOPIC",
        "title": "P4 独立复审证据",
        "summary": "复核不可变 Bundle、状态 Outbox、跨账户身份、鉴权、生命周期和备份恢复。",
        "conclusion": "原 P4 审计红灯已关闭，但不代表 P4 部署和前向运行验收完成。",
        "status": "PASS",
    },
)


def _source_commit(workspace: Path, source: Path) -> tuple[str, str]:
    relative = source.relative_to(workspace)
    try:
        output = subprocess.check_output(
            ["git", "log", "-1", "--format=%H%n%cI", "--", str(relative)],
            cwd=workspace,
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
        if len(output) >= 2:
            return output[0], output[1]
    except (OSError, subprocess.CalledProcessError):
        pass
    stamp = datetime.fromtimestamp(source.stat().st_mtime).astimezone().isoformat()
    return "UNCOMMITTED", stamp


def build_research_bundle(
    *,
    category: str,
    title: str,
    summary: str,
    conclusion: str,
    status: str,
    source_path: str,
    source_commit: str,
    data_cutoff: str,
    published_at: str,
    body_markdown: str,
) -> dict[str, Any]:
    facts = {
        "category": category,
        "title": title,
        "summary": summary,
        "conclusion": conclusion,
        "status": status,
        "source_path": source_path,
        "source_commit": source_commit,
        "data_cutoff": data_cutoff,
        "published_at": published_at,
        "body_markdown": body_markdown,
        "disclaimer": "A股模拟盘研究资料，不构成投资建议。",
    }
    content_hash = sha256_bytes(canonical_json(facts))
    slug = hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:10]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_id": f"research-{slug}-{content_hash[:16]}",
        "content_sha256": content_hash,
        **facts,
    }


def validate_research_bundle(bundle: dict[str, Any]) -> None:
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported research bundle schema")
    facts = {
        key: value
        for key, value in bundle.items()
        if key not in {"schema_version", "report_id", "content_sha256"}
    }
    actual = sha256_bytes(canonical_json(facts))
    if actual != bundle.get("content_sha256"):
        raise ValueError("research bundle content hash mismatch")
    slug = hashlib.sha256(str(bundle["source_path"]).encode("utf-8")).hexdigest()[:10]
    if bundle.get("report_id") != f"research-{slug}-{actual[:16]}":
        raise ValueError("research bundle id mismatch")


def write_research_bundle(bundle: dict[str, Any], root: Path) -> Path:
    validate_research_bundle(bundle)
    target = root / bundle["category"].lower() / f"{bundle['report_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(bundle)
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError("immutable research bundle already exists with different content")
        return target
    target.write_bytes(encoded)
    return target


def publish_research_bundles(workspace: Path, root: Path) -> list[tuple[dict[str, Any], Path]]:
    published = []
    for definition in RESEARCH_SOURCES:
        source = workspace / definition["path"]
        if not source.is_file():
            continue
        commit, published_at = _source_commit(workspace, source)
        body = source.read_text(encoding="utf-8")
        bundle = build_research_bundle(
            category=definition["category"],
            title=definition["title"],
            summary=definition["summary"],
            conclusion=definition["conclusion"],
            status=definition["status"],
            source_path=definition["path"],
            source_commit=commit,
            data_cutoff=published_at[:10],
            published_at=published_at,
            body_markdown=body,
        )
        published.append((bundle, write_research_bundle(bundle, root)))
    return published
