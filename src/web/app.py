# -*- coding: utf-8 -*-
"""
키움 자동매매 웹 대시보드 메인 애플리케이션
"""
import sys
import os
import io
import socket

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'

from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import json
from datetime import datetime, timedelta
import time
from flask import g
import math
from src.config.settings import WEB_HOST, WEB_PORT, WEB_DEBUG, SECRET_KEY, SESSION_TIMEOUT
from src.config.server_config import set_server_type, get_current_server_config
from src.utils import get_web_logger
# 캐시 모듈 제거됨
from src.utils.deeplearning_server_config import load_deeplearning_server_config, save_deeplearning_server_config

def safe_float(value, default=0.0):
    """안전한 float 변환 함수"""
    if value is None or value == '' or value == 'None':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _pick_available_port(host: str, start_port: int = 7000, end_port: int = 7999) -> int:
    """
    start_port ~ end_port 범위에서 사용 가능한 포트를 찾아 반환.
    - host가 0.0.0.0 인 경우에도 로컬 체크는 127.0.0.1로 수행 (윈도우에서 바인딩 체크 안정화)
    """
    bind_host = host
    if host in ("0.0.0.0", "::", "", None):
        bind_host = "127.0.0.1"

    for port in range(int(start_port), int(end_port) + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((bind_host, port))
            return port
        except OSError:
            continue

    raise RuntimeError(f"사용 가능한 포트를 찾을 수 없습니다. ({start_port}~{end_port})")


def _sanitize_json_value(obj):
    """
    JSON 직렬화 안전화:
    - NaN/Inf -> None (JSON의 null)
    - dict/list/tuple 재귀 처리
    기존 로직/데이터 구조는 유지하고 "응답 직전"에만 적용한다.
    """
    try:
        if obj is None:
            return None
        if isinstance(obj, float):
            return obj if math.isfinite(obj) else None
        if isinstance(obj, dict):
            return {k: _sanitize_json_value(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize_json_value(v) for v in obj]
        if isinstance(obj, tuple):
            return [_sanitize_json_value(v) for v in obj]

        # numpy float 등(있을 경우) 처리
        try:
            import numpy as np  # type: ignore
            if isinstance(obj, (np.floating,)):
                fv = float(obj)
                return fv if math.isfinite(fv) else None
        except Exception:
            pass

        return obj
    except Exception:
        # 안전하게 실패 시 원본 반환
        return obj
from src.api import kiwoom_auth, kiwoom_account, kiwoom_quote, kiwoom_order, kiwoom_chart, mock_account, real_account, mock_quote, real_quote, mock_order, real_order, mock_chart, real_chart
from src.auto_trading.config_manager import mock_config_manager, real_config_manager
from src.auto_trading.engine import mock_engine, real_engine
from src.auto_trading.scheduler import mock_scheduler, real_scheduler
import threading
import time

# Flask 애플리케이션 초기화
app = Flask(__name__, 
           template_folder='../../templates',
           static_folder='../../static')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=SESSION_TIMEOUT)

# UTF-8 인코딩 설정
app.config['JSON_AS_ASCII'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

# Flask 로깅 레벨 설정 (개발 중에는 INFO 레벨로 설정하여 디버깅 가능)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.INFO)  # 개발 중에는 INFO 레벨로 변경

# Flask 애플리케이션 로깅 레벨도 조정
app.logger.setLevel(logging.INFO)  # 개발 중에는 INFO 레벨로 변경

# 자동매매 상태 조회 요청 로그 필터링
class AutoTradingStatusLogFilter(logging.Filter):
    def filter(self, record):
        # 자동매매 상태 조회 요청은 로그에서 제외
        if hasattr(record, 'getMessage'):
            message = record.getMessage()
            if '/api/auto-trading/status' in message:
                return False
        return True

# 로그 필터 적용
log.addFilter(AutoTradingStatusLogFilter())

# 서버 선택 상태 관리
from src.utils.server_manager import get_current_server, set_current_server, get_server_info

# -------------------------------------------------------------------
# 요청 단위 server_type 해석 (동시 mock/real 백프로세스 고려)
# - 우선순위: request(server_type) > session(server_type) > 전역 선택(get_current_server)
# -------------------------------------------------------------------
def _normalize_server_type(server_type):
    return server_type if server_type in ['mock', 'real'] else None

def get_request_server_type():
    """현재 요청이 대상으로 하는 서버 타입 반환"""
    # 1) querystring 우선
    server_type = _normalize_server_type(request.args.get('server_type'))

    # 2) JSON body (POST 등)
    if not server_type and request.is_json:
        try:
            data = request.get_json(silent=True) or {}
            server_type = _normalize_server_type(data.get('server_type'))
        except Exception:
            server_type = None

    # 3) 세션
    if not server_type:
        server_type = _normalize_server_type(session.get('server_type'))

    # 4) 전역 선택(파일 기반)
    if not server_type:
        server_type = _normalize_server_type(get_current_server())

    return server_type or 'mock'

def clear_auth_session():
    """인증 관련 세션만 정리 (서버 선택 정보는 유지)"""
    session.pop('authenticated', None)
    session.pop('login_time', None)

def get_config_manager_for(server_type: str):
    return mock_config_manager if server_type == 'mock' else real_config_manager

def get_engine_for(server_type: str):
    return mock_engine if server_type == 'mock' else real_engine

def get_scheduler_for(server_type: str):
    return mock_scheduler if server_type == 'mock' else real_scheduler

# 현재 서버에 맞는 config_manager와 engine 가져오기
def get_current_config_manager():
    """현재 서버에 맞는 config_manager 반환"""
    server_type = get_current_server()
    return mock_config_manager if server_type == 'mock' else real_config_manager

def get_current_server_config_instance():
    """현재 서버에 맞는 ServerConfig 인스턴스 반환"""
    server_type = get_current_server()
    from src.config.server_config import ServerConfig
    return ServerConfig(server_type)

def get_current_engine():
    """현재 서버에 맞는 engine 반환"""
    server_type = get_current_server()
    return mock_engine if server_type == 'mock' else real_engine

def get_current_account():
    """현재 서버에 맞는 account 반환"""
    from src.api.account import KiwoomAccount
    server_type = get_current_server()
    return KiwoomAccount(server_type)

def get_current_quote():
    """현재 서버에 맞는 quote 반환"""
    from src.api.quote import KiwoomQuote
    server_type = get_current_server()
    return KiwoomQuote(server_type)

def get_current_order():
    """현재 서버에 맞는 order 반환"""
    from src.api.order import KiwoomOrder
    server_type = get_current_server()
    return KiwoomOrder(server_type)

def get_current_chart():
    """현재 서버에 맞는 chart 반환"""
    from src.api.chart import KiwoomChart
    server_type = get_current_server()
    return KiwoomChart(server_type)

# CORS 및 SocketIO 설정
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# 전역 변수
is_connected = False
real_time_data = {}

def get_user_friendly_message(error_code, error_message, context=""):
    """
    API 오류 코드를 사용자 친화적인 메시지로 변환
    """
    # 키움 API 오류 코드별 사용자 친화적 메시지
    error_messages = {
        # 인증 관련
        "RC4010": "모의투자 영업일이 아닙니다. 실제 거래일(평일 09:00-15:30)에만 주문이 가능합니다.",
        "RC4011": "실시간 시세 서비스가 일시 중단되었습니다. 잠시 후 다시 시도해주세요.",
        "RC4012": "API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
        
        # 주문 관련
        "1501": "잘못된 주문 정보입니다. 종목코드, 수량, 가격을 확인해주세요.",
        "1502": "주문 수량이 잘못되었습니다. 1주 이상의 수량을 입력해주세요.",
        "1503": "주문 가격이 잘못되었습니다. 올바른 가격을 입력해주세요.",
        "1504": "지원하지 않는 API입니다. 시스템 관리자에게 문의해주세요.",
        "1505": "주문 가능 시간이 아닙니다. 거래시간(09:00-15:30)에만 주문이 가능합니다.",
        "1506": "잔고가 부족합니다. 보유 주식 수량을 확인해주세요.",
        "1507": "현금이 부족합니다. 계좌 잔고를 확인해주세요.",
        "1508": "주문이 거부되었습니다. 주문 정보를 다시 확인해주세요.",
        
        # 계좌 관련
        "1511": "필수 입력 값이 누락되었습니다. 모든 필수 항목을 입력해주세요.",
        "1512": "잘못된 계좌번호입니다. 계좌번호를 확인해주세요.",
        "1513": "계좌 정보를 가져올 수 없습니다. 잠시 후 다시 시도해주세요.",
        
        # 종목 관련
        "1521": "존재하지 않는 종목코드입니다. 종목코드를 확인해주세요.",
        "1522": "종목 정보를 가져올 수 없습니다. 잠시 후 다시 시도해주세요.",
        "1523": "거래정지된 종목입니다. 다른 종목을 선택해주세요.",
        
        # 시스템 관련
        "2000": "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        "2001": "네트워크 연결에 문제가 있습니다. 인터넷 연결을 확인해주세요.",
        "2002": "서버가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
    }
    
    # 오류 코드 추출 (RC4010, 1501 등)
    if isinstance(error_code, str):
        code = error_code
    else:
        code = str(error_code)
    
    # 사용자 친화적 메시지 반환
    if code in error_messages:
        return error_messages[code]
    elif error_message:
        # 기본 메시지가 있으면 사용
        return f"{error_message}"
    else:
        # 기본 오류 메시지
        return f"오류가 발생했습니다. (코드: {code})"

def create_error_response(error_code, error_message, context=""):
    """
    오류 응답 생성
    """
    user_message = get_user_friendly_message(error_code, error_message, context)
    return {
        'success': False,
        'message': user_message,
        'error_code': error_code,
        'context': context
    }


@app.before_request
def before_request():
    """요청 전 처리"""
    session.permanent = True
    g._req_start_ts = time.time()

    # API 요청 접수 로그 (너무 자주 호출되는 엔드포인트는 제외)
    try:
        path = request.path or ""
        if path.startswith("/api/"):
            if path in ("/api/auto-trading/status",):
                return
            server_type = None
            try:
                server_type = get_request_server_type()
            except Exception:
                server_type = None
            qs = request.query_string.decode("utf-8", errors="replace") if request.query_string else ""
            get_web_logger().info(
                f"[API] {request.method} {path}"
                + (f"?{qs}" if qs else "")
                + f" from={request.remote_addr} server_type={server_type}"
            )
    except Exception:
        # 로깅 실패는 요청 처리를 막지 않음
        pass


@app.after_request
def after_request(response):
    """요청 후 처리(응답/처리시간 로깅)"""
    try:
        path = request.path or ""
        if path.startswith("/api/"):
            if path in ("/api/auto-trading/status",):
                return response
            elapsed_ms = None
            if hasattr(g, "_req_start_ts"):
                elapsed_ms = int((time.time() - g._req_start_ts) * 1000)
            get_web_logger().info(
                f"[API] {request.method} {path} -> {response.status_code}"
                + (f" {elapsed_ms}ms" if elapsed_ms is not None else "")
            )
    except Exception:
        pass
    return response


@app.route('/')
def index():
    """메인 대시보드 페이지"""
    # 현재 서버 설정 로드
    server_info = get_server_info()
    return render_template('dashboard.html', server_info=server_info)


@app.route('/api-test')
def api_test():
    """API 테스트 페이지"""
    return render_template('api_test.html')


@app.route('/server-selection')
def server_selection():
    """서버 선택 페이지"""
    return render_template('server_selection.html')


@app.route('/api/server/select', methods=['POST'])
def select_server():
    """서버 선택"""
    try:
        data = request.get_json()
        server_type = data.get('server_type')
        
        if server_type not in ['mock', 'real']:
            return jsonify({
                'success': False,
                'message': '잘못된 서버 타입입니다.'
            }), 400
        
        # 기존 서버의 토큰 폐기 (이전 서버 타입이 있는 경우)
        old_server_type = session.get('server_type')
        if old_server_type and old_server_type != server_type:
            try:
                from src.api.auth import KiwoomAuth
                old_auth = KiwoomAuth(old_server_type)
                old_auth.revoke_token()
                get_web_logger().info(f"이전 서버({old_server_type})의 토큰을 폐기했습니다.")
            except Exception as e:
                get_web_logger().warning(f"이전 서버 토큰 폐기 실패: {e}")
        
        # 서버 타입 설정 (전역 설정 파일에 저장)
        set_current_server(server_type)
        
        # 세션에 서버 타입 정보 저장 (호환성을 위해)
        session['server_type'] = server_type
        
        get_web_logger().info(f"서버 선택 완료: {server_type}")
        get_web_logger().info(f"세션에 저장된 server_type: {session.get('server_type')}")
        
        return jsonify({
            'success': True,
            'message': f'{server_type} 서버가 선택되었습니다.',
            'server_type': server_type
        })
        
    except Exception as e:
        get_web_logger().error(f"🚨 서버 선택 실패: {e}")
        get_web_logger().error(f"   📍 요청 데이터: {request.get_json()}")
        import traceback
        get_web_logger().error(f"   📍 스택 트레이스: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'서버 선택 실패: {str(e)}'
        }), 500


@app.route('/api/server/status')
def get_server_status():
    """현재 서버 상태 조회"""
    try:
        server_type = get_current_server()
        server_info = get_server_info()
        
        return jsonify({
            'success': True,
            'server_type': server_type,
            'server_info': server_info
        })
    except Exception as e:
        get_web_logger().error(f"🚨 서버 상태 조회 실패: {e}")
        import traceback
        get_web_logger().error(f"   📍 스택 트레이스: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'서버 상태 조회 실패: {str(e)}'
        }), 500


@app.route('/api/deeplearning/config', methods=['GET'])
def get_deeplearning_config():
    """원격 분석 서버(kiwoomDeepLearning) 설정 조회"""
    cfg = load_deeplearning_server_config()
    return jsonify({
        'success': True,
        'data': {
            'scheme': cfg.scheme,
            'host': cfg.host,
            'port': cfg.port,
            'base_url': cfg.base_url
        }
    })


