"""
키움 자동매매 프로그램 설정 파일
"""
import os
from pathlib import Path

# 프로젝트 루트 디렉토리
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 키움증권 API 설정 (모의투자 사용)
KIWOOM_APP_KEY = "V9mudQMHawpCK_sILj7nmasU9AZI_zr2sgsUFIxbyb4"
KIWOOM_SECRET_KEY = "erjXUeVqBNA5vZLjBjAfy3HkaAOcJEF3G9X37lGUgA0"
KIWOOM_DOMAIN = "https://mockapi.kiwoom.com"

# API 엔드포인트
KIWOOM_OAUTH_URL = f"{KIWOOM_DOMAIN}/oauth2/token"
KIWOOM_REVOKE_URL = f"{KIWOOM_DOMAIN}/oauth2/revoke"
KIWOOM_ACCOUNT_URL = f"{KIWOOM_DOMAIN}/api/dostk/acnt"
KIWOOM_QUOTE_URL = f"{KIWOOM_DOMAIN}/api/dostk/stkinfo"
KIWOOM_ORDER_URL = f"{KIWOOM_DOMAIN}/api/dostk/ordr"

# 주의: 신용주문 API는 사용하지 않음
# KIWOOM_CREDIT_ORDER_URL = f"{KIWOOM_DOMAIN}/api/dostk/crdordr"  # 신용주문 URL (사용 안함)
# 
# 신용주문을 사용하지 않는 이유:
# - 복잡성: 현금 주문보다 복잡한 구조
# - 위험성: 레버리지로 인한 손실 확대 가능
# - 비용: 이자 및 추가 수수료 부담
# - 규제: 신용거래 한도 및 제한사항

# 웹 애플리케이션 설정
WEB_HOST = "0.0.0.0"  # 모든 IP에서 접근 가능하도록 변경
WEB_PORT = 5001
WEB_DEBUG = True

# 로깅 설정
LOG_LEVEL = "INFO"
LOG_FILE = PROJECT_ROOT / "logs" / "kiwoom_auto_trading.log"

# 데이터 저장 경로
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / "cache"

# 토큰 관리
TOKEN_CACHE_FILE = CACHE_DIR / "access_token.json"
TOKEN_EXPIRE_BUFFER = 300  # 토큰 만료 5분 전 갱신

# API 요청 제한
API_REQUEST_DELAY = 2.0  # API 요청 간 최소 지연시간 (초) - 429 오류 방지
MAX_RETRY_COUNT = 3
API_CACHE_DURATION = 300  # API 응답 캐시 지속시간 (초) - 5분

# 웹소켓 설정 (실시간 데이터)
WEBSOCKET_URL = "wss://mockapi.kiwoom.com/ws"

# 데이터베이스 설정 (선택사항)
DATABASE_URL = f"sqlite:///{DATA_DIR}/kiwoom_trading.db"

# 보안 설정
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-here')
SESSION_TIMEOUT = 3600  # 세션 타임아웃 (초)

# 자동매매 설정
AUTO_TRADING_ENABLED = False
RISK_MANAGEMENT = {
    'max_position_size': 0.1,  # 최대 포지션 크기 (총 자산 대비)
    'stop_loss_ratio': 0.05,   # 손절매 비율
    'take_profit_ratio': 0.1,  # 익절매 비율
    'max_daily_loss': 0.02     # 일일 최대 손실 비율
}
