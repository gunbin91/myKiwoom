# -*- coding: utf-8 -*-
"""
로깅 유틸리티 모듈 (서버별 분리)
"""
import sys
import os
import io
from pathlib import Path
from loguru import logger
from src.config import LOG_LEVEL, LOG_FILE
from src.utils.server_manager import get_current_server

# 환경 변수 설정 (로깅 전에 설정)
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 프로젝트 루트 디렉토리
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 기본 로거 설정 제거
logger.remove()

# 콘솔 로거 설정
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    colorize=True
)

# 기존 통합 로그 파일 설정 (하위 호환성)
logger.add(
    LOG_FILE,
    level=LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="1 day",
    retention="30 days",
    compression="zip"
)

# 로거 핸들러 캐시 (중복 방지)
_logger_handlers = {}

def get_server_logger(server_type: str = None, log_type: str = "system"):
    """
    서버별 로거 생성 (중복 핸들러 방지)
    
    Args:
        server_type: 'mock' 또는 'real' (None이면 현재 서버 사용)
        log_type: 'system' 또는 'auto_trading'
    
    Returns:
        loguru logger 인스턴스
    """
    if server_type is None:
        server_type = get_current_server()
    
    # 캐시 키 생성
    cache_key = f"{server_type}_{log_type}"
    
    # 이미 생성된 핸들러가 있으면 재사용
    if cache_key in _logger_handlers:
        return logger.bind(server=server_type, log_type=log_type)
    
    # 서버별 로그 디렉토리
    server_logs_dir = PROJECT_ROOT / "logs" / server_type
    server_logs_dir.mkdir(parents=True, exist_ok=True)
    
    # 로그 파일 경로
    if log_type == "system":
        log_file = server_logs_dir / "system.log"
    elif log_type == "auto_trading":
        # Windows 멀티프로세싱에서 동일 파일 로테이션(rename) 충돌(WinError 32)을 피하기 위해
        # 프로세스별 로그 파일로 분리한다.
        if os.name == "nt":
            pid = os.getpid()
            log_file = server_logs_dir / f"auto_trading_{pid}.log"
        else:
            log_file = server_logs_dir / "auto_trading.log"
    else:
        raise ValueError(f"잘못된 로그 타입: {log_type}")
    
    # 파일 로거 추가 (한 번만)
    logger.add(
        log_file,
        level=LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="1 day",
        retention="30 days",
        compression="zip",
        filter=lambda record: record["extra"].get("server") == server_type and record["extra"].get("log_type") == log_type
    )
    
    # 캐시에 추가
    _logger_handlers[cache_key] = True
    
    return logger.bind(server=server_type, log_type=log_type)

# 기본 로거들 (현재 서버 기준 - 동적 생성)
def get_current_system_logger():
    """현재 서버의 시스템 로거 반환 (동적 생성)"""
    return get_server_logger(log_type="system")

def get_current_auto_trading_logger():
    """현재 서버의 자동매매 로거 반환 (동적 생성)"""
    return get_server_logger(log_type="auto_trading")

# 동적 로거 팩토리 함수들
def get_api_logger():
    """API 로거 반환 (현재 서버 기준)"""
    return get_current_system_logger().bind(module="API")

def get_web_logger():
    """웹 로거 반환 (현재 서버 기준)"""
    return get_current_system_logger().bind(module="WEB")

def get_trading_logger():
    """트레이딩 로거 반환 (현재 서버 기준)"""
    return get_current_auto_trading_logger().bind(module="TRADING")

# 기존 호환성을 위한 로거들 (정적 - 하위 호환성)
api_logger = get_api_logger()
web_logger = get_web_logger()
trading_logger = get_trading_logger()

def log_error_with_context(logger_instance, error_msg: str, error: Exception, 
                          context: dict = None, include_traceback: bool = True):
    """
    에러 로깅을 위한 공통 유틸리티 함수
    
    Args:
        logger_instance: 로거 인스턴스 (api_logger, web_logger, trading_logger)
        error_msg: 에러 메시지
        error: Exception 객체
        context: 추가 컨텍스트 정보 (dict)
        include_traceback: 스택 트레이스 포함 여부
    """
    logger_instance.error(f"🚨 {error_msg}: {error}")
    
    # 컨텍스트 정보 로깅
    if context:
        for key, value in context.items():
            logger_instance.error(f"   📍 {key}: {value}")
    
    # 스택 트레이스 로깅
    if include_traceback:
        import traceback
        logger_instance.error(f"   📍 스택 트레이스: {traceback.format_exc()}")

def log_api_error(logger_instance, api_id: str, error: Exception, 
                 url: str = None, data: dict = None):
    """
    API 에러 로깅을 위한 전용 함수
    
    Args:
        logger_instance: 로거 인스턴스
        api_id: API ID
        error: Exception 객체
        url: 요청 URL
        data: 요청 데이터
    """
    context = {}
    if url:
        context['요청 URL'] = url
    if data:
        context['요청 데이터'] = data
    
    log_error_with_context(
        logger_instance, 
        f"API {api_id} 처리 중 오류", 
        error, 
        context
    )