@app.route('/api/deeplearning/config', methods=['POST'])
def set_deeplearning_config():
    """원격 분석 서버(kiwoomDeepLearning) 설정 저장"""
    data = request.get_json() or {}
    cfg = save_deeplearning_server_config(data)
    return jsonify({
        'success': True,
        'message': '분석 서버 설정이 저장되었습니다.',
        'data': {
            'scheme': cfg.scheme,
            'host': cfg.host,
            'port': cfg.port,
            'base_url': cfg.base_url
        }
    })


@app.route('/api/deeplearning/health', methods=['GET'])
def deeplearning_health():
    """원격 분석 서버 연결 테스트"""
    try:
        from src.utils.deeplearning_client import DeepLearningClient
        cfg = load_deeplearning_server_config()
        client = DeepLearningClient(base_url=cfg.base_url)
        result = client.health()
        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'분석 서버 연결 실패: {str(e)}'
        }), 502


@app.route('/portfolio')
def portfolio():
    """포트폴리오 페이지"""
    server_info = get_server_info()
    return render_template('portfolio.html', server_info=server_info)


@app.route('/orders')
def orders():
    """주문내역 페이지"""
    server_info = get_server_info()
    return render_template('orders.html', server_info=server_info)


@app.route('/trading-diary')
def trading_diary():
    """매매일지 페이지"""
    server_info = get_server_info()
    return render_template('trading_diary.html', server_info=server_info)


@app.route('/auto-trading')
def auto_trading():
    """자동매매 페이지"""
    server_info = get_server_info()
    return render_template('auto_trading.html', server_info=server_info)




@app.route('/api/auth/login', methods=['POST'])
def login():
    """OAuth 인증 로그인"""
    try:
        # 현재 서버 타입에 맞는 인증 인스턴스 사용
        server_type = get_request_server_type()
        get_web_logger().info(f"로그인 시도 - 현재 서버: {server_type}")
        
        from src.api.auth import KiwoomAuth
        current_auth = KiwoomAuth(server_type)
        get_web_logger().info(f"로그인 시도 - {server_type} 서버용 인증 인스턴스 생성")
        token = current_auth.get_access_token(force_refresh=True)
        if token:
            # 토큰 발급 성공 후 체결내역 수집 시작
            get_web_logger().info("🔍 매수 체결내역 수집 시작")
            
            try:
                from src.utils.order_history_manager import OrderHistoryManager
                order_manager = OrderHistoryManager(server_type)
                
                # 체결내역 수집 (최대 30일)
                get_web_logger().info(f"🔍 {server_type} 서버 매수 체결내역 수집 시작")
                get_web_logger().info(f"🔍 보유기간 계산을 위한 체결일자 수집을 시작합니다...")
                
                collection_success = order_manager.collect_order_history(max_days=30)
                
                if collection_success:
                    # 수집된 데이터 요약 정보 로그
                    summary = order_manager.get_data_summary()
                    get_web_logger().info(f"✅ 매수 체결내역 수집 완료: {summary['total_orders']}개 주문, {summary['stock_count']}개 종목")
                    get_web_logger().info(f"✅ 보유기간 계산을 위한 체결일자 수집이 완료되었습니다.")
                else:
                    get_web_logger().warning("⚠️ 매수 체결내역 수집 실패 (로그인은 계속 진행)")
                    get_web_logger().warning("⚠️ 보유기간 계산을 위한 체결일자 수집에 실패했습니다.")
                
            except Exception as collection_error:
                get_web_logger().error(f"🚨 체결내역 수집 중 오류: {collection_error}")
                get_web_logger().error(f"🚨 보유기간 계산을 위한 체결일자 수집 중 오류가 발생했습니다.")
                import traceback
                get_web_logger().error(f"   📍 스택 트레이스: {traceback.format_exc()}")
                # 수집 실패해도 로그인은 계속 진행
            
            # 로그인 완료
            session['authenticated'] = True
            session['server_type'] = server_type
            session['login_time'] = datetime.now().isoformat()
            get_web_logger().info("사용자 로그인 성공")
            return jsonify({
                'success': True,
                'message': '로그인 성공'
            })
        else:
            return jsonify({
                'success': False,
                'message': '토큰 발급 실패'
            })
    except Exception as e:
        get_web_logger().error(f"🚨 로그인 실패: {e}")
        get_web_logger().error(f"   📍 요청 데이터: {request.get_json()}")
        import traceback
        get_web_logger().error(f"   📍 스택 트레이스: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'로그인 실패: {str(e)}'
        })


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """로그아웃"""
    try:
        # 현재 세션의 서버 타입에 맞는 인증 인스턴스 사용
        server_type = session.get('server_type')
        if server_type:
            from src.api.auth import KiwoomAuth
            current_auth = KiwoomAuth(server_type)
            revoke_result = current_auth.revoke_token()
            get_web_logger().info(f"토큰 폐기 결과: {revoke_result}")
        
        # 세션 정리
        session.clear()
        get_web_logger().info("사용자 로그아웃 완료")
        return jsonify({
            'success': True,
            'message': '로그아웃 성공'
        })
    except Exception as e:
        get_web_logger().error(f"로그아웃 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'로그아웃 실패: {str(e)}'
        })


def check_auth():
    """인증 상태 체크 데코레이터"""
    session_authenticated = session.get('authenticated', False)
    server_type = get_request_server_type()
    
    # 현재 서버 타입에 맞는 인증 인스턴스 사용
    from src.api.auth import KiwoomAuth
    current_auth = KiwoomAuth(server_type)
    token_valid = current_auth.is_token_valid()
    
    if not (session_authenticated and token_valid):
        return False, jsonify({
            'success': False,
            'message': '인증이 필요합니다. 로그인해주세요.',
            'authenticated': False
        })
    
    return True, None


@app.route('/api/account/deposit')
def get_deposit():
    """예수금 상세 현황 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        # kt00001로 예수금 정보 조회
        result = get_current_account().get_deposit_detail()
        if result and result.get('success') is not False:
            # 서버별 분기처리
            server_config = get_current_server_config_instance()
            
            if server_config.is_real_server():
                # 운영서버: kt00002로 최신 예수금 정보 확인
                from datetime import datetime
                today = datetime.now().strftime('%Y%m%d')
                
                try:
                    daily_result = get_current_account().get_daily_estimated_deposit_assets(today, today)
                    if daily_result and daily_result.get('daly_prsm_dpst_aset_amt_prst'):
                        # 오늘 날짜의 예수금 정보가 있으면 사용
                        today_data = daily_result['daly_prsm_dpst_aset_amt_prst'][0]
                        if 'entr' in today_data:
                            result['entr'] = today_data['entr']
                            get_web_logger().info(f"운영서버 kt00002에서 최신 예수금 정보 사용: {today_data['entr']}")
                except Exception as e:
                    get_web_logger().warning(f"운영서버 kt00002 조회 실패, kt00001 결과 사용: {e}")
                    get_web_logger().info("🔄 kt00002 실패로 인해 kt00001 예수금 정보로 대체 호출합니다")
            
            # 주문가능금액을 우선적으로 사용 (100stk_ord_alow_amt)
            if '100stk_ord_alow_amt' in result and result['100stk_ord_alow_amt'] and result['100stk_ord_alow_amt'] != '000000000000000':
                original_entr = result.get('entr', '0')
                result['entr'] = result['100stk_ord_alow_amt']
                result['entr_type'] = '주문가능금액'
                get_web_logger().info(f"✅ 주문가능금액 사용: {result['100stk_ord_alow_amt']} (기본 예수금: {original_entr})")
            # D+2 추정예수금 사용 (주문가능금액이 없는 경우)
            elif 'd2_entra' in result and result['d2_entra'] and result['d2_entra'] != '000000000000000':
                original_entr = result.get('entr', '0')
                result['entr'] = result['d2_entra']
                result['entr_type'] = 'D+2'
                get_web_logger().info(f"✅ D+2 추정예수금 사용: {result['d2_entra']} (기본 예수금: {original_entr})")
            # D+1 추정예수금 사용 (D+2가 없는 경우)
            elif 'd1_entra' in result and result['d1_entra'] and result['d1_entra'] != '000000000000000':
                original_entr = result.get('entr', '0')
                result['entr'] = result['d1_entra']
                result['entr_type'] = 'D+1'
                get_web_logger().info(f"✅ D+1 추정예수금 사용: {result['d1_entra']} (기본 예수금: {original_entr})")
            else:
                result['entr_type'] = 'D+0'
                get_web_logger().info(f"✅ 기본 예수금 사용: {result.get('entr', '0')}")
            
            # 주문가능금액도 참고용으로 추가
            if 'ord_alow_amt' in result:
                result['ord_alow_amt'] = result['ord_alow_amt']
            
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            # API 오류 정보가 있는 경우
            if result and result.get('error_code'):
                error_response = create_error_response(
                    result.get('error_code'), 
                    result.get('error_message', '예수금 정보를 가져올 수 없습니다.'), 
                    "get_deposit"
                )
                return jsonify(error_response)
            else:
                error_response = create_error_response("1513", "예수금 정보를 가져올 수 없습니다.", "get_deposit")
                return jsonify(error_response)
    except Exception as e:
        get_web_logger().error(f"예수금 조회 실패: {e}")
        error_response = create_error_response("2000", f"예수금 조회 실패: {str(e)}", "get_deposit")
        return jsonify(error_response)


@app.route('/api/account/assets')
def get_assets():
    """추정자산 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        result = get_current_account().get_estimated_assets()
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '자산 정보 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"자산 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'자산 조회 실패: {str(e)}'
        })


@app.route('/api/account/evaluation')
def get_evaluation():
    """계좌 평가 현황 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        # kt00018 계좌평가잔고내역요청 API 사용 (총 데이터용)
        balance_result = get_current_account().get_account_balance_detail()
        
        # kt00004 계좌평가현황요청 API 사용 (개별 종목 데이터용)
        evaluation_result = get_current_account().get_account_evaluation()
        
        if balance_result and evaluation_result:
            # kt00018의 총 데이터와 kt00004의 개별 종목 데이터를 결합
            combined_data = balance_result.copy()
            
            # kt00004에서 개별 종목 데이터 가져오기
            if 'stk_acnt_evlt_prst' in evaluation_result:
                stocks = evaluation_result['stk_acnt_evlt_prst']
                
                # 보유기간 계산 추가
                try:
                    from src.utils.order_history_manager import OrderHistoryManager
                    server_type = get_current_server()
                    order_manager = OrderHistoryManager(server_type)
                    
                    # 각 종목에 보유기간 추가
                    for stock in stocks:
                        stock_code = stock.get('stk_cd', '')
                        current_quantity = int(stock.get('rmnd_qty', '0'))
                        
                        if stock_code and current_quantity > 0:
                            # A 프리픽스 유지 (일관성을 위해)
                            holding_days = order_manager.get_holding_period(stock_code, current_quantity)
                            stock['holding_days'] = holding_days
                        else:
                            stock['holding_days'] = 0
                    
                    get_web_logger().info(f"📊 보유기간 계산 완료: {len(stocks)}개 종목")
                    
                except Exception as holding_error:
                    get_web_logger().error(f"🚨 보유기간 계산 중 오류: {holding_error}")
                    # 보유기간 계산 실패해도 기본 데이터는 반환
                    for stock in stocks:
                        stock['holding_days'] = 0
                
                combined_data['stk_acnt_evlt_prst'] = stocks
            
            return jsonify({
                'success': True,
                'data': combined_data
            })
        else:
            return jsonify({
                'success': False,
                'message': '계좌 평가 정보 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"계좌 평가 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'계좌 평가 조회 실패: {str(e)}'
        })


@app.route('/api/account/balance')
def get_balance():
    """계좌 잔고 내역 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        result = get_current_account().get_account_balance_detail()
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '잔고 정보 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"잔고 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'잔고 조회 실패: {str(e)}'
        })


