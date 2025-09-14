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

