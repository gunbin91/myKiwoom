# -*- coding: utf-8 -*-
"""
서버별 동적 설정 관리 모듈
"""
import os
from pathlib import Path
from typing import Dict, Any

# 프로젝트 루트 디렉토리
PROJECT_ROOT = Path(__file__).parent.parent.parent

# config.py에서 서버별 설정 import
import sys
sys.path.append(str(PROJECT_ROOT))
from config import (
    KIWOOM_APP_KEY_MOCK, KIWOOM_SECRET_KEY_MOCK, KIWOOM_DOMAIN_MOCK,
    KIWOOM_APP_KEY_REAL, KIWOOM_SECRET_KEY_REAL, KIWOOM_DOMAIN_REAL,
    DART_API_KEY
)


class ServerConfig:
    """서버별 동적 설정 관리 클래스"""
    
    def __init__(self, server_type: str = 'mock'):
        """
        서버 설정 초기화
        
        Args:
            server_type: 'mock' 또는 'real'
        """
        self.server_type = server_type
        self._validate_server_type()
        self._load_config()
        self._setup_paths()
    
    def _validate_server_type(self):
        """서버 타입 검증"""
        if self.server_type not in ['mock', 'real']:
            raise ValueError(f"잘못된 서버 타입: {self.server_type}. 'mock' 또는 'real'만 허용됩니다.")
    
    def _load_config(self):
        """서버별 설정 로드"""
        if self.server_type == 'mock':
            self.app_key = KIWOOM_APP_KEY_MOCK
            self.secret_key = KIWOOM_SECRET_KEY_MOCK
            self.domain = KIWOOM_DOMAIN_MOCK
            self.server_name = "모의투자"
            self.server_color = "#4CAF50"  # 녹색
        else:  # real
            self.app_key = KIWOOM_APP_KEY_REAL
            self.secret_key = KIWOOM_SECRET_KEY_REAL
            self.domain = KIWOOM_DOMAIN_REAL
            self.server_name = "실전투자"
            self.server_color = "#F44336"  # 빨간색 (위험 표시)
        
        # 공통 설정
        self.dart_api_key = DART_API_KEY
        
        # API 엔드포인트 생성
        self.oauth_url = f"{self.domain}/oauth2/token"
        self.revoke_url = f"{self.domain}/oauth2/revoke"
        self.account_url = f"{self.domain}/api/dostk/acnt"
        self.quote_url = f"{self.domain}/api/dostk/stkinfo"
        self.order_url = f"{self.domain}/api/dostk/ordr"
        self.websocket_url = f"wss://{self.domain.replace('https://', '')}/ws"
    
    def _setup_paths(self):
        """서버별 파일 경로 설정"""
        # 기본 디렉토리
        self.cache_dir = PROJECT_ROOT / "cache"
        self.data_dir = PROJECT_ROOT / "data"
        self.logs_dir = PROJECT_ROOT / "logs"
        
        # 서버별 디렉토리
        self.server_cache_dir = self.cache_dir / self.server_type
        self.server_logs_dir = self.logs_dir / self.server_type
        
        # 서버별 파일 경로
        self.token_cache_file = self.cache_dir / f"access_token_{self.server_type}.json"
        self.config_file = self.data_dir / f"auto_trading_config_{self.server_type}.json"
        self.execution_log_file = self.server_logs_dir / "auto_trading_execution.log"
        self.main_log_file = self.server_logs_dir / "kiwoom_auto_trading.log"
        self.api_cache_dir = self.server_cache_dir / "api_responses"
        
        # 디렉토리 생성
        self._create_directories()
    
    def _create_directories(self):
        """필요한 디렉토리 생성"""
        directories = [
            self.cache_dir,
            self.data_dir,
            self.logs_dir,
            self.server_cache_dir,
            self.server_logs_dir,
            self.api_cache_dir
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_auth_config(self) -> Dict[str, Any]:
        """인증 관련 설정 반환"""
        return {
            'app_key': self.app_key,
            'secret_key': self.secret_key,
            'oauth_url': self.oauth_url,
            'revoke_url': self.revoke_url,
            'token_cache_file': self.token_cache_file
        }
    
    def get_api_config(self) -> Dict[str, Any]:
        """API 관련 설정 반환"""
        return {
            'account_url': self.account_url,
            'quote_url': self.quote_url,
            'order_url': self.order_url,
            'websocket_url': self.websocket_url,
            'api_cache_dir': self.api_cache_dir
        }
    
    def get_file_paths(self) -> Dict[str, Path]:
        """파일 경로 설정 반환"""
        return {
            'config_file': self.config_file,
            'execution_log_file': self.execution_log_file,
            'main_log_file': self.main_log_file,
            'token_cache_file': self.token_cache_file
        }
    
    def get_server_info(self) -> Dict[str, Any]:
        """서버 정보 반환"""
        return {
            'server_type': self.server_type,
            'server_name': self.server_name,
            'server_color': self.server_color,
            'domain': self.domain
        }
    
    def is_mock_server(self) -> bool:
        """모의투자 서버인지 확인"""
        return self.server_type == 'mock'
    
    def is_real_server(self) -> bool:
        """실전투자 서버인지 확인"""
        return self.server_type == 'real'


# 전역 설정 인스턴스 (기본값: 모의투자)
current_server_config = ServerConfig('mock')


def get_current_server_config() -> ServerConfig:
    """현재 서버 설정 반환"""
    return current_server_config


def set_server_type(server_type: str) -> ServerConfig:
    """서버 타입 변경"""
    global current_server_config
    current_server_config = ServerConfig(server_type)
    return current_server_config


def get_server_config(server_type: str) -> ServerConfig:
    """특정 서버 타입의 설정 반환"""
    return ServerConfig(server_type)