@app.route('/api/account/orders/unexecuted')
def get_unexecuted_orders():
    """미체결 주문 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        # ka10075 API 사용 (미체결요청) - 키움 개발가이드에 맞게 수정
        result = get_current_account().get_unexecuted_orders(
            all_stock_type="0",  # 0: 전체, 1: 종목
            trade_type="0",      # 0: 전체, 1: 매도, 2: 매수
            stock_code="",       # 공백시 전체종목
            exchange="KRX"       # KRX: 한국거래소
        )
        
        if result and result.get('success') is not False:
            # ka10075 API 응답 데이터 구조에 맞게 매핑 (키움 개발가이드 기준)
            if 'oso' in result:
                mapped_data = {
                    'oso': []  # 미체결 주문
                }
                
                for order in result['oso']:
                    # 매도수구분 판단
                    sell_tp = '1' if '매도' in order.get('io_tp_nm', '') else '0'
                    
                    # 주문시간 처리 (tm이 "HHMMSS" 형태) - ka10075 API 기준
                    tm = order.get('tm', '')
                    if len(tm) >= 6:
                        # "154113" 형식인 경우 (HHMMSS)
                        ord_time = tm[:2] + ':' + tm[2:4] + ':' + tm[4:6]
                        ord_date = datetime.now().strftime('%Y%m%d')  # 오늘 날짜 사용
                    elif ':' in tm:
                        # "15:41:13" 형식인 경우
                        ord_time = tm
                        ord_date = datetime.now().strftime('%Y%m%d')
                    else:
                        # 시간만 있는 경우 오늘 날짜 사용
                        ord_date = datetime.now().strftime('%Y%m%d')
                        ord_time = tm
                    
                    mapped_order = {
                        'ord_no': order.get('ord_no', ''),
                        'stk_cd': order.get('stk_cd', ''),
                        'stk_nm': order.get('stk_nm', ''),
                        'sell_tp': sell_tp,
                        'ord_qty': order.get('ord_qty', '0'),
                        'ord_pric': order.get('ord_pric', '0'),  # ka10075 API: ord_pric
                        'oso_qty': order.get('oso_qty', '0'),   # ka10075 API: oso_qty (미체결수량)
                        'ord_stt': order.get('ord_stt', ''),    # ka10075 API: ord_stt (주문상태)
                        'ord_dt': ord_date,
                        'ord_tm': ord_time,
                        'orig_ord_no': order.get('orig_ord_no', ''),  # ka10075 API: orig_ord_no
                        'trde_tp': order.get('trde_tp', ''),    # ka10075 API: trde_tp (매매구분)
                        'io_tp_nm': order.get('io_tp_nm', ''),  # ka10075 API: io_tp_nm (주문구분)
                        'stex_tp': order.get('stex_tp', ''),    # ka10075 API: stex_tp (거래소구분)
                        'stex_tp_txt': order.get('stex_tp_txt', ''),  # ka10075 API: stex_tp_txt
                        'sor_yn': order.get('sor_yn', ''),      # ka10075 API: sor_yn (SOR 여부)
                        'stop_pric': order.get('stop_pric', '') # ka10075 API: stop_pric (스톱가)
                    }
                    mapped_data['oso'].append(mapped_order)
                
                return jsonify({
                    'success': True,
                    'data': mapped_data
                })
            else:
                return jsonify({
                    'success': True,
                    'data': {'oso': []}
                })
        else:
            return jsonify({
                'success': False,
                'message': '미체결 주문 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"미체결 주문 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'미체결 주문 조회 실패: {str(e)}'
        })


@app.route('/api/account/orders/executed')
def get_executed_orders():
    """체결 주문 조회 - 개선된 서버사이드 필터링"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        # 쿼리 파라미터에서 필터링 조건 가져오기
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=7)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        order_type = request.args.get('order_type', '0')  # 0: 전체, 1: 매도, 2: 매수
        stock_code = request.args.get('stock_code', '')
        order_no = request.args.get('order_no', '')
        
        # 매도수구분 매핑 (프론트엔드: buy/sell -> API: 2/1)
        sell_type = "0"  # 기본값: 전체
        if order_type == "buy":
            sell_type = "2"  # 매수
        elif order_type == "sell":
            sell_type = "1"  # 매도
        
        # ka10076 API 사용 (체결요청) - 키움 개발가이드에 맞게 수정
        result = get_current_account().get_executed_orders(
            query_type="0",  # 0: 전체, 1: 종목
            sell_type=sell_type,
            start_date=start_date,  # ka10076은 날짜 필터링 미지원이지만 파라미터는 유지
            end_date=end_date,
            exchange="1",  # 1: KRX (키움 개발가이드: 0: 통합, 1: KRX, 2: NXT)
            stock_code=stock_code,
            from_order_no=order_no
        )
        
        if result and result.get('success') is not False:
            # ka10076 API 응답 데이터 구조에 맞게 매핑 (키움 개발가이드 기준)
            if 'cntr' in result:
                mapped_data = {
                    'cntr': []
                }
                
                for order in result['cntr']:
                    # ka10076 API는 체결된 주문만 반환하므로 체결수량 확인
                    cntr_qty = int(order.get('cntr_qty', '0') or '0')
                    if cntr_qty > 0:
                        # 매도수구분 판단 (io_tp_nm에서 "매도" 포함 여부로 판단)
                        sell_tp = '1' if '매도' in order.get('io_tp_nm', '') else '0'
                        
                        # 체결금액 계산 (체결수량 * 체결가) - 안전한 정수 변환
                        try:
                            cntr_pric = int(order.get('cntr_pric', '0') or '0')
                            cntr_amt = str(cntr_qty * cntr_pric)
                        except (ValueError, TypeError):
                            cntr_qty = 0
                            cntr_pric = 0
                            cntr_amt = '0'
                    
                        # 주문시간 처리 (ord_tm이 "HHMMSS" 형태) - ka10076 API 기준
                        ord_tm = order.get('ord_tm', '')
                        if len(ord_tm) >= 6:
                            # "153815" 형식인 경우 (HHMMSS)
                            ord_time = ord_tm[:2] + ':' + ord_tm[2:4] + ':' + ord_tm[4:6]
                            ord_date = datetime.now().strftime('%Y%m%d')  # 오늘 날짜 사용
                        elif ':' in ord_tm:
                            # "15:38:15" 형식인 경우
                            ord_time = ord_tm
                            ord_date = datetime.now().strftime('%Y%m%d')
                        else:
                            # 시간만 있는 경우 오늘 날짜 사용
                            ord_date = datetime.now().strftime('%Y%m%d')
                            ord_time = ord_tm
                        
                        # 체결율 계산
                        try:
                            ord_qty = int(order.get('ord_qty', '0') or '0')
                            cntr_rate = round((cntr_qty / ord_qty * 100), 2) if ord_qty > 0 else 0
                        except (ValueError, TypeError, ZeroDivisionError):
                            cntr_rate = 0
                        
                        mapped_order = {
                            'ord_no': order.get('ord_no', ''),
                            'stk_cd': order.get('stk_cd', ''),
                            'stk_nm': order.get('stk_nm', ''),
                            'sell_tp': sell_tp,
                            'ord_qty': order.get('ord_qty', '0'),
                            'cntr_qty': order.get('cntr_qty', '0'),
                            'cntr_rate': cntr_rate,  # 체결율 추가
                            'cntr_pric': order.get('cntr_uv', '0'),  # 키움 개발가이드: cntr_uv
                            'cntr_amt': cntr_amt,
                            'cmsn': '0',  # kt00009에서는 수수료 정보 없음
                            'tax': '0',   # kt00009에서는 세금 정보 없음
                            'cntr_dt': ord_date,
                            'cntr_tm': ord_time,
                            'ord_dt': ord_date,
                            'ord_tm': ord_time,
                            'ord_pric': order.get('ord_uv', '0'),  # 키움 개발가이드: ord_uv
                            'orig_ord_no': order.get('orig_ord_no', ''),  # 키움 개발가이드: orig_ord_no
                            'ord_stt': order.get('acpt_tp', ''),  # 키움 개발가이드: acpt_tp (접수구분)
                            'trde_tp': order.get('trde_tp', ''),  # 키움 개발가이드: trde_tp (매매구분)
                            'io_tp_nm': order.get('io_tp_nm', ''),  # 키움 개발가이드: io_tp_nm (주문유형구분)
                            'stk_bond_tp': order.get('stk_bond_tp', ''),  # 주식채권구분 추가
                            'setl_tp': order.get('setl_tp', ''),  # 결제구분 추가
                            'crd_deal_tp': order.get('crd_deal_tp', ''),  # 신용거래구분 추가
                            'comm_ord_tp': order.get('comm_ord_tp', ''),  # 통신구분 추가
                            'mdfy_cncl_tp': order.get('mdfy_cncl_tp', ''),  # 정정/취소구분 추가
                            'dmst_stex_tp': order.get('dmst_stex_tp', ''),  # 거래소구분 추가
                            'cond_uv': order.get('cond_uv', '')  # 스톱가 추가
                        }
                        mapped_data['cntr'].append(mapped_order)
                
                return jsonify({
                    'success': True,
                    'data': mapped_data
                })
            else:
                return jsonify({
                    'success': True,
                    'data': {'cntr': []}
                })
        else:
            # API 오류 정보가 있는 경우
            if result and result.get('error_code'):
                error_response = create_error_response(
                    result.get('error_code'), 
                    result.get('error_message', '체결 주문 조회에 실패했습니다.'), 
                    "get_executed_orders"
                )
                return jsonify(error_response)
            else:
                return jsonify({
                    'success': False,
                    'message': '체결 주문 조회 실패'
                })
    except Exception as e:
        get_web_logger().error(f"체결 주문 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'체결 주문 조회 실패: {str(e)}'
        })


