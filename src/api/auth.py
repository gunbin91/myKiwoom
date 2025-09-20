# -*- coding: utf-8 -*-
"""
키움증권 OAuth 인증 모듈
"""
import sys
import os
import io
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import requests

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'
from src.config.server_config import get_current_server_config
from src.config.settings import TOKEN_EXPIRE_BUFFER, API_REQUEST_DELAY
from src.utils import api_logger


class KiwoomAuth:
    """키움증권 OAuth 인증 관리 클래스"""
    
    def __init__(self, server_type: str = None):
        # 서버 타입 저장
        self.server_type = server_type
        
        # 서버 설정 로드
        if server_type:
            from src.config.server_config import get_server_config
            self.server_config = get_server_config(server_type)
        else:
            self.server_config = get_current_server_config()
        
        # 서버별 설정 적용
        auth_config = self.server_config.get_auth_config()
        self.app_key = auth_config['app_key']
        self.secret_key = auth_config['secret_key']
        self.oauth_url = auth_config['oauth_url']
        self.revoke_url = auth_config['revoke_url']
        self.token_cache_file = auth_config['token_cache_file']
        self.domain = self.server_config.domain  # 서버 도메인 설정 추가
        self._access_token = None
        self._token_expires_at = None
        
        # 캐시 디렉토리 생성
        self.token_cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 기존 토큰 로드
        self._load_cached_token()
    
    def _load_cached_token(self) -> None:
        """캐시된 토큰 로드"""
        try:
            if self.token_cache_file.exists():
                with open(self.token_cache_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)
                
                self._access_token = token_data.get('token')
                expires_dt_str = token_data.get('expires_dt')
                
                if expires_dt_str and self._access_token:
                    # YYYYMMDDHHMMSS 형식을 datetime으로 변환
                    expires_dt = datetime.strptime(expires_dt_str, '%Y%m%d%H%M%S')
                    self._token_expires_at = expires_dt
                    
                    # 토큰이 아직 유효한지 확인
                    if datetime.now() < expires_dt - timedelta(seconds=TOKEN_EXPIRE_BUFFER):
                        # 토큰 로드 로그 제거 - 너무 자주 출력됨
                        return
                    else:
                        api_logger.info(f"캐시된 토큰이 만료되었습니다. (서버: {self.server_type})")
                
                # 만료된 토큰 정리
                self._access_token = None
                self._token_expires_at = None
                
        except Exception as e:
            api_logger.error(f"토큰 캐시 로드 실패: {e}")
            self._access_token = None
            self._token_expires_at = None
    
    def _save_token_cache(self, token_data: Dict[str, Any]) -> None:
        """토큰을 캐시 파일에 저장"""
        try:
            with open(self.token_cache_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)
            api_logger.info(f"토큰이 캐시에 저장되었습니다. (서버: {self.server_config.server_type})")
        except Exception as e:
            api_logger.error(f"토큰 캐시 저장 실패: {e}")
    
    def get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        접근 토큰 발급 또는 반환
        
        Args:
            force_refresh: 강제 갱신 여부
            
        Returns:
            접근 토큰 문자열 또는 None
        """
        # 강제 갱신이 아니고 유효한 토큰이 있으면 반환
        if not force_refresh and self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at - timedelta(seconds=TOKEN_EXPIRE_BUFFER):
                return self._access_token
        
        # 새 토큰 발급
        return self._request_new_token()
    
    def _request_new_token(self) -> Optional[str]:
        """새로운 접근 토큰 발급 요청"""
        try:
            api_logger.info(f"새로운 접근 토큰을 발급받습니다. (서버: {self.server_type})")
            
            # 서버 상태 먼저 확인
            if not self._check_server_status():
                api_logger.error("키움 API 서버가 점검 중이거나 접근할 수 없습니다.")
                api_logger.error("키움증권 고객센터(1544-5000) 또는 홈페이지를 확인해주세요.")
                return None
            
            headers = {
                'Content-Type': 'application/json;charset=UTF-8'
            }
            
            data = {
                'grant_type': 'client_credentials',
                'appkey': self.app_key,
                'secretkey': self.secret_key
            }
            
            response = requests.post(
                self.oauth_url,
                headers=headers,
                json=data,
                timeout=30
            )
            
            response.raise_for_status()
            
            # 응답 내용 디버깅
            response_text = response.text
            api_logger.info(f"토큰 발급 응답 상태코드: {response.status_code}")
            api_logger.info(f"토큰 발급 응답 내용: {response_text}")
            
            # 빈 응답 체크
            if not response_text.strip():
                api_logger.error("토큰 발급 응답이 비어있습니다.")
                return None
            
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                api_logger.error(f"토큰 발급 응답 JSON 파싱 실패: {e}")
                api_logger.error(f"응답 내용: {response_text}")
                return None
            
            if result.get('return_code') == 0:
                token = result.get('token')
                expires_dt_str = result.get('expires_dt')
                
                if token and expires_dt_str:
                    # 토큰 정보 저장
                    self._access_token = token
                    self._token_expires_at = datetime.strptime(expires_dt_str, '%Y%m%d%H%M%S')
                    
                    # 캐시에 저장
                    self._save_token_cache({
                        'token': token,
                        'expires_dt': expires_dt_str,
                        'issued_at': datetime.now().strftime('%Y%m%d%H%M%S')
                    })
                    
                    api_logger.info("접근 토큰 발급 성공")
                    return token
                else:
                    api_logger.error("토큰 응답 데이터가 올바르지 않습니다.")
                    return None
            else:
                api_logger.error(f"토큰 발급 실패: {result.get('return_msg', '알 수 없는 오류')}")
                return None
                
        except requests.exceptions.RequestException as e:
            api_logger.error(f"토큰 발급 요청 실패: {e}")
            return None
        except Exception as e:
            api_logger.error(f"토큰 발급 중 오류 발생: {e}")
            return None
    
    def _check_server_status(self) -> bool:
        """키움 API 서버 상태 확인"""
        try:
            response = requests.get(f"{self.domain}/start.html", timeout=10)
            if response.status_code == 200:
                api_logger.info("키움 API 서버 정상")
                return True
            else:
                api_logger.warning(f"키움 API 서버 상태 이상: {response.status_code}")
                return False
        except Exception as e:
            api_logger.error(f"키움 API 서버 연결 실패: {e}")
            return False
    
    def revoke_token(self) -> bool:
        """
        접근 토큰 폐기
        
        Returns:
            폐기 성공 여부
        """
        if not self._access_token:
            api_logger.warning("폐기할 토큰이 없습니다.")
            return True
        
        try:
            api_logger.info("접근 토큰을 폐기합니다.")
            
            headers = {
                'Content-Type': 'application/json;charset=UTF-8'
            }
            
            data = {
                'appkey': self.app_key,
                'secretkey': self.secret_key,
                'token': self._access_token
            }
            
            response = requests.post(
                self.revoke_url,
                headers=headers,
                json=data,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('return_code') == 0:
                api_logger.info("토큰 폐기 성공")
                
                # 로컬 토큰 정보 정리
                self._access_token = None
                self._token_expires_at = None
                
                # 캐시 파일 삭제
                if self.token_cache_file.exists():
                    self.token_cache_file.unlink()
                
                return True
            else:
                api_logger.error(f"토큰 폐기 실패: {result.get('return_msg', '알 수 없는 오류')}")
                return False
                
        except requests.exceptions.RequestException as e:
            api_logger.error(f"토큰 폐기 요청 실패: {e}")
            return False
        except Exception as e:
            api_logger.error(f"토큰 폐기 중 오류 발생: {e}")
            return False
    
    def get_auth_headers(self) -> Dict[str, str]:
        """
        API 호출용 인증 헤더 반환
        
        Returns:
            인증 헤더 딕셔너리
        """
        token = self.get_access_token()
        if not token:
            raise Exception("유효한 접근 토큰을 가져올 수 없습니다.")
        
        return {
            'Content-Type': 'application/json;charset=UTF-8',
            'authorization': f'Bearer {token}'
        }
    
    def is_token_valid(self) -> bool:
        """토큰 유효성 확인"""
        if not self._access_token or not self._token_expires_at:
            return False
        
        return datetime.now() < self._token_expires_at - timedelta(seconds=TOKEN_EXPIRE_BUFFER)
    
    def is_authenticated(self) -> bool:
        """인증 상태 확인"""
        return self.is_token_valid()
    
    def get_token_info(self) -> Optional[Dict[str, Any]]:
        """토큰 정보 반환"""
        if not self.is_authenticated():
            return None
        
        return {
            'expires_at': self._token_expires_at.isoformat() if self._token_expires_at else None,
            'expires_in_seconds': int((self._token_expires_at - datetime.now()).total_seconds()) if self._token_expires_at else 0
        }


# 전역 인증 인스턴스들 (서버별)
mock_auth = KiwoomAuth('mock')
real_auth = KiwoomAuth('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
kiwoom_auth = mock_auth

