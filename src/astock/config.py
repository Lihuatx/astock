from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


def load_env_file(path: Path) -> None:
    """加载本机配置，不覆盖进程中已经存在的环境变量。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    tdx_base_url: str
    ths_base_url: str
    ths_api_key: str | None
    data_dir: Path
    db_path: Path
    initial_cash: Decimal

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        if env_file:
            load_env_file(Path(env_file))
        data_dir = Path(os.getenv("ASTOCK_DATA_DIR", "./data")).resolve()
        db_path = Path(os.getenv("ASTOCK_DB_PATH", str(data_dir / "astock.db"))).resolve()
        return cls(
            tdx_base_url=os.getenv("TDX_BASE_URL", "http://127.0.0.1:17709/"),
            ths_base_url=os.getenv("THS_BASE_URL", "https://fuyao.aicubes.cn"),
            ths_api_key=os.getenv("THS_API_KEY") or None,
            data_dir=data_dir,
            db_path=db_path,
            initial_cash=Decimal(os.getenv("ASTOCK_INITIAL_CASH", "100000")),
        )