@app.route('/api/account/orders/executed/history')
def get_executed_orders_history():
    """체결 주문 이력 조회 - kt00007 API 사용 (특정일 조회)"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    # 쿼리 파라미터에서 필터링 조건 가져오기 (특정일 조회)
    order_date = request.args.get('start_date', datetime.now().strftime('%Y%m%d'))
    order_type = request.args.get('order_type', '0')
    stock_code = request.args.get('stock_code', '')
    
    try:
        # 매도수구분 매핑 (프론트엔드: buy/sell -> API: 2/1)
        sell_type = "0"  # 기본값: 전체
        if order_type == "buy":
            sell_type = "2"  # 매수
        elif order_type == "sell":
            sell_type = "1"  # 매도
        
        # kt00007 API 사용 (계좌별주문체결내역상세요청) - 키움 개발가이드에 맞게 수정
        # 모의서버에서는 날짜 범위를 지정하면 빈 배열이 반환되므로 날짜 파라미터 제거
        from src.utils.server_manager import get_current_server
        current_server = get_current_server()
        
        # 모의서버와 실전서버 모두 특정일 조회 사용
        result = get_current_account().get_executed_orders_history(
            query_type="1",  # 1: 주문순, 2: 역순, 3: 미체결, 4: 체결내역만
            sell_type=sell_type,
            order_date=order_date,
            exchange="%",    # %: 전체 거래소
            stock_code=stock_code,
            from_order_no=""
        )
        
        if result and result.get('success') is not False:
            # kt00007 API 응답 데이터 구조에 맞게 매핑 (키움 개발가이드 기준)
            if 'acnt_ord_cntr_prps_dtl' in result:
                mapped_data = {
                    'cntr': []
                }
                
                for order in result['acnt_ord_cntr_prps_dtl']:
                    # 체결수량이 있는 주문만 처리 (체결된 주문)
                    cntr_qty = int(order.get('cntr_qty', '0') or '0')
                    if cntr_qty > 0:
                        # 모의서버에서는 날짜 필터링 없이 모든 데이터 반환
                        # (모의서버 API가 이미 날짜별로 데이터를 제공하므로)
                        # 매도수구분 판단 (io_tp_nm에서 "매도" 포함 여부로 판단)
                        sell_tp = '1' if '매도' in order.get('io_tp_nm', '') else '0'
                        
                        # 체결금액 계산 (안전한 정수 변환)
                        try:
                            cntr_uv = int(order.get('cntr_uv', '0') or '0')
                            cntr_amt = str(cntr_qty * cntr_uv)
                        except (ValueError, TypeError):
                            cntr_qty = 0
                            cntr_uv = 0
                            cntr_amt = '0'
                        
                        # 주문시간 처리 (ord_tm이 "HH:MM:SS" 형태) - kt00007 API 기준
                        ord_tm = order.get('ord_tm', '')
                        if ':' in ord_tm:
                            # "13:05:43" 형식인 경우
                            ord_time = ord_tm
                            ord_date = datetime.now().strftime('%Y%m%d')  # 오늘 날짜 사용
                        elif len(ord_tm) >= 8:
                            # "YYYYMMDDHHMMSS" 형식인 경우
                            ord_date = ord_tm[:8]  # YYYYMMDD
                            ord_time = ord_tm[8:] if len(ord_tm) > 8 else ''  # HHMMSS
                        else:
                            # 시간만 있는 경우 오늘 날짜 사용
                            ord_date = datetime.now().strftime('%Y%m%d')
                            ord_time = ord_tm
                        
                        # 체결율 계산
                        try:
                            ord_qty = int(order.get('ord_qty', '0') or '0')
                            cntr_rate = round((cntr_qty / ord_qty * 100), 2) if ord_qty > 0 else 0
                        except (ValueError, TypeError, ZeroDivisionError):
                            cntr_rate = 0
                        
                        mapped_order = {
                            'ord_no': order.get('ord_no', ''),
                            'stk_cd': order.get('stk_cd', ''),
                            'stk_nm': order.get('stk_nm', ''),
                            'sell_tp': sell_tp,
                            'ord_qty': order.get('ord_qty', '0'),
                            'cntr_qty': order.get('cntr_qty', '0'),
                            'cntr_rate': cntr_rate,  # 체결율 추가
                            'cntr_pric': order.get('cntr_uv', '0'),  # 키움 개발가이드: cntr_uv
                            'cntr_amt': cntr_amt,
                            'cmsn': '0',  # kt00009에서는 수수료 정보 없음
                            'tax': '0',   # kt00009에서는 세금 정보 없음
                            'cntr_dt': ord_date,
                            'cntr_tm': ord_time,
                            'ord_dt': ord_date,
                            'ord_tm': ord_time,
                            'ord_pric': order.get('ord_uv', '0'),  # 키움 개발가이드: ord_uv
                            'orig_ord_no': order.get('orig_ord_no', ''),  # 키움 개발가이드: orig_ord_no
                            'ord_stt': order.get('acpt_tp', ''),  # 키움 개발가이드: acpt_tp (접수구분)
                            'trde_tp': order.get('trde_tp', ''),  # 키움 개발가이드: trde_tp (매매구분)
                            'io_tp_nm': order.get('io_tp_nm', ''),  # 키움 개발가이드: io_tp_nm (주문유형구분)
                            'stk_bond_tp': order.get('stk_bond_tp', ''),  # 주식채권구분 추가
                            'setl_tp': order.get('setl_tp', ''),  # 결제구분 추가
                            'crd_deal_tp': order.get('crd_deal_tp', ''),  # 신용거래구분 추가
                            'comm_ord_tp': order.get('comm_ord_tp', ''),  # 통신구분 추가
                            'mdfy_cncl_tp': order.get('mdfy_cncl_tp', ''),  # 정정/취소구분 추가
                            'dmst_stex_tp': order.get('dmst_stex_tp', ''),  # 거래소구분 추가
                            'cond_uv': order.get('cond_uv', '')  # 스톱가 추가
                        }
                        mapped_data['cntr'].append(mapped_order)
                
                return jsonify({
                    'success': True,
                    'data': mapped_data
                })
            else:
                return jsonify({
                    'success': True,
                    'data': {'cntr': []}
                })
        else:
            # API 오류 정보가 있는 경우
            if result and result.get('error_code'):
                error_response = create_error_response(
                    result.get('error_code'), 
                    result.get('error_message', '체결 주문 이력 조회에 실패했습니다.'), 
                    "get_executed_orders_history"
                )
                return jsonify(error_response)
            else:
                return jsonify({
                    'success': False,
                    'message': '체결 주문 이력 조회 실패'
                })
    except Exception as e:
        get_web_logger().error(f"체결 주문 이력 조회 실패: {e}")
        import traceback
        get_web_logger().error(f"상세 오류: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'체결 주문 이력 조회 실패: {str(e)}',
            'error_type': 'server_error'
        })


@app.route('/api/account/orders/unified')
def get_unified_orders():
    """통합 주문내역 조회 - kt00009 API 사용 (체결/미체결 통합)"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    # 쿼리 파라미터에서 필터링 조건 가져오기
    start_date = request.args.get('start_date', (datetime.now() - timedelta(days=7)).strftime('%Y%m%d'))
    end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
    order_type = request.args.get('order_type', '0')
    stock_code = request.args.get('stock_code', '')
    order_no = request.args.get('order_no', '')
    
    try:
        # 매도수구분 매핑 (프론트엔드: buy/sell -> API: 2/1)
        sell_type = "0"  # 기본값: 전체
        if order_type == "buy":
            sell_type = "2"  # 매수
        elif order_type == "sell":
            sell_type = "1"  # 매도
        
        # kt00009 API 사용 (통합 주문내역 조회) - 키움 개발가이드에 맞게 수정
        result = get_current_account().get_order_status(
            start_date=start_date,
            end_date=end_date,
            query_type="0",  # 0: 전체, 1: 체결
            sell_type=sell_type,
            stock_code=stock_code,
            from_order_no=order_no,
            market_type="0",  # 0: 전체, 1: 코스피, 2: 코스닥
            exchange="KRX"  # KRX: 한국거래소, NXT: 넥스트트레이드, %: 전체
        )
        
        if result and result.get('success') is not False:
            # kt00009 API 응답 데이터 구조에 맞게 매핑 (키움 개발가이드 기준)
            if 'acnt_ord_cntr_prst_array' in result:
                mapped_data = {
                    'cntr': [],  # 체결내역
                    'oso': []    # 미체결내역
                }
                
                for order in result['acnt_ord_cntr_prst_array']:
                    # 매도수구분 판단 (io_tp_nm에서 판단)
                    io_tp_nm = order.get('io_tp_nm', '')
                    sell_tp = '1' if '매도' in io_tp_nm else '0'
                    
                    # 체결수량과 주문수량 비교하여 체결/미체결 구분 - 안전한 정수 변환
                    try:
                        cntr_qty = int(order.get('cntr_qty', '0') or '0')
                        ord_qty = int(order.get('ord_qty', '0') or '0')
                    except (ValueError, TypeError):
                        cntr_qty = 0
                        ord_qty = 0
                    
                    # 체결수량이 있고 주문수량보다 작거나 같으면 체결, 아니면 미체결
                    if cntr_qty > 0 and cntr_qty <= ord_qty:  # 체결된 주문
                        # 체결금액 계산 - 안전한 정수 변환
                        try:
                            cntr_uv = int(order.get('cntr_uv', '0') or '0')
                            cntr_amt = str(cntr_qty * cntr_uv)
                        except (ValueError, TypeError):
                            cntr_amt = '0'
                        
                        # 체결시간 처리 (cntr_tm이 "HH:MM:SS" 형태) - 키움 개발가이드 기준
                        cntr_tm = order.get('cntr_tm', '')
                        if ':' in cntr_tm:
                            # "13:05:43" 형식인 경우
                            ord_time = cntr_tm
                            ord_date = datetime.now().strftime('%Y%m%d')  # 오늘 날짜 사용
                        elif len(cntr_tm) >= 8:
                            # "YYYYMMDDHHMMSS" 형식인 경우
                            ord_date = cntr_tm[:8]
                            ord_time = cntr_tm[8:] if len(cntr_tm) > 8 else ''
                        else:
                            # 시간만 있는 경우 오늘 날짜 사용
                            ord_date = datetime.now().strftime('%Y%m%d')
                            ord_time = cntr_tm
                        
                        # 체결율 계산
                        try:
                            cntr_rate = round((cntr_qty / ord_qty * 100), 2) if ord_qty > 0 else 0
                        except (ValueError, TypeError, ZeroDivisionError):
                            cntr_rate = 0
                        
                        mapped_order = {
                            'ord_no': order.get('ord_no', ''),
                            'stk_cd': order.get('stk_cd', ''),
                            'stk_nm': order.get('stk_nm', ''),
                            'sell_tp': sell_tp,
                            'ord_qty': order.get('ord_qty', '0'),
                            'cntr_qty': order.get('cntr_qty', '0'),
                            'cntr_rate': cntr_rate,  # 체결율 추가
                            'cntr_pric': order.get('cntr_uv', '0'),
                            'cntr_amt': cntr_amt,
                            'cmsn': '0',  # kt00009에서는 수수료 정보 없음
                            'tax': '0',   # kt00009에서는 세금 정보 없음
                            'cntr_dt': ord_date,
                            'cntr_tm': ord_time,
                            'ord_dt': ord_date,
                            'ord_tm': ord_time,
                            'ord_pric': order.get('ord_uv', '0'),
                            'orig_ord_no': order.get('orig_ord_no', ''),  # 키움 개발가이드: orig_ord_no
                            'ord_stt': order.get('acpt_tp', ''),  # 키움 개발가이드: acpt_tp (접수구분)
                            'trde_tp': order.get('trde_tp', ''),  # 키움 개발가이드: trde_tp (매매구분)
                            'io_tp_nm': order.get('io_tp_nm', ''),  # 키움 개발가이드: io_tp_nm (주문유형구분)
                            'stk_bond_tp': order.get('stk_bond_tp', ''),  # 주식채권구분 추가
                            'setl_tp': order.get('setl_tp', ''),  # 결제구분 추가
                            'crd_deal_tp': order.get('crd_deal_tp', ''),  # 신용거래구분 추가
                            'comm_ord_tp': order.get('comm_ord_tp', ''),  # 통신구분 추가
                            'mdfy_cncl_tp': order.get('mdfy_cncl_tp', ''),  # 정정/취소구분 추가
                            'cntr_tm': order.get('cntr_tm', ''),  # 체결시간 추가
                            'dmst_stex_tp': order.get('dmst_stex_tp', ''),  # 거래소구분 추가
                            'cond_uv': order.get('cond_uv', '')  # 스톱가 추가
                        }
                        mapped_data['cntr'].append(mapped_order)
                    
                    elif cntr_qty < ord_qty or cntr_qty == 0:  # 미체결 주문 (체결수량이 주문수량보다 작거나 0인 경우)
                        # 미체결수량 계산 - 안전한 계산
                        try:
                            oso_qty = str(ord_qty - cntr_qty)
                        except (ValueError, TypeError):
                            oso_qty = '0'
                        
                        # 주문시간 처리 (ord_tm이 "HH:MM:SS" 형태) - 키움 개발가이드 기준
                        ord_tm = order.get('ord_tm', '')
                        if ':' in ord_tm:
                            # "13:05:43" 형식인 경우
                            ord_time = ord_tm
                            ord_date = datetime.now().strftime('%Y%m%d')  # 오늘 날짜 사용
                        elif len(ord_tm) >= 8:
                            # "YYYYMMDDHHMMSS" 형식인 경우
                            ord_date = ord_tm[:8]
                            ord_time = ord_tm[8:] if len(ord_tm) > 8 else ''
                        else:
                            # 시간만 있는 경우 오늘 날짜 사용
                            ord_date = datetime.now().strftime('%Y%m%d')
                            ord_time = ord_tm
                        
                        mapped_order = {
                            'ord_no': order.get('ord_no', ''),
                            'stk_cd': order.get('stk_cd', ''),
                            'stk_nm': order.get('stk_nm', ''),
                            'sell_tp': sell_tp,  # 매도수구분 추가
                            'ord_qty': order.get('ord_qty', '0'),
                            'ord_pric': order.get('ord_uv', '0'),
                            'oso_qty': oso_qty,
                            'ord_stt': order.get('acpt_tp', ''),  # 키움 개발가이드: acpt_tp (접수구분)
                            'ord_dt': ord_date,
                            'ord_tm': ord_time,
                            'orig_ord_no': order.get('orig_ord_no', ''),  # 키움 개발가이드: orig_ord_no
                            'trde_tp': order.get('trde_tp', ''),  # 키움 개발가이드: trde_tp (매매구분)
                            'io_tp_nm': order.get('io_tp_nm', ''),  # 키움 개발가이드: io_tp_nm (주문유형구분)
                            'stk_bond_tp': order.get('stk_bond_tp', ''),  # 주식채권구분 추가
                            'setl_tp': order.get('setl_tp', ''),  # 결제구분 추가
                            'crd_deal_tp': order.get('crd_deal_tp', ''),  # 신용거래구분 추가
                            'comm_ord_tp': order.get('comm_ord_tp', ''),  # 통신구분 추가
                            'mdfy_cncl_tp': order.get('mdfy_cncl_tp', ''),  # 정정/취소구분 추가
                            'dmst_stex_tp': order.get('dmst_stex_tp', ''),  # 거래소구분 추가
                            'cond_uv': order.get('cond_uv', '')  # 스톱가 추가
                        }
                        mapped_data['oso'].append(mapped_order)
                
                return jsonify({
                    'success': True,
                    'data': mapped_data
                })
            else:
                return jsonify({
                    'success': True,
                    'data': {'cntr': [], 'oso': []}
                })
        else:
            # API 오류 정보가 있는 경우
            if result and result.get('error_code'):
                error_response = create_error_response(
                    result.get('error_code'), 
                    result.get('error_message', '통합 주문내역 조회에 실패했습니다.'), 
                    "get_unified_orders"
                )
                return jsonify(error_response)
            else:
                return jsonify({
                    'success': False,
                    'message': '통합 주문내역 조회 실패'
                })
    except Exception as e:
        get_web_logger().error(f"통합 주문내역 조회 실패: {e}")
        import traceback
        get_web_logger().error(f"상세 오류: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'통합 주문내역 조회 실패: {str(e)}',
            'error_type': 'server_error'
        })


