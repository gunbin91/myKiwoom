# -*- coding: utf-8 -*-
"""
서버 선택 상태 관리 모듈
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# 프로젝트 루트 디렉토리
PROJECT_ROOT = Path(__file__).parent.parent.parent
SERVER_SELECTION_FILE = PROJECT_ROOT / "data" / "server_selection.json"


def get_current_server() -> str:
    """현재 선택된 서버 반환"""
    try:
        if SERVER_SELECTION_FILE.exists():
            with open(SERVER_SELECTION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('current_server', 'mock')
        else:
            # 파일이 없으면 기본값으로 모의투자 설정
            set_current_server('mock')
            return 'mock'
    except Exception as e:
        print(f"서버 선택 상태 읽기 실패: {e}")
        return 'mock'


def set_current_server(server_type: str) -> bool:
    """현재 서버 설정"""
    try:
        if server_type not in ['mock', 'real']:
            print(f"잘못된 서버 타입: {server_type}")
            return False
        
        data = {
            'current_server': server_type,
            'last_updated': datetime.now().isoformat()
        }
        
        # 디렉토리가 없으면 생성
        SERVER_SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(SERVER_SELECTION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 서버 선택 시에만 로그 출력
        from src.utils import api_logger
        server_name = "모의투자" if server_type == "mock" else "실전투자"
        api_logger.info(f"서버 선택: {server_name} ({server_type})")
        print(f"서버 선택 상태 업데이트: {server_type}")
        return True
        
    except Exception as e:
        print(f"서버 선택 상태 저장 실패: {e}")
        return False


def get_server_info() -> Dict[str, Any]:
    """서버 정보 반환"""
    current_server = get_current_server()
    
    if current_server == 'real':
        return {
            'server_type': 'real',
            'server_name': '실전투자',
            'server_color': '#F44336',
            'domain': 'https://api.kiwoom.com'
        }
    else:
        return {
            'server_type': 'mock',
            'server_name': '모의투자',
            'server_color': '#4CAF50',
            'domain': 'https://mockapi.kiwoom.com'
        }
