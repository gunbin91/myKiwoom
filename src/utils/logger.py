# -*- coding: utf-8 -*-
"""
로깅 유틸리티 모듈
"""
import sys
import os
import io
from pathlib import Path
from loguru import logger
from src.config import LOG_LEVEL, LOG_FILE

# 환경 변수 설정 (로깅 전에 설정)
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 로그 디렉토리 생성
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# 기본 로거 설정 제거
logger.remove()

# 콘솔 로거 설정
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    colorize=True
)

# 파일 로거 설정
logger.add(
    LOG_FILE,
    level=LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    rotation="1 day",
    retention="30 days",
    compression="zip"
)

# API 전용 로거
api_logger = logger.bind(module="API")
web_logger = logger.bind(module="WEB")
trading_logger = logger.bind(module="TRADING")

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