@app.route('/api/account/trading-diary')
def get_trading_diary():
    """당일 매매일지 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        # ka10170(당일매매일지요청) 파라미터 고정:
        # - ottks_tp: "2"(당일매도 전체)로 호출해 매수/매도/손익 필드 누락을 방지하고 데이터 일관성 확보
        # - ch_crd_tp: "0"(전체)
        result = get_current_account().get_today_trading_diary(
            base_date="",
            odd_lot_type="2",
            cash_credit_type="0"
        )
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '매매일지 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/daily')
def get_daily_trading():
    """일별 매매일지 조회 - ka10074 API 사용 (일자별실현손익요청)"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 날짜 범위가 너무 크면 제한 (성능 최적화)
        date_range = (datetime.strptime(end_date, '%Y%m%d') - datetime.strptime(start_date, '%Y%m%d')).days
        if date_range > 365:  # 1년 초과 시 제한
            return jsonify({
                'success': False,
                'message': '조회 기간이 너무 깁니다. 최대 1년까지만 조회 가능합니다.'
            })
        
        # ka10074 API로 일자별 실현손익 조회
        result = get_current_account().get_daily_realized_profit(
            start_date=start_date,
            end_date=end_date
        )
        
        if result and result.get('success') is not False:
            daily_trades = []
            
            # ka10074 응답에서 dt_rlzt_pl 배열 처리
            if 'dt_rlzt_pl' in result and result['dt_rlzt_pl']:
                for day_data in result['dt_rlzt_pl']:
                    trade_date = day_data.get('dt', '')
                    if not trade_date:
                        continue
                    
                    # 요청된 날짜 범위 내의 데이터만 필터링
                    start_date_obj = datetime.strptime(start_date, '%Y%m%d')
                    end_date_obj = datetime.strptime(end_date, '%Y%m%d')
                    trade_date_obj = datetime.strptime(trade_date, '%Y%m%d')
                    
                    if start_date_obj <= trade_date_obj <= end_date_obj:
                        # ka10074 API 응답 데이터 (세금은 일자 요약에서만 제공되어 우선 유지)
                        tax = safe_float(day_data.get('tdy_trde_tax', '0'))

                        # ka10170 기반으로 '매도 체결'만 집계 (상세팝업과 동일 기준)
                        sell_amount = 0.0
                        total_commission_tax = 0.0
                        profit_amount = 0.0
                        trade_count = 0

                        try:
                            ka10170_result = get_current_account().get_daily_trading_diary(
                                base_dt=trade_date,
                                ottks_tp="2",  # 당일매도 전체
                                ch_crd_tp="0"  # 전체
                            )

                            if ka10170_result and ka10170_result.get('success') is not False and 'tdy_trde_diary' in ka10170_result:
                                for individual_trade in ka10170_result['tdy_trde_diary']:
                                    sell_amt_i = safe_float(individual_trade.get('sell_amt', '0'))
                                    sell_qty_i = safe_float(individual_trade.get('sell_qty', '0'))

                                    # 매수/0원 행 섞임 제외: 매도 체결(수량/금액 > 0)만 집계
                                    if sell_amt_i <= 0 or sell_qty_i <= 0:
                                        continue

                                    trade_count += 1
                                    sell_amount += sell_amt_i
                                    total_commission_tax += safe_float(individual_trade.get('cmsn_alm_tax', '0'))
                                    profit_amount += safe_float(individual_trade.get('pl_amt', '0'))
                        except Exception:
                            # API 호출 실패 시 ka10074 기반으로만 표시(기존 동작에 가까움)
                            sell_amount = safe_float(day_data.get('sell_amt', '0'))
                            commission = safe_float(day_data.get('tdy_trde_cmsn', '0'))
                            tax = safe_float(day_data.get('tdy_trde_tax', '0'))
                            profit_amount = safe_float(day_data.get('tdy_sel_pl', '0'))
                            buy_amount = sell_amount - profit_amount - commission - tax if sell_amount > 0 else safe_float(day_data.get('buy_amt', '0'))
                            if sell_amount == 0 or (buy_amount == 0 and sell_amount == 0):
                                continue

                            # 수익률 계산
                            return_rate = (profit_amount / buy_amount) * 100 if buy_amount > 0 else 0.0

                            daily_trade = {
                                'trade_date': trade_date,
                                'trade_count': 1,
                                'buy_amount': buy_amount,
                                'sell_amount': sell_amount,
                                'commission': commission,
                                'tax': tax,
                                'profit_amount': profit_amount,
                                'return_rate': return_rate
                            }
                            daily_trades.append(daily_trade)
                            continue

                        # 매도 체결이 없는 날은 제외
                        if sell_amount <= 0 or trade_count <= 0:
                            continue

                        # ka10170은 수수료+세금 합산(cmsn_alm_tax)만 제공 → ka10074의 tax를 우선 사용해 분리
                        if tax < 0:
                            tax = 0.0
                        commission = max(0.0, total_commission_tax - tax)

                        # 매수금액(원가) 역산: 매도금액 - 손익 - (수수료+세금)
                        buy_amount = sell_amount - profit_amount - total_commission_tax
                        
                        # 수익률 계산 (매수금액이 0보다 클 때만)
                        if buy_amount > 0:
                            return_rate = (profit_amount / buy_amount) * 100
                        else:
                            return_rate = 0.0
                        
                        # ka10074 응답을 프론트엔드 형식으로 변환
                        daily_trade = {
                            'trade_date': trade_date,
                            'trade_count': trade_count,  # ka10170에서 실제 거래 건수 조회
                            'buy_amount': buy_amount,
                            'sell_amount': sell_amount,
                            'commission': commission,
                            'tax': tax,
                            'profit_amount': profit_amount,
                            'return_rate': return_rate
                        }
                        daily_trades.append(daily_trade)
                
                # 날짜순 정렬
                daily_trades.sort(key=lambda x: x['trade_date'])
            
            # 총 거래 건수와 승률 계산 (ka10170 API 개별 거래 데이터 사용, '매도 체결'만)
            total_trade_count = 0
            total_win_count = 0
            
            for trade in daily_trades:
                trade_date = trade['trade_date']
                try:
                    # ka10170 API로 해당 날짜의 개별 거래 데이터 조회
                    ka10170_result = get_current_account().get_daily_trading_diary(
                        base_dt=trade_date,
                        ottks_tp="2",  # 당일매도 전체
                        ch_crd_tp="0"  # 전체
                    )
                    if ka10170_result and ka10170_result.get('success') is not False and 'tdy_trde_diary' in ka10170_result:
                        ka10170_trades = ka10170_result['tdy_trde_diary']
                        for individual_trade in ka10170_trades:
                            sell_amt_i = safe_float(individual_trade.get('sell_amt', '0'))
                            sell_qty_i = safe_float(individual_trade.get('sell_qty', '0'))
                            if sell_amt_i <= 0 or sell_qty_i <= 0:
                                continue
                            pl_amt = safe_float(individual_trade.get('pl_amt', '0'))
                            total_trade_count += 1
                            if pl_amt > 0:
                                total_win_count += 1
                except:
                    # API 호출 실패 시 일별 집계 데이터 사용
                    total_trade_count += trade['trade_count']
                    if trade['profit_amount'] > 0:
                        total_win_count += trade['trade_count']
            
            win_rate = (total_win_count / total_trade_count * 100) if total_trade_count > 0 else 0.0
            
            return jsonify({
                'success': True,
                'data': {
                    'daily_trades': daily_trades,
                    'summary': {
                        'total_trade_count': total_trade_count,
                        'total_win_count': total_win_count,
                        'win_rate': round(win_rate, 1)
                    }
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': '일자별실현손익 조회 실패'
            })
        
    except Exception as e:
        get_web_logger().error(f"일별 매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'일별 매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/monthly')
def get_monthly_trading():
    """월별 매매일지 조회 - ka10074 API 사용 (일자별실현손익요청)"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=365)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 날짜 범위가 너무 크면 제한 (성능 최적화)
        date_range = (datetime.strptime(end_date, '%Y%m%d') - datetime.strptime(start_date, '%Y%m%d')).days
        if date_range > 365:  # 1년 초과 시 제한
            return jsonify({
                'success': False,
                'message': '조회 기간이 너무 깁니다. 최대 1년까지만 조회 가능합니다.'
            })
        
        # ka10074 API로 일자별 실현손익 조회
        result = get_current_account().get_daily_realized_profit(
            start_date=start_date,
            end_date=end_date
        )
        
        if result and result.get('success') is not False:
            monthly_trades = {}
            
            # ka10074 응답에서 dt_rlzt_pl 배열 처리
            if 'dt_rlzt_pl' in result and result['dt_rlzt_pl']:
                # 요청된 날짜 범위 내의 데이터만 필터링
                start_date_obj = datetime.strptime(start_date, '%Y%m%d')
                end_date_obj = datetime.strptime(end_date, '%Y%m%d')
                
                for day_data in result['dt_rlzt_pl']:
                    trade_date = day_data.get('dt', '')
                    if not trade_date:
                        continue
                    
                    trade_date_obj = datetime.strptime(trade_date, '%Y%m%d')
                    if not (start_date_obj <= trade_date_obj <= end_date_obj):
                        continue
                    
                    month_key = trade_date[:6]  # YYYYMM
                    
                    if month_key not in monthly_trades:
                        monthly_trades[month_key] = {
                            'month': month_key,
                            'trade_count': 0,
                            'buy_amount': 0,
                            'sell_amount': 0,
                            'commission': 0,
                            'tax': 0,
                            'profit_amount': 0,
                            'return_rate': 0
                        }
                    
                    # ka10074 API 응답 데이터
                    sell_amount = safe_float(day_data.get('sell_amt', '0'))
                    commission = safe_float(day_data.get('tdy_trde_cmsn', '0'))
                    tax = safe_float(day_data.get('tdy_trde_tax', '0'))
                    profit_amount = safe_float(day_data.get('tdy_sel_pl', '0'))
                    
                    # ka10074의 buy_amt가 0원인 문제 해결: 역산 계산
                    if sell_amount > 0:
                        buy_amount = sell_amount - profit_amount - commission - tax
                    else:
                        buy_amount = safe_float(day_data.get('buy_amt', '0'))
                    
                    # 월별 데이터 누적
                    monthly_trades[month_key]['trade_count'] += 1
                    monthly_trades[month_key]['buy_amount'] += buy_amount
                    monthly_trades[month_key]['sell_amount'] += sell_amount
                    monthly_trades[month_key]['commission'] += commission
                    monthly_trades[month_key]['tax'] += tax
                    monthly_trades[month_key]['profit_amount'] += profit_amount
                
                # 월별 수익률 계산
                for month, data in monthly_trades.items():
                    if data['buy_amount'] > 0:
                        data['return_rate'] = (data['profit_amount'] / data['buy_amount']) * 100
                
                # 월별 데이터를 리스트로 변환하고 정렬
                monthly_list = list(monthly_trades.values())
                monthly_list.sort(key=lambda x: x['month'])
                
                return jsonify({
                    'success': True,
                    'data': {
                        'monthly_trades': monthly_list
                    }
                })
            else:
                return jsonify({
                    'success': True,
                    'data': {
                        'monthly_trades': []
                    }
                })
        else:
            return jsonify({
                'success': False,
                'message': '일자별실현손익 조회 실패'
            })
        
    except Exception as e:
        get_web_logger().error(f"월별 매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'월별 매매일지 조회 실패: {str(e)}'
        })




@app.route('/api/account/trading/daily/<trade_date>')
def get_daily_trading_detail(trade_date):
    """일별 매매 상세 조회 - ka10074 + kt00007 + ka10170 API 조합 사용"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        # 1단계: ka10170 API로 해당 날짜의 정확한 매매일지 정보 조회
        ka10170_result = get_current_account().get_daily_trading_diary(
            base_dt=trade_date,
            ottks_tp="2",  # 당일매도 전체
            ch_crd_tp="0"  # 전체
        )
        
        # 2단계: kt00007 API로 해당 날짜의 주문체결내역 조회 (시간 정보용)
        kt00007_result = get_current_account().get_executed_orders_history(
            order_date=trade_date,
            query_type="4",  # 체결내역만
            stock_bond_type="1",  # 주식
            sell_type="0",  # 전체
            stock_code="",  # 전체 종목
            from_order_no="",  # 전체 주문
            exchange="%"  # 전체 거래소
        )
        
        if ka10170_result and ka10170_result.get('success') is not False and 'tdy_trde_diary' in ka10170_result:
            trades = []
            ka10170_trades = ka10170_result['tdy_trde_diary']
            
            # kt00007에서 시간 정보 매핑
            kt00007_trades = {}
            if kt00007_result and 'acnt_ord_cntr_prps_dtl' in kt00007_result and kt00007_result['acnt_ord_cntr_prps_dtl']:
                for trade in kt00007_result['acnt_ord_cntr_prps_dtl']:
                    stock_name = trade.get('stk_nm', '')
                    cntr_tm = trade.get('ord_tm', '')
                    if stock_name not in kt00007_trades:
                        kt00007_trades[stock_name] = cntr_tm
            
            total_sell_amount = 0
            total_buy_amount = 0
            total_commission_tax = 0
            total_profit = 0
            
            for trade in ka10170_trades:
                stock_name = trade.get('stk_nm', '')
                sell_amt = safe_float(trade.get('sell_amt', '0'))
                cmsn_alm_tax = safe_float(trade.get('cmsn_alm_tax', '0'))
                pl_amt = safe_float(trade.get('pl_amt', '0'))
                prft_rt = safe_float(trade.get('prft_rt', '0'))
                sell_qty = safe_float(trade.get('sell_qty', '0'))
                sel_avg_pric = safe_float(trade.get('sel_avg_pric', '0'))

                # 매수/0원 행 섞임 제외: 매도 체결(수량/금액 > 0)만 표시
                if sell_amt <= 0 or sell_qty <= 0:
                    continue
                
                # 매수금액 계산: 매도금액 - 손익 - 수수료_세금
                buy_amt = sell_amt - pl_amt - cmsn_alm_tax
                
                # 총합 계산
                total_sell_amount += sell_amt
                total_buy_amount += buy_amt
                total_commission_tax += cmsn_alm_tax
                total_profit += pl_amt
                
                # kt00007에서 시간 정보 가져오기
                cntr_tm = kt00007_trades.get(stock_name, '')
                
                # 매도 거래 정보 생성
                mapped_trade = {
                    'stk_cd': trade.get('stk_cd', ''),
                    'stk_nm': stock_name,
                    'sel_avg_pric': str(sel_avg_pric),  # 매도 평균단가
                    'sell_qty': str(sell_qty),  # 매도 수량
                    'pl_amt': str(pl_amt),  # 손익
                    'sell_amt': str(sell_amt),  # 매도금액
                    'buy_amt': str(buy_amt),  # 매수금액 (ka10170에서 제공)
                    'cmsn_alm_tax': str(cmsn_alm_tax),  # 수수료_세금
                    'prft_rt': str(prft_rt),  # 수익률
                    'cntr_tm': cntr_tm,  # 주문시간 (kt00007에서)
                    'sell_tp': '1',  # 매도 거래
                    'cntr_qty': str(sell_qty),  # 체결수량
                    'cntr_pric': str(sel_avg_pric),  # 체결단가
                    'cntr_amt': str(sell_amt),  # 체결금액
                    'trde_tp': '',  # 매매구분
                    'crd_tp': '',  # 신용구분
                    'ord_no': '',  # 주문번호
                    'acpt_tp': ''  # 접수구분
                }
                trades.append(mapped_trade)
            
            return jsonify({
                'success': True,
                'data': {
                    'trades': trades,
                    'summary': {
                        'total_commission_tax': total_commission_tax,
                        'total_profit': total_profit,
                        'total_sell_amount': total_sell_amount,
                        'total_buy_amount': total_buy_amount,
                        'trade_count': len(trades)
                    }
                }
            })
        else:
            return jsonify({
                'success': True,
                'data': {
                    'trades': [],
                    'summary': {
                        'total_commission_tax': 0,
                        'total_profit': 0,
                        'total_sell_amount': 0,
                        'total_buy_amount': 0,
                        'trade_count': 0
                    }
                }
            })
            
    except Exception as e:
        get_web_logger().error(f"일별 매매 상세 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'일별 매매 상세 조회 실패: {str(e)}'
        })


@app.route('/api/cache/clear')
def clear_cache():
    """API 캐시 클리어 (캐시 비활성화로 인해 더 이상 사용되지 않음)"""
    return jsonify({
        'success': True,
        'message': '캐시가 비활성화되어 있습니다. 모든 API 호출은 실시간으로 처리됩니다.'
    })


@app.route('/api/quote/stock/<stock_code>')
def get_stock_info(stock_code):
    """종목 정보 조회"""
    try:
        result = get_current_quote().get_stock_info(stock_code)
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '종목 정보 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"종목 정보 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'종목 정보 조회 실패: {str(e)}'
        })


@app.route('/api/quote/price/<stock_code>')
def get_stock_price(stock_code):
    """주식 호가 조회"""
    try:
        result = get_current_quote().get_stock_quote(stock_code)
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '주식 호가 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"주식 호가 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'주식 호가 조회 실패: {str(e)}'
        })


@app.route('/api/quote/chart/<stock_code>')
def get_stock_chart(stock_code):
    """주식 차트 데이터 조회"""
    try:
        period = request.args.get('period', 'D')  # D, W, M, H, M
        days = int(request.args.get('days', 30))
        
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        
        if period == 'D':
            result = get_current_quote().get_stock_daily_chart(stock_code, start_date, end_date)
        elif period == 'W':
            result = get_current_quote().get_stock_weekly_chart(stock_code, start_date, end_date)
        elif period == 'M':
            result = get_current_quote().get_stock_monthly_chart(stock_code, start_date, end_date)
        else:
            result = get_current_quote().get_stock_daily_chart(stock_code, start_date, end_date)
        
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '차트 데이터 조회 실패'
            })
    except Exception as e:
        get_web_logger().error(f"차트 데이터 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'차트 데이터 조회 실패: {str(e)}'
        })


