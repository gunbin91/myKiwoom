"""
API 응답 캐싱 유틸리티
"""
import time
import json
import hashlib
from typing import Any, Optional, Dict
from pathlib import Path
from src.config.settings import CACHE_DIR, API_CACHE_DURATION


class APICache:
    """API 응답 캐시 관리 클래스"""
    
    def __init__(self):
        self.cache_dir = CACHE_DIR / "api_responses"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _generate_cache_key(self, api_id: str, params: Dict[str, Any]) -> str:
        """캐시 키 생성"""
        # API ID와 파라미터를 조합하여 고유한 키 생성
        key_data = f"{api_id}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, api_id: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """캐시에서 데이터 조회"""
        cache_key = self._generate_cache_key(api_id, params)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 캐시 만료 시간 확인
            if time.time() - cache_data['timestamp'] > API_CACHE_DURATION:
                cache_file.unlink()  # 만료된 캐시 파일 삭제
                return None
            
            return cache_data['data']
        
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            # 손상된 캐시 파일 삭제
            if cache_file.exists():
                cache_file.unlink()
            return None
    
    def set(self, api_id: str, params: Dict[str, Any], data: Dict[str, Any]) -> None:
        """캐시에 데이터 저장"""
        cache_key = self._generate_cache_key(api_id, params)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        cache_data = {
            'timestamp': time.time(),
            'api_id': api_id,
            'params': params,
            'data': data
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 캐시 저장 실패는 로그만 남기고 계속 진행
            print(f"캐시 저장 실패: {e}")
    
    def clear(self) -> None:
        """모든 캐시 삭제"""
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
    
    def clear_expired(self) -> None:
        """만료된 캐시만 삭제"""
        if not self.cache_dir.exists():
            return
        
        current_time = time.time()
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                if current_time - cache_data.get('timestamp', 0) > API_CACHE_DURATION:
                    cache_file.unlink()
            
            except (json.JSONDecodeError, KeyError):
                # 손상된 캐시 파일 삭제
                cache_file.unlink()


# 전역 캐시 인스턴스
api_cache = APICache()
