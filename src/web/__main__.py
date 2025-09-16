#!/usr/bin/env python3
"""
키움 자동매매 웹 애플리케이션 메인 모듈
"""

if __name__ == '__main__':
    from .app import app, socketio
    
    print("=" * 50)
    print("키움 자동매매 시스템이 시작되었습니다.")
    print("브라우저에서 http://127.0.0.1:5001 으로 접속하세요.")
    print("자동매매 페이지: http://127.0.0.1:5001/auto-trading")
    print()
    print("서버를 중지하려면 Ctrl+C를 누르세요.")
    print("=" * 50)
    
    # Flask-SocketIO로 서버 시작
    socketio.run(app, host='127.0.0.1', port=5001, debug=False)