@app.route('/api/order/buy', methods=['POST'])
def buy_stock():
    """주식 매수 주문"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        quantity = int(data.get('quantity', 0))
        price = int(data.get('price', 0))
        order_type = data.get('order_type', '0')
        order_amount = data.get('order_amount')  # 금액주문 시 사용
        
        # 주문 타입 매핑 (기존 형식 -> 새로운 API 형식)
        order_type_mapping = {
            '00': '0',  # 지정가
            '01': '3',  # 시장가
            '05': '5',  # 조건부지정가
        }
        order_type = order_type_mapping.get(order_type, order_type)
        
        if not stock_code:
            return jsonify({
                'success': False,
                'message': '종목코드를 입력해주세요.'
            })
        
        # 금액주문인 경우 수량 계산
        if order_amount and int(order_amount) > 0:
            if order_type == '3':  # 시장가 금액주문
                # 시장가 금액주문은 현재가로 수량 계산
                stock_info = kiwoom_quote.get_stock_info(stock_code)
                if not stock_info or not stock_info.get('data'):
                    return jsonify({
                        'success': False,
                        'message': '종목 정보를 가져올 수 없습니다.'
                    })
                
                current_price = int(stock_info['data'].get('stk_prc', 0))
                if current_price <= 0:
                    return jsonify({
                        'success': False,
                        'message': '현재가 정보를 가져올 수 없습니다.'
                    })
                
                quantity = int(order_amount) // current_price
                price = 0  # 시장가
                
                if quantity <= 0:
                    return jsonify({
                        'success': False,
                        'message': '주문금액이 너무 적습니다.'
                    })
            else:  # 지정가 금액주문
                if price <= 0:
                    return jsonify({
                        'success': False,
                        'message': '지정가 금액주문 시 가격을 입력해주세요.'
                    })
                quantity = int(order_amount) // price
                
                if quantity <= 0:
                    return jsonify({
                        'success': False,
                        'message': '주문금액이 너무 적습니다.'
                    })
        else:
            # 일반 수량주문
            if quantity <= 0:
                return jsonify({
                    'success': False,
                    'message': '주문수량을 입력해주세요.'
                })
            
            # 지정가 주문인 경우 가격 검증
            if order_type == '0' and price <= 0:
                return jsonify({
                    'success': False,
                    'message': '지정가 주문 시 가격을 입력해주세요.'
                })
        
        result = get_current_order().buy_stock(stock_code, quantity, price, order_type)
        
        if result and result.get('success') is not False:
            # 성공 메시지
            order_no = result.get("ord_no", "N/A")
            order_type_text = "시장가" if order_type == "3" else "지정가"
            quantity_text = f"{quantity}주" if orderUnit != 'amount' else f"{orderAmount}원"
            
            success_message = f"✅ 매수주문이 접수되었습니다!\n" \
                            f"• 종목: {stock_code}\n" \
                            f"• 수량: {quantity_text}\n" \
                            f"• 방식: {order_type_text}\n" \
                            f"• 주문번호: {order_no}"
            
            return jsonify({
                'success': True,
                'data': result,
                'message': success_message
            })
        else:
            # API 오류 정보가 있는 경우
            if result and result.get('error_code'):
                error_response = create_error_response(
                    result.get('error_code'), 
                    result.get('error_message', '매수주문 처리 중 오류가 발생했습니다.'), 
                    "buy_stock"
                )
                return jsonify(error_response)
            else:
                # 일반적인 오류
                error_response = create_error_response("2000", "매수주문 처리 중 오류가 발생했습니다.", "buy_stock")
                return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"매수 주문 실패: {e}")
        error_response = create_error_response("2000", f"매수 주문 실패: {str(e)}", "buy_stock")
        return jsonify(error_response)


@app.route('/api/order/sell', methods=['POST'])
def sell_stock():
    """주식 매도 주문 (수량주문만 지원)"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        quantity = int(data.get('quantity', 0))
        price = int(data.get('price', 0))
        order_type = data.get('order_type', '0')
        
        # 주문 타입 매핑 (기존 형식 -> 새로운 API 형식)
        order_type_mapping = {
            '00': '0',  # 지정가
            '01': '3',  # 시장가
            '05': '5',  # 조건부지정가
        }
        order_type = order_type_mapping.get(order_type, order_type)
        
        if not stock_code:
            return jsonify({
                'success': False,
                'message': '종목코드를 입력해주세요.'
            })
        
        if quantity <= 0:
            return jsonify({
                'success': False,
                'message': '주문수량을 입력해주세요.'
            })
        
        # 지정가 주문인 경우 가격 검증
        if order_type == '0' and price <= 0:
            return jsonify({
                'success': False,
                'message': '지정가 주문 시 가격을 입력해주세요.'
            })
        
        result = get_current_order().sell_stock(stock_code, quantity, price, order_type)
        
        if result and result.get('success') is not False:
            # 성공 메시지
            order_no = result.get("ord_no", "N/A")
            order_type_text = "시장가" if order_type == "3" else "지정가"
            
            success_message = f"✅ 매도주문이 접수되었습니다!\n" \
                            f"• 종목: {stock_code}\n" \
                            f"• 수량: {quantity}주\n" \
                            f"• 방식: {order_type_text}\n" \
                            f"• 주문번호: {order_no}"
            
            return jsonify({
                'success': True,
                'data': result,
                'message': success_message
            })
        else:
            # API 오류 정보가 있는 경우
            if result and result.get('error_code'):
                error_response = create_error_response(
                    result.get('error_code'), 
                    result.get('error_message', '매도주문 처리 중 오류가 발생했습니다.'), 
                    "sell_stock"
                )
                return jsonify(error_response)
            else:
                # 일반적인 오류
                error_response = create_error_response("2000", "매도주문 처리 중 오류가 발생했습니다.", "sell_stock")
                return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"매도 주문 실패: {e}")
        error_response = create_error_response("2000", f"매도 주문 실패: {str(e)}", "sell_stock")
        return jsonify(error_response)


@app.route('/api/order/cancel', methods=['POST'])
def cancel_order():
    """주문 취소"""
    try:
        data = request.get_json()
        order_no = data.get('order_no')
        stock_code = data.get('stock_code')
        quantity = int(data.get('quantity', 0))
        
        if not order_no or not stock_code or quantity <= 0:
            error_response = create_error_response("1501", "주문 취소 정보가 올바르지 않습니다.", "cancel_order")
            return jsonify(error_response)
        
        # 주문번호 유효성 검증 (7자리 숫자여야 함)
        if not order_no.isdigit() or len(order_no) != 7:
            error_response = create_error_response("1502", f"주문번호 형식이 올바르지 않습니다. (입력: {order_no}, 요구: 7자리 숫자)", "cancel_order")
            return jsonify(error_response)
        
        # 주문 상태 확인 (선택적 - 주문이 존재하는지 확인)
        try:
            # 미체결 주문 조회로 해당 주문이 존재하는지 확인
            from src.api.account import get_current_account
            account = get_current_account()
            if account:
                # 미체결 주문 조회 (최근 1일)
                from datetime import datetime, timedelta
                today = datetime.now().strftime('%Y%m%d')
                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                
                pending_orders = account.get_pending_orders(yesterday, today, stock_code)
                if pending_orders and pending_orders.get('success', False):
                    orders = pending_orders.get('data', {}).get('acnt_ord_cntr_prps_dtl', [])
                    order_exists = any(order.get('orig_ord_no') == order_no for order in orders)
                    
                    if not order_exists:
                        error_response = create_error_response("1503", f"주문번호 {order_no}에 해당하는 미체결 주문을 찾을 수 없습니다.", "cancel_order")
                        return jsonify(error_response)
        except Exception as e:
            # 주문 상태 확인 실패해도 취소 시도는 계속 진행
            get_web_logger().warning(f"주문 상태 확인 실패 (취소 시도 계속): {e}")
        
        result = get_current_order().cancel_order(order_no, stock_code, quantity)
        
        if result and result.get('success', False):
            success_message = f"✅ 주문이 취소되었습니다!\n" \
                            f"• 주문번호: {order_no}\n" \
                            f"• 종목: {stock_code}\n" \
                            f"• 수량: {quantity}주"
            
            return jsonify({
                'success': True,
                'data': result,
                'message': success_message
            })
        else:
            # 실제 API 에러 메시지 표시
            error_msg = result.get('error_message', '주문 취소 처리 중 오류가 발생했습니다.') if result else '주문 취소 처리 중 오류가 발생했습니다.'
            error_response = create_error_response("2000", f"주문 취소 실패: {error_msg}", "cancel_order")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"주문 취소 실패: {e}")
        error_response = create_error_response("2000", f"주문 취소 실패: {str(e)}", "cancel_order")
        return jsonify(error_response)


# 차트 API 엔드포인트들
@app.route('/api/chart/tick', methods=['POST'])
def get_tick_chart():
    """주식 틱차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        tick_scope = data.get('tick_scope', '1')
        upd_stkpc_tp = data.get('upd_stkpc_tp', '0')
        
        if not stock_code:
            error_response = create_error_response("1501", "종목코드가 필요합니다.", "get_tick_chart")
            return jsonify(error_response)
        
        result = get_current_chart().get_stock_tick_chart(stock_code, tick_scope, upd_stkpc_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '틱차트 조회 실패') if result else '틱차트 조회 실패'
            error_response = create_error_response("2000", f"틱차트 조회 실패: {error_msg}", "get_tick_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"틱차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"틱차트 조회 실패: {str(e)}", "get_tick_chart")
        return jsonify(error_response)

@app.route('/api/chart/minute', methods=['POST'])
def get_minute_chart():
    """주식 분봉차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        tick_scope = data.get('tick_scope', '1')
        upd_stkpc_tp = data.get('upd_stkpc_tp', '0')
        
        if not stock_code:
            error_response = create_error_response("1501", "종목코드가 필요합니다.", "get_minute_chart")
            return jsonify(error_response)
        
        result = get_current_chart().get_stock_minute_chart(stock_code, tick_scope, upd_stkpc_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '분봉차트 조회 실패') if result else '분봉차트 조회 실패'
            error_response = create_error_response("2000", f"분봉차트 조회 실패: {error_msg}", "get_minute_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"분봉차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"분봉차트 조회 실패: {str(e)}", "get_minute_chart")
        return jsonify(error_response)

@app.route('/api/chart/daily', methods=['POST'])
def get_daily_chart():
    """주식 일봉차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        base_dt = data.get('base_dt', '')
        upd_stkpc_tp = data.get('upd_stkpc_tp', '0')
        
        if not stock_code:
            error_response = create_error_response("1501", "종목코드가 필요합니다.", "get_daily_chart")
            return jsonify(error_response)
        
        # base_dt가 비어있으면 오늘 날짜로 설정 (키움 API는 base_dt부터 과거 데이터를 가져옴)
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        result = get_current_chart().get_stock_daily_chart(stock_code, base_dt, upd_stkpc_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '일봉차트 조회 실패') if result else '일봉차트 조회 실패'
            error_response = create_error_response("2000", f"일봉차트 조회 실패: {error_msg}", "get_daily_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"일봉차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"일봉차트 조회 실패: {str(e)}", "get_daily_chart")
        return jsonify(error_response)

@app.route('/api/chart/weekly', methods=['POST'])
def get_weekly_chart():
    """주식 주봉차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        base_dt = data.get('base_dt', '')
        upd_stkpc_tp = data.get('upd_stkpc_tp', '0')
        
        if not stock_code:
            error_response = create_error_response("1501", "종목코드가 필요합니다.", "get_weekly_chart")
            return jsonify(error_response)
        
        # base_dt가 비어있으면 오늘 날짜로 설정
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        result = get_current_chart().get_stock_weekly_chart(stock_code, base_dt, upd_stkpc_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '주봉차트 조회 실패') if result else '주봉차트 조회 실패'
            error_response = create_error_response("2000", f"주봉차트 조회 실패: {error_msg}", "get_weekly_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"주봉차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"주봉차트 조회 실패: {str(e)}", "get_weekly_chart")
        return jsonify(error_response)

@app.route('/api/chart/monthly', methods=['POST'])
def get_monthly_chart():
    """주식 월봉차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        base_dt = data.get('base_dt', '')
        upd_stkpc_tp = data.get('upd_stkpc_tp', '0')
        
        if not stock_code:
            error_response = create_error_response("1501", "종목코드가 필요합니다.", "get_monthly_chart")
            return jsonify(error_response)
        
        # base_dt가 비어있으면 오늘 날짜로 설정
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        result = get_current_chart().get_stock_monthly_chart(stock_code, base_dt, upd_stkpc_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '월봉차트 조회 실패') if result else '월봉차트 조회 실패'
            error_response = create_error_response("2000", f"월봉차트 조회 실패: {error_msg}", "get_monthly_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"월봉차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"월봉차트 조회 실패: {str(e)}", "get_monthly_chart")
        return jsonify(error_response)

@app.route('/api/chart/yearly', methods=['POST'])
def get_yearly_chart():
    """주식 년봉차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        base_dt = data.get('base_dt', '')
        upd_stkpc_tp = data.get('upd_stkpc_tp', '0')
        
        if not stock_code:
            error_response = create_error_response("1501", "종목코드가 필요합니다.", "get_yearly_chart")
            return jsonify(error_response)
        
        # base_dt가 비어있으면 오늘 날짜로 설정
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        result = get_current_chart().get_stock_yearly_chart(stock_code, base_dt, upd_stkpc_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '년봉차트 조회 실패') if result else '년봉차트 조회 실패'
            error_response = create_error_response("2000", f"년봉차트 조회 실패: {error_msg}", "get_yearly_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"년봉차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"년봉차트 조회 실패: {str(e)}", "get_yearly_chart")
        return jsonify(error_response)

@app.route('/api/chart/investor', methods=['POST'])
def get_investor_chart():
    """투자자별 차트 조회"""
    try:
        data = request.get_json()
        stock_code = data.get('stock_code')
        dt = data.get('dt', '')
        amt_qty_tp = data.get('amt_qty_tp', '1')
        trde_tp = data.get('trde_tp', '0')
        unit_tp = data.get('unit_tp', '1000')
        
        if not stock_code or not dt:
            error_response = create_error_response("1501", "종목코드와 일자가 필요합니다.", "get_investor_chart")
            return jsonify(error_response)
        
        result = get_current_chart().get_investor_chart(stock_code, dt, amt_qty_tp, trde_tp, unit_tp)
        
        if result and result.get('return_code') == 0:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            error_msg = result.get('return_msg', '투자자별 차트 조회 실패') if result else '투자자별 차트 조회 실패'
            error_response = create_error_response("2000", f"투자자별 차트 조회 실패: {error_msg}", "get_investor_chart")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"투자자별 차트 조회 실패: {e}")
        error_response = create_error_response("2000", f"투자자별 차트 조회 실패: {str(e)}", "get_investor_chart")
        return jsonify(error_response)


