# -*- coding: utf-8 -*-
"""
kiwoomDeepLearning 원격 분석 서버 HTTP 클라이언트
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import requests

from .deeplearning_server_config import load_deeplearning_server_config


class DeepLearningClient:
    def __init__(self, base_url: Optional[str] = None, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            cfg = load_deeplearning_server_config()
            self.base_url = cfg.base_url.rstrip("/")

    def health(self) -> Dict[str, Any]:
        url = f"{self.base_url}/health"
        r = requests.get(url, timeout=(5, 10))
        r.raise_for_status()
        return r.json()

    def run_analysis(self, analysis_date: Optional[str] = None) -> Dict[str, Any]:
        """
        실시간 분석 실행 (요청 시점에 분석 수행)
        - analysis_date 미지정 시 서버가 '오늘' 기준으로 실행
        """
        url = f"{self.base_url}/v1/analysis/run"
        payload: Dict[str, Any] = {}
        if analysis_date:
            payload["analysis_date"] = analysis_date

        # 분석 로직은 시간이 오래 걸릴 수 있으므로 read timeout을 크게 둔다.
        # connect timeout은 짧게 유지.
        r = requests.post(url, json=payload, timeout=(5, int(self.timeout_seconds)))
        r.raise_for_status()
        return r.json()


