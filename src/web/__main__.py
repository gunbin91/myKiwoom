#!/usr/bin/env python3
"""
키움 자동매매 웹 애플리케이션 메인 모듈
"""

if __name__ == '__main__':
    from .app import app, socketio
    from src.config.settings import WEB_HOST, WEB_PORT, WEB_DEBUG
    
    print("=" * 50)
    print("키움 자동매매 시스템이 시작되었습니다.")
    print("브라우저 접속 주소는 콘솔 로그에 출력되는 포트를 확인하세요.")
    print(f"기본 포트: {WEB_PORT} (사용 중이면 {WEB_PORT}~7999 범위에서 자동 선택)")
    print()
    print("서버를 중지하려면 Ctrl+C를 누르세요.")
    print("=" * 50)
    
    # Flask-SocketIO로 서버 시작
    socketio.run(app, host=WEB_HOST, port=WEB_PORT, debug=WEB_DEBUG)