# 자동매매 API 엔드포인트들
@app.route('/api/auto-trading/config')
def get_auto_trading_config():
    """자동매매 설정 조회"""
    try:
        server_type = get_request_server_type()
        config = get_config_manager_for(server_type).load_config()
        return jsonify({
            'success': True,
            'data': config
        })
    except Exception as e:
        get_web_logger().error(f"자동매매 설정 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'설정 조회 실패: {str(e)}'
        })


@app.route('/api/auto-trading/config', methods=['POST'])
def save_auto_trading_config():
    """자동매매 설정 저장"""
    try:
        server_type = get_request_server_type()
        config = request.get_json()
        if get_config_manager_for(server_type).save_config(config):
            return jsonify({
                'success': True,
                'message': '설정이 저장되었습니다.'
            })
        else:
            return jsonify({
                'success': False,
                'message': '설정 저장에 실패했습니다.'
            })
    except Exception as e:
        get_web_logger().error(f"자동매매 설정 저장 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'설정 저장 실패: {str(e)}'
        })


@app.route('/api/auto-trading/status')
def get_auto_trading_status():
    """자동매매 상태 조회"""
    try:
        server_type = get_request_server_type()
        config_manager = get_config_manager_for(server_type)
        engine = get_engine_for(server_type)
        scheduler = get_scheduler_for(server_type)

        config = config_manager.load_config()
        last_execution = config_manager.get_last_execution_time()
        today_executed = config_manager.is_today_executed()
        
        # 실행 상태 조회
        execution_status = engine.get_execution_status()
        
        return jsonify({
            'success': True,
            'data': {
                'enabled': config.get('auto_trading_enabled', False),
                'last_execution': last_execution,
                'today_executed': today_executed,
                'is_running': execution_status['is_running'],
                'current_status': execution_status['current_status'],
                'progress_percentage': execution_status['progress_percentage'],
                'last_check_time': scheduler.get_last_check_time()
            }
        })
    except Exception as e:
        get_web_logger().error(f"자동매매 상태 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'상태 조회 실패: {str(e)}'
        })


@app.route('/api/auto-trading/execute', methods=['POST'])
def execute_auto_trading():
    """자동매매 수동 실행"""
    try:
        from datetime import datetime
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 자동매매 수동 실행 요청")
        server_type = get_request_server_type()
        result = get_engine_for(server_type).execute_strategy(manual_execution=True)
        
        if result['success']:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 자동매매 실행 성공: {result['message']}")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 자동매매 실행 실패: {result['message']}")
        
        return jsonify(result)
    except Exception as e:
        from datetime import datetime
        error_message = f'자동매매 실행 실패: {str(e)}'
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ {error_message}")
        get_web_logger().error(f"자동매매 실행 실패: {e}")
        return jsonify({
            'success': False,
            'message': error_message
        })


@app.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    """키움 API 인증 상태 조회"""
    try:
        # 현재 서버 타입에 맞는 인증 상태 확인
        server_type = get_request_server_type()
        get_web_logger().info(f"인증 상태 확인 - 현재 서버: {server_type}")
        
        # 현재 서버에 맞는 인증 인스턴스 사용
        from src.api.auth import KiwoomAuth
        current_auth = KiwoomAuth(server_type)
        get_web_logger().info(f"인증 상태 확인 - {server_type} 서버용 인증 인스턴스 사용")
        
        # 세션 인증 상태와 토큰 유효성을 모두 확인
        session_authenticated = session.get('authenticated', False)
        token_valid = current_auth.is_token_valid()
        
        # 둘 다 True여야만 인증된 것으로 간주
        is_authenticated = session_authenticated and token_valid
        
        get_web_logger().info(f"세션 인증 상태: {session_authenticated}, 토큰 유효성: {token_valid}, 최종 인증 상태: {is_authenticated}")
        
        # 인증되지 않은 경우 세션도 정리
        if not is_authenticated:
            clear_auth_session()
            get_web_logger().info("인증 실패로 인해 세션을 정리했습니다.")
        
        token_info = current_auth.get_token_info() if is_authenticated else None
        
        return jsonify({
            'success': True,
            'authenticated': is_authenticated,
            'token_info': token_info
        })
    except AttributeError as e:
        get_web_logger().error(f"인증 메서드 없음: {e}")
        return jsonify({
            'success': False,
            'message': '인증 시스템이 초기화되지 않았습니다.',
            'authenticated': False
        }), 500
    except Exception as e:
        get_web_logger().error(f"인증 상태 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'인증 상태 조회 실패: {str(e)}',
            'authenticated': False
        }), 500

@app.route('/api/auto-trading/analysis', methods=['POST'])
def get_analysis_result():
    """분석 결과 조회 (테스트용)"""
    try:
        server_type = get_request_server_type()
        engine = get_engine_for(server_type)

        data = request.get_json() or {}
        force_realtime = data.get('force_realtime', True)  # 기본값: 실시간 분석
        
        # 키움 API 인증 상태 확인
        try:
            from src.api.auth import KiwoomAuth
            current_auth = KiwoomAuth(server_type)

            session_authenticated = session.get('authenticated', False)
            token_valid = current_auth.is_token_valid()
            is_authenticated = session_authenticated and token_valid

            if not is_authenticated:
                clear_auth_session()
                return jsonify({
                    'success': False,
                    'message': '키움 API 인증이 필요합니다. 먼저 인증을 완료해주세요.',
                    'error_details': {
                        'error_type': 'auth_required',
                        'timestamp': datetime.now().isoformat()
                    }
                }), 401
        except Exception as e:
            get_web_logger().error(f"인증 상태 확인 실패: {e}")
            return jsonify({
                'success': False,
                'message': f'인증 상태 확인 실패: {str(e)}',
                'error_details': {
                    'error_type': 'auth_check_failed',
                    'timestamp': datetime.now().isoformat()
                }
            }), 500
        
        
        # 분석 실행 (test_mode=True로 호출)
        try:
            trading_data = engine.execute_strategy(test_mode=True)
            if not trading_data.get('success'):
                return jsonify({
                    'success': False,
                    'message': f"분석 실행 실패: {trading_data.get('message', '알 수 없는 오류')}",
                    'error_details': {
                        'error_type': 'analysis_failed',
                        'timestamp': datetime.now().isoformat(),
                        'force_realtime': force_realtime
                    }
                }), 500
            
            analysis_result = trading_data.get('analysis_result')
            account_info = trading_data.get('account_info')
            strategy_params = trading_data.get('strategy_params')
            
        except Exception as e:
            get_web_logger().error(f"분석 실행 중 예외 발생: {e}")
            return jsonify({
                'success': False,
                'message': f"분석 실행 중 오류 발생: {str(e)}",
                'error_details': {
                    'error_type': 'analysis_exception',
                    'timestamp': datetime.now().isoformat(),
                    'force_realtime': force_realtime
                }
            }), 500
        
        if not analysis_result.get('success'):
            error_message = analysis_result.get('message', '알 수 없는 오류')
            get_web_logger().error(f"분석 결과 조회 실패: {error_message}")
            return jsonify({
                'success': False,
                'message': f"분석 실행 실패: {error_message}",
                'error_details': {
                    'error_type': 'analysis_failed',
                    'timestamp': datetime.now().isoformat(),
                    'force_realtime': force_realtime
                }
            }), 400
        
        # 매도/매수 대상 선별 (analysis_result에서 가져오기)
        sell_candidates = []
        buy_candidates = []
        sell_proceeds = 0
        
        try:
            # 매도 대상 선별 (보유종목 기준)
            from src.utils.order_history_manager import OrderHistoryManager
            order_history_manager = OrderHistoryManager(server_type)
            
            # 보유 종목 조회 - 올바른 구조로 수정
            balance_info = account_info.get('balance', {})
            balance_result = balance_info.get('acnt_evlt_remn_indv_tot', [])
            get_web_logger().debug(f"보유종목 조회: {len(balance_result)}개 종목")
            
            if balance_result:
                take_profit_pct = strategy_params.get('take_profit_pct', 5.0)
                stop_loss_pct = strategy_params.get('stop_loss_pct', 3.0)
                max_hold_period = strategy_params.get('max_hold_period', 15)
                
                for stock in balance_result:
                    stock_code = stock.get('stk_cd', '')
                    stock_name = stock.get('stk_nm', '')
                    quantity = int(stock.get('rmnd_qty', 0))
                    avg_price = float(stock.get('pur_pric', 0))
                    current_price = float(stock.get('cur_prc', 0))
                    
                    get_web_logger().debug(f"보유종목 확인: {stock_name}({stock_code}) - 수량:{quantity}, 평균단가:{avg_price}, 현재가:{current_price}")
                    
                    if quantity <= 0 or avg_price <= 0 or current_price <= 0:
                        get_web_logger().debug(f"보유종목 스킵: {stock_name}({stock_code}) - 유효하지 않은 데이터")
                        continue
                    
                    # 매도 조건 확인
                    should_sell = False
                    sell_reason = ""
                    
                    # 익절/손절 조건
                    profit_rate = ((current_price - avg_price) / avg_price) * 100
                    get_web_logger().debug(f"수익률 계산: {stock_name}({stock_code}) - {profit_rate:.1f}% (익절:{take_profit_pct}%, 손절:{stop_loss_pct}%)")
                    
                    if profit_rate >= take_profit_pct:
                        should_sell = True
                        sell_reason = f"익절 ({profit_rate:.1f}%)"
                        get_web_logger().info(f"📈 익절 조건 만족: {stock_name}({stock_code}) - {profit_rate:.1f}%")
                    elif profit_rate <= -stop_loss_pct:
                        should_sell = True
                        sell_reason = f"손절 ({profit_rate:.1f}%)"
                        get_web_logger().info(f"📉 손절 조건 만족: {stock_name}({stock_code}) - {profit_rate:.1f}%")
                    
                    # 보유기간 만료 조건 추가
                    if not should_sell:
                        try:
                            holding_days = order_history_manager.get_holding_period(stock_code, quantity)
                            get_web_logger().debug(f"보유기간 확인: {stock_name}({stock_code}) - {holding_days}일 (최대:{max_hold_period}일)")
                            if holding_days >= max_hold_period:
                                should_sell = True
                                sell_reason = f"보유기간 만료 ({holding_days}일)"
                                get_web_logger().info(f"⏰ 보유기간 만료: {stock_name}({stock_code}) - {holding_days}일")
                        except Exception as holding_error:
                            get_web_logger().warning(f"보유기간 계산 실패 ({stock_code}): {holding_error}")
                    
                    if should_sell:
                        # 매도 예상금액 계산 (수수료 제외)
                        sell_amount = quantity * current_price
                        sell_proceeds += sell_amount
                        
                        # 보유기간 계산
                        holding_days = -1  # 기본값
                        try:
                            holding_days = order_history_manager.get_holding_period(stock_code, quantity)
                        except Exception as holding_error:
                            get_web_logger().warning(f"보유기간 계산 실패 ({stock_code}): {holding_error}")
                        
                        sell_candidates.append({
                            '종목코드': stock_code,
                            '종목명': stock_name,
                            '보유수량': quantity,
                            '평균단가': avg_price,
                            '현재가': current_price,
                            '수익률': profit_rate,
                            '보유기간': holding_days,
                            '매도사유': sell_reason,
                            '매도예상금액': sell_amount
                        })
                        get_web_logger().info(f"✅ 매도 대상 추가: {stock_name}({stock_code}) - {sell_reason}")
                
                get_web_logger().info(f"📉 분석결과확인 테스트: 매도 대상 {len(sell_candidates)}개 종목이 선정되었습니다.")
            
            # 매수 대상 선별 (analysis_result에서 가져오기) - 매도 예정 종목을 상위 매수고려대상에 추가
            # 매도 예정 종목코드에서 A 프리픽스 제거
            clean_sell_candidates = []
            for candidate in sell_candidates:
                stock_code = candidate['종목코드']
                clean_stock_code = stock_code.replace('A', '') if stock_code.startswith('A') else stock_code
                clean_sell_candidates.append(clean_stock_code)
                get_web_logger().debug(f"매도 예정 종목코드 정리: {stock_code} → {clean_stock_code}")
            
            buy_candidates = engine.analyzer.get_top_stocks(
                analysis_result,
                top_n=strategy_params.get('top_n', 5),
                buy_universe_rank=strategy_params.get('buy_universe_rank', 20),
                include_sell_candidates=clean_sell_candidates,  # A 프리픽스 제거된 매도 예정 종목을 매수 대상에 포함
                server_type=server_type
            )
            
            get_web_logger().info(f"📋 분석결과확인 테스트: 매수 대상 {len(buy_candidates)}개 종목이 선정되었습니다.")
            
        except Exception as e:
            get_web_logger().error(f"매도/매수 대상 선별 중 오류 발생: {e}")
            get_web_logger().debug(f"account_info 구조: {list(account_info.keys()) if account_info else 'None'}")
            get_web_logger().debug(f"strategy_params: {strategy_params}")
            import traceback
            get_web_logger().error(f"스택 트레이스: {traceback.format_exc()}")
            sell_candidates = []
            buy_candidates = []
        
        # 💰 사용가능금액 계산 (분석결과확인 테스트용)
        available_cash = 0
        total_deposit = 0
        reserve_cash = 0
        
        try:
            # 예수금 정보 조회 (account_info에서 가져오기) - 기존 로직 복원
            deposit_info = account_info.get('deposit', {})
            if deposit_info:
                # 주문가능금액을 우선적으로 사용 (100stk_ord_alow_amt)
                if '100stk_ord_alow_amt' in deposit_info and deposit_info['100stk_ord_alow_amt'] and deposit_info['100stk_ord_alow_amt'] != '000000000000000':
                    total_deposit = int(deposit_info['100stk_ord_alow_amt'])
                    get_web_logger().info(f"✅ 자동매매 분석: 주문가능금액 사용: {deposit_info['100stk_ord_alow_amt']}")
                # D+2 추정예수금 사용 (주문가능금액이 없는 경우)
                elif 'd2_entra' in deposit_info and deposit_info['d2_entra'] and deposit_info['d2_entra'] != '000000000000000':
                    total_deposit = int(deposit_info['d2_entra'])
                    get_web_logger().info(f"✅ 자동매매 분석: D+2 추정예수금 사용: {deposit_info['d2_entra']}")
                # D+1 추정예수금 사용 (D+2가 없는 경우)
                elif 'd1_entra' in deposit_info and deposit_info['d1_entra'] and deposit_info['d1_entra'] != '000000000000000':
                    total_deposit = int(deposit_info['d1_entra'])
                    get_web_logger().info(f"✅ 자동매매 분석: D+1 추정예수금 사용: {deposit_info['d1_entra']}")
                # 기본 예수금 사용
                elif 'entr' in deposit_info:
                    total_deposit = int(deposit_info['entr'])
                    get_web_logger().info(f"✅ 자동매매 분석: 기본 예수금 사용: {deposit_info['entr']}")
                else:
                    total_deposit = 0
                    get_web_logger().warning("⚠️ 자동매매 분석: 예수금 정보 없음")
                
                reserve_cash = strategy_params.get('reserve_cash', 1000000)
                available_cash = total_deposit + sell_proceeds - reserve_cash
                get_web_logger().info(f"💰 분석결과확인 테스트: 총 예수금: {total_deposit:,}원, 매도 예상금액: {sell_proceeds:,}원, 매매제외예수금: {reserve_cash:,}원, 사용가능현금: {available_cash:,}원")
            else:
                get_web_logger().warning("⚠️ 분석결과확인 테스트: 예수금 정보 조회 실패 - deposit 정보 없음")
                get_web_logger().debug(f"account_info 구조: {list(account_info.keys()) if account_info else 'None'}")
        except Exception as e:
            get_web_logger().error(f"예수금 정보 계산 중 오류 발생: {e}")
            get_web_logger().debug(f"account_info: {account_info}")
        
        # 결과 정리
        result = {
            'success': True,
            'analysis_date': analysis_result['data'].get('analysis_date'),
            'total_stocks': analysis_result['data'].get('total_stocks', 0),
            'top_stocks': analysis_result['data'].get('top_stocks', [])[:20],  # 상위 20개만
            'sell_candidates': sell_candidates,  # 매도 대상 추가
            'buy_candidates': buy_candidates,
            'strategy_params': strategy_params,
            'analysis_result': analysis_result,  # 팝업에서 매매실행 시 사용할 analysis_result 객체 추가
            'cash_info': {
                'current_deposit': total_deposit,
                'sell_proceeds': sell_proceeds,
                'expected_deposit_after_sell': total_deposit + sell_proceeds,
                'reserve_cash': reserve_cash,
                'available_cash': available_cash
            }
        }

        # NaN/Inf가 포함되면 브라우저 JSON 파싱이 깨지므로, 응답 직전 정리
        result = _sanitize_json_value(result)
        return jsonify(result)
        
    except Exception as e:
        get_web_logger().error(f"분석 결과 조회 중 오류: {e}")
        import traceback
        get_web_logger().error(f"스택 트레이스: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'분석 결과 조회 중 오류가 발생했습니다: {str(e)}'
        }), 500

