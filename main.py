#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
키움 자동매매 웹 대시보드 메인 실행 파일
"""

import sys
import os
import io
from pathlib import Path

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 필요한 디렉토리 생성
for directory in ['logs', 'cache', 'data']:
    (project_root / directory).mkdir(exist_ok=True)

if __name__ == '__main__':
    try:
        from src.web.app import app, socketio
        from src.config import WEB_HOST, WEB_PORT, WEB_DEBUG
        from src.utils import web_logger
        
        web_logger.info("키움 자동매매 웹 대시보드 시작")
        web_logger.info(f"서버 주소: http://{WEB_HOST}:{WEB_PORT}")
        
        # 웹 서버 시작
        socketio.run(app, host=WEB_HOST, port=WEB_PORT, debug=WEB_DEBUG)
        
    except KeyboardInterrupt:
        web_logger.info("사용자에 의해 서버가 중지되었습니다.")
    except Exception as e:
        web_logger.error(f"서버 시작 중 오류 발생: {e}")
        sys.exit(1)

