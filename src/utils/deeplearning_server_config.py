# -*- coding: utf-8 -*-
"""
kiwoomDeepLearning 원격 분석 서버 설정 관리

- 저장 위치: myKiwoom/data/deeplearning_server.json
- 기본값: http://127.0.0.1:5000
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).parent.parent.parent  # myKiwoom/
CONFIG_FILE = PROJECT_ROOT / "data" / "deeplearning_server.json"


@dataclass
class DeepLearningServerConfig:
    scheme: str = "http"
    host: str = "127.0.0.1"
    port: int = 5000

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def _normalize(cfg: Dict[str, Any]) -> DeepLearningServerConfig:
    scheme = (cfg.get("scheme") or "http").strip()
    host = (cfg.get("host") or "127.0.0.1").strip()
    port = cfg.get("port", 5000)
    try:
        port = int(port)
    except Exception:
        port = 5000

    if scheme not in ("http", "https"):
        scheme = "http"
    if not host:
        host = "127.0.0.1"
    if not (1 <= port <= 65535):
        port = 5000

    return DeepLearningServerConfig(scheme=scheme, host=host, port=port)


def load_deeplearning_server_config() -> DeepLearningServerConfig:
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return _normalize(data)
    except Exception:
        # 설정 로드 실패 시 기본값 사용
        pass
    return DeepLearningServerConfig()


def save_deeplearning_server_config(cfg: Dict[str, Any]) -> DeepLearningServerConfig:
    normalized = _normalize(cfg if isinstance(cfg, dict) else {})
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(normalized), f, ensure_ascii=False, indent=2)
    return normalized