@app.route('/api/auto-trading/execute-with-candidates', methods=['POST'])
def execute_auto_trading_with_candidates():
    """팝업에서 매매실행 버튼 클릭 시 호출"""
    try:
        server_type = get_request_server_type()
        data = request.get_json()
        analysis_result = data.get('analysis_result')
        manual_execution = data.get('manual_execution', True)
        
        if not analysis_result:
            return jsonify({
                'success': False,
                'message': '분석 결과가 지정되지 않았습니다.'
            }), 400
        
        # 자동매매 실행 (analysis_result를 파라미터로 전달)
        result = get_engine_for(server_type).execute_strategy_with_candidates(
            analysis_result=analysis_result,
            manual_execution=manual_execution
        )
        
        return jsonify(result)
        
    except Exception as e:
        get_web_logger().error(f"자동매매 실행 중 오류: {e}")
        return jsonify({
            'success': False,
            'message': f'자동매매 실행 중 오류가 발생했습니다: {str(e)}'
        }), 500

@app.route('/api/auto-trading/stop', methods=['POST'])
def stop_auto_trading():
    """자동매매 긴급 중지"""
    try:
        server_type = get_request_server_type()
        result = get_engine_for(server_type).stop_trading()
        return jsonify(result)
    except Exception as e:
        get_web_logger().error(f"자동매매 중지 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'자동매매 중지 실패: {str(e)}'
        })


@app.route('/api/auto-trading/history')
def get_auto_trading_history():
    """자동매매 실행 이력 조회"""
    try:
        server_type = get_request_server_type()
        days = request.args.get('days', 7, type=int)
        history = get_config_manager_for(server_type).get_execution_history(days)
        return jsonify({
            'success': True,
            'data': history
        })
    except Exception as e:
        get_web_logger().error(f"자동매매 이력 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'이력 조회 실패: {str(e)}'
        })


@socketio.on('connect')
def handle_connect():
    """웹소켓 연결 처리"""
    global is_connected
    is_connected = True
    get_web_logger().info(f"클라이언트 연결: {request.sid}")
    emit('status', {'message': '연결됨', 'timestamp': datetime.now().isoformat()})


@socketio.on('disconnect')
def handle_disconnect():
    """웹소켓 연결 해제 처리"""
    global is_connected
    is_connected = False
    get_web_logger().info(f"클라이언트 연결 해제: {request.sid}")


@socketio.on('subscribe_stock')
def handle_subscribe_stock(data):
    """종목 실시간 데이터 구독"""
    stock_code = data.get('stock_code')
    if stock_code:
        get_web_logger().info(f"종목 구독: {stock_code}")
        emit('subscribed', {'stock_code': stock_code, 'message': '구독됨'})


def start_real_time_updates():
    """실시간 데이터 업데이트 스레드"""
    while True:
        try:
            if is_connected:
                # 실시간 데이터 업데이트 로직
                current_time = datetime.now().isoformat()
                socketio.emit('update', {
                    'timestamp': current_time,
                    'data': real_time_data
                })
            time.sleep(5)  # 5초마다 업데이트
        except Exception as e:
            get_web_logger().error(f"실시간 업데이트 오류: {e}")
            time.sleep(10)


# 전역 변수로 스케줄러 시작 상태 관리
_schedulers_started = False

def start_schedulers():
    """스케줄러 시작 (항상 두 스케줄러 프로세스 생성)"""
    global _schedulers_started
    
    # Werkzeug reloader 환경에서는 메인 프로세스에서만 스케줄러 시작
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' and WEB_DEBUG:
        get_web_logger().info("Werkzeug reloader 환경에서 서브프로세스는 스케줄러를 시작하지 않습니다.")
        return
    
    if _schedulers_started:
        get_web_logger().info("스케줄러가 이미 시작되었습니다. 중복 시작을 방지합니다.")
        return
    
    try:
        # 모의투자 스케줄러 시작 (설정과 관계없이 항상 시작)
        mock_scheduler.start()
        get_web_logger().info("✅ 모의투자 자동매매 스케줄러가 시작되었습니다.")
        
        # 실전투자 스케줄러 시작 (설정과 관계없이 항상 시작)
        real_scheduler.start()
        get_web_logger().info("✅ 실전투자 자동매매 스케줄러가 시작되었습니다.")
        
        _schedulers_started = True
        get_web_logger().info("✅ 자동매매 스케줄러들이 시작되었습니다. (설정파일에 따라 실행 여부 결정)")
            
    except Exception as e:
        get_web_logger().error(f"스케줄러 시작 실패: {e}")

@app.route('/api/server/current')
def get_current_server_info():
    """현재 서버 타입 조회"""
    try:
        server_config = get_current_server_config()
        return jsonify({
            'success': True,
            'server_type': server_config.server_type,
            'server_name': server_config.server_name
        })
    except Exception as e:
        get_web_logger().error(f"서버 정보 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'서버 정보 조회 실패: {str(e)}'
        })


@app.route('/api/test/execute', methods=['POST'])
def execute_api_test():
    """API 테스트 실행"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        data = request.get_json()
        api_id = data.get('api_id')
        params = data.get('params', {})
        
        if not api_id:
            return jsonify({
                'success': False,
                'message': 'API ID가 필요합니다.'
            })
        
        # 현재 계좌 인스턴스 가져오기
        account = get_current_account()
        
        # API ID에 따라 적절한 메서드 호출
        result = None
        
        if api_id == 'kt00001':
            result = account.get_deposit_detail(params.get('qry_tp', '2'))
        elif api_id == 'kt00002':
            result = account.get_daily_estimated_deposit_assets(
                params.get('start_dt', ''),
                params.get('end_dt', '')
            )
        elif api_id == 'kt00003':
            result = account.get_estimated_assets(params.get('qry_tp', '0'))
        elif api_id == 'kt00004':
            result = account.get_account_evaluation(
                params.get('qry_tp', '0'),
                params.get('dmst_stex_tp', 'KRX')
            )
        elif api_id == 'kt00017':
            result = account.get_daily_account_status()
        elif api_id == 'kt00018':
            result = account.get_account_balance_detail(
                params.get('qry_tp', '0'),
                params.get('dmst_stex_tp', 'KRX')
            )
        elif api_id == 'ka10085':
            result = account.get_account_profit_rate(params.get('stex_tp', '0'))
        elif api_id == 'ka10075':
            result = account.get_unexecuted_orders(
                params.get('all_stk_tp', '0'),
                params.get('trde_tp', '0'),
                params.get('stk_cd', ''),
                params.get('stex_tp', 'KRX')
            )
        elif api_id == 'ka10076':
            result = account.get_executed_orders(
                params.get('qry_tp', '0'),
                params.get('sell_tp', '0'),
                params.get('start_dt', ''),
                params.get('end_dt', ''),
                params.get('stex_tp', 'KRX'),
                params.get('stk_cd', ''),
                params.get('fr_ord_no', '')
            )
        elif api_id == 'ka01690':
            result = account.get_daily_balance_profit_rate(params.get('qry_dt', ''))
        elif api_id == 'ka10072':
            result = account.get_realized_profit_by_date(
                params.get('stk_cd', ''),
                params.get('strt_dt', '')
            )
        elif api_id == 'ka10073':
            result = account.get_realized_profit_by_period(
                params.get('stk_cd', ''),
                params.get('strt_dt', ''),
                params.get('end_dt', '')
            )
        elif api_id == 'ka10074':
            result = account.get_daily_realized_profit(
                params.get('strt_dt', ''),
                params.get('end_dt', '')
            )
        elif api_id == 'ka10077':
            result = account.get_daily_realized_profit_detail(
                params.get('stk_cd', '')
            )
        elif api_id == 'ka10170':
            result = account.get_today_trading_diary(
                params.get('base_dt', ''),
                params.get('ottks_tp', '0'),
                params.get('ch_crd_tp', '0')
            )
        elif api_id == 'kt00015':
            result = account.get_trust_overall_trade_history(
                params.get('strt_dt', ''),
                params.get('end_dt', ''),
                params.get('tp', '3'),
                params.get('stk_cd', ''),
                params.get('gds_tp', '1'),
                params.get('dmst_stex_tp', '%')
            )
        elif api_id == 'kt00007':
            result = account.get_executed_orders_history(
                order_date=params.get('ord_dt', ''),
                query_type=params.get('qry_tp', '4'),
                stock_bond_type=params.get('stk_bond_tp', '1'),
                sell_type=params.get('sell_tp', '0'),
                stock_code=params.get('stk_cd', ''),
                from_order_no=params.get('fr_ord_no', ''),
                exchange=params.get('dmst_stex_tp', '%')
            )
        elif api_id == 'kt00009':
            result = account.get_order_status(
                params.get('strt_dt', ''),
                params.get('end_dt', ''),
                params.get('qry_tp', '0'),
                params.get('sell_tp', '0'),
                params.get('stk_cd', ''),
                params.get('fr_ord_no', ''),
                params.get('mrkt_tp', '0'),
                params.get('dmst_stex_tp', 'KRX')
            )
        elif api_id == 'kt00010':
            result = account.get_order_possible_amount(
                params.get('stk_cd', ''),
                params.get('uv', ''),
                params.get('trde_qty', '')
            )
        else:
            return jsonify({
                'success': False,
                'message': f'지원하지 않는 API ID: {api_id}'
            })
        
        if result:
            return jsonify({
                'success': True,
                'data': result,
                'api_id': api_id,
                'params': params
            })
        else:
            return jsonify({
                'success': False,
                'message': 'API 호출 결과가 없습니다.',
                'api_id': api_id,
                'params': params
            })
            
    except Exception as e:
        get_web_logger().error(f"API 테스트 실행 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'API 테스트 실행 실패: {str(e)}',
            'api_id': data.get('api_id') if 'data' in locals() else None,
            'params': data.get('params') if 'data' in locals() else {}
        })


if __name__ == '__main__':
    # 실시간 업데이트 스레드 시작
    update_thread = threading.Thread(target=start_real_time_updates, daemon=True)
    update_thread.start()
    
    # 스케줄러 시작
    start_schedulers()
    
    # 포트 충돌 시 7000~7999 범위에서 자동 선택 (브라우저 unsafe port 이슈 회피)
    try:
        run_port = _pick_available_port(WEB_HOST, start_port=WEB_PORT, end_port=7999)
    except Exception as e:
        get_web_logger().error(f"웹 서버 포트 선택 실패: {e}")
        raise

    if run_port != WEB_PORT:
        get_web_logger().warning(f"기본 포트 {WEB_PORT}가 사용 중이라 {run_port}로 변경하여 실행합니다.")

    get_web_logger().info(f"웹 서버 시작: http://{WEB_HOST}:{run_port}")
    socketio.run(app, host=WEB_HOST, port=run_port, debug=WEB_DEBUG)
