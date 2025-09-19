# -*- coding: utf-8 -*-
"""
키움 자동매매 웹 대시보드 메인 애플리케이션
"""
import sys
import os
import io

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'

from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import json
from datetime import datetime, timedelta
from src.config.settings import WEB_HOST, WEB_PORT, WEB_DEBUG, SECRET_KEY, SESSION_TIMEOUT
from src.config.server_config import set_server_type, get_current_server_config
from src.utils import get_web_logger
# 캐시 모듈 제거됨
from src.api import kiwoom_auth, kiwoom_account, kiwoom_quote, kiwoom_order, mock_account, real_account, mock_quote, real_quote, mock_order, real_order
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


@app.route('/')
def index():
    """메인 대시보드 페이지"""
    # 현재 서버 설정 로드
    server_info = get_server_info()
    return render_template('dashboard.html', server_info=server_info)


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
        server_type = get_current_server()
        get_web_logger().info(f"로그인 시도 - 현재 서버: {server_type}")
        
        from src.api.auth import KiwoomAuth
        current_auth = KiwoomAuth(server_type)
        get_web_logger().info(f"로그인 시도 - {server_type} 서버용 인증 인스턴스 생성")
        token = current_auth.get_access_token(force_refresh=True)
        if token:
            session['authenticated'] = True
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
            current_auth.revoke_token()
        
        session.clear()
        get_web_logger().info("사용자 로그아웃")
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
    server_type = get_current_server()  # 전역 설정에서 서버 타입 가져오기
    
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
            
            # D+2 추정예수금이 있으면 더 정확한 현재 예수금으로 사용 (모든 서버 공통)
            if 'd2_entra' in result and result['d2_entra'] and result['d2_entra'] != '000000000000000':
                result['entr'] = result['d2_entra']
                get_web_logger().info(f"D+2 추정예수금 사용: {result['d2_entra']}")
            # D+1 추정예수금이 있으면 사용 (D+2가 없는 경우)
            elif 'd1_entra' in result and result['d1_entra'] and result['d1_entra'] != '000000000000000':
                result['entr'] = result['d1_entra']
                get_web_logger().info(f"D+1 추정예수금 사용: {result['d1_entra']}")
            
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
                combined_data['stk_acnt_evlt_prst'] = evaluation_result['stk_acnt_evlt_prst']
            
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
            start_date=order_date,
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
        result = get_current_account().get_today_trading_diary()
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
    """일별 매매일지 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 체결 내역을 기반으로 일별 매매일지 생성
        result = get_current_account().get_executed_orders(
            query_type="0",
            sell_type="0", 
            start_date=start_date,
            end_date=end_date,
            exchange="KRX"
        )
        
        if result and result.get('cntr'):
            # 일별로 그룹화하여 매매일지 생성
            daily_trades = {}
            for trade in result['cntr']:
                trade_date = trade.get('cntr_dt', '')
                if trade_date not in daily_trades:
                    daily_trades[trade_date] = {
                        'trade_date': trade_date,
                        'trade_count': 0,
                        'buy_amount': 0,
                        'sell_amount': 0,
                        'commission': 0,
                        'tax': 0,
                        'profit_amount': 0,
                        'return_rate': 0
                    }
                
                daily_trades[trade_date]['trade_count'] += 1
                daily_trades[trade_date]['commission'] += float(trade.get('cmsn', '0'))
                daily_trades[trade_date]['tax'] += float(trade.get('tax', '0'))
                
                if trade.get('sell_tp') == '1':  # 매도
                    daily_trades[trade_date]['sell_amount'] += float(trade.get('cntr_amt', '0'))
                else:  # 매수
                    daily_trades[trade_date]['buy_amount'] += float(trade.get('cntr_amt', '0'))
            
            # 손익 계산
            for date, data in daily_trades.items():
                data['profit_amount'] = data['sell_amount'] - data['buy_amount'] - data['commission'] - data['tax']
                if data['buy_amount'] > 0:
                    data['return_rate'] = (data['profit_amount'] / data['buy_amount'] * 100)
            
            return jsonify({
                'success': True,
                'data': {
                    'daily_trades': list(daily_trades.values())
                }
            })
        else:
            return jsonify({
                'success': True,
                'data': {
                    'daily_trades': []
                }
            })
    except Exception as e:
        get_web_logger().error(f"일별 매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'일별 매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/monthly')
def get_monthly_trading():
    """월별 매매일지 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=365)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 체결 내역을 기반으로 월별 매매일지 생성
        result = get_current_account().get_executed_orders(
            query_type="0",
            sell_type="0", 
            start_date=start_date,
            end_date=end_date,
            exchange="KRX"
        )
        
        if result and result.get('cntr'):
            # 월별로 그룹화하여 매매일지 생성
            monthly_trades = {}
            for trade in result['cntr']:
                trade_date = trade.get('cntr_dt', '')
                if len(trade_date) >= 6:
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
                    
                    monthly_trades[month_key]['trade_count'] += 1
                    monthly_trades[month_key]['commission'] += float(trade.get('cmsn', '0'))
                    monthly_trades[month_key]['tax'] += float(trade.get('tax', '0'))
                    
                    if trade.get('sell_tp') == '1':  # 매도
                        monthly_trades[month_key]['sell_amount'] += float(trade.get('cntr_amt', '0'))
                    else:  # 매수
                        monthly_trades[month_key]['buy_amount'] += float(trade.get('cntr_amt', '0'))
            
            # 손익 계산
            for month, data in monthly_trades.items():
                data['profit_amount'] = data['sell_amount'] - data['buy_amount'] - data['commission'] - data['tax']
                if data['buy_amount'] > 0:
                    data['return_rate'] = (data['profit_amount'] / data['buy_amount'] * 100)
            
            return jsonify({
                'success': True,
                'data': {
                    'monthly_trades': list(monthly_trades.values())
                }
            })
        else:
            return jsonify({
                'success': True,
                'data': {
                    'monthly_trades': []
                }
            })
    except Exception as e:
        get_web_logger().error(f"월별 매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'월별 매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/analysis')
def get_trading_analysis():
    """매매 분석 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 체결 내역을 기반으로 분석 데이터 생성
        result = get_current_account().get_executed_orders(
            query_type="0",
            sell_type="0", 
            start_date=start_date,
            end_date=end_date,
            exchange="KRX"
        )
        
        if result and result.get('cntr'):
            # 종목별 분석
            stock_analysis = {}
            profit_trend = {}
            pattern_analysis = {'profit_count': 0, 'loss_count': 0}
            
            for trade in result['cntr']:
                stock_code = trade.get('stk_cd', '')
                stock_name = trade.get('stk_nm', '')
                trade_date = trade.get('cntr_dt', '')
                
                if stock_code not in stock_analysis:
                    stock_analysis[stock_code] = {
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'trade_count': 0,
                        'total_profit': 0,
                        'avg_return': 0,
                        'win_rate': 0,
                        'max_profit': 0,
                        'max_loss': 0,
                        'profits': []
                    }
                
                # 거래 정보 업데이트
                stock_analysis[stock_code]['trade_count'] += 1
                profit = float(trade.get('pl_amt', '0'))
                stock_analysis[stock_code]['total_profit'] += profit
                stock_analysis[stock_code]['profits'].append(profit)
                
                if profit > 0:
                    pattern_analysis['profit_count'] += 1
                    stock_analysis[stock_code]['max_profit'] = max(stock_analysis[stock_code]['max_profit'], profit)
                else:
                    pattern_analysis['loss_count'] += 1
                    stock_analysis[stock_code]['max_loss'] = min(stock_analysis[stock_code]['max_loss'], profit)
                
                # 수익률 추이
                if trade_date not in profit_trend:
                    profit_trend[trade_date] = 0
                profit_trend[trade_date] += profit
            
            # 종목별 통계 계산
            for stock_code, data in stock_analysis.items():
                if data['trade_count'] > 0:
                    data['avg_return'] = data['total_profit'] / data['trade_count']
                    win_count = sum(1 for p in data['profits'] if p > 0)
                    data['win_rate'] = (win_count / data['trade_count'] * 100) if data['trade_count'] > 0 else 0
            
            # 수익률 추이 정렬
            profit_trend_list = [{'date': date, 'cumulative_profit': sum(profit_trend[d] for d in profit_trend if d <= date)} 
                                for date in sorted(profit_trend.keys())]
            
            return jsonify({
                'success': True,
                'data': {
                    'stock_analysis': list(stock_analysis.values()),
                    'profit_trend': profit_trend_list,
                    'pattern_analysis': pattern_analysis
                }
            })
        else:
            return jsonify({
                'success': True,
                'data': {
                    'stock_analysis': [],
                    'profit_trend': [],
                    'pattern_analysis': {'profit_count': 0, 'loss_count': 0}
                }
            })
    except Exception as e:
        get_web_logger().error(f"매매 분석 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'매매 분석 조회 실패: {str(e)}'
        })


@app.route('/api/cache/clear')
def clear_cache():
    """API 캐시 클리어 (캐시 비활성화로 인해 더 이상 사용되지 않음)"""
    return jsonify({
        'success': True,
        'message': '캐시가 비활성화되어 있습니다. 모든 API 호출은 실시간으로 처리됩니다.'
    })


@app.route('/api/account/trading/daily/<trade_date>')
def get_daily_trading_detail(trade_date):
    """특정 날짜의 매매 상세 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        result = get_current_account().get_executed_orders(
            query_type="0",
            sell_type="0", 
            start_date=trade_date,
            end_date=trade_date,
            exchange="KRX"
        )
        
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '해당 날짜의 매매 내역이 없습니다.'
            })
    except Exception as e:
        get_web_logger().error(f"일별 매매 상세 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'일별 매매 상세 조회 실패: {str(e)}'
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
        
        result = get_current_order().cancel_order(order_no, stock_code, quantity)
        
        if result:
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
            error_response = create_error_response("2000", "주문 취소 처리 중 오류가 발생했습니다.", "cancel_order")
            return jsonify(error_response)
            
    except Exception as e:
        get_web_logger().error(f"주문 취소 실패: {e}")
        error_response = create_error_response("2000", f"주문 취소 실패: {str(e)}", "cancel_order")
        return jsonify(error_response)


# 자동매매 API 엔드포인트들
@app.route('/api/auto-trading/config')
def get_auto_trading_config():
    """자동매매 설정 조회"""
    try:
        config = get_current_config_manager().load_config()
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
        config = request.get_json()
        if get_current_config_manager().save_config(config):
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
        config = get_current_config_manager().load_config()
        last_execution = get_current_config_manager().get_last_execution_time()
        today_executed = get_current_config_manager().is_today_executed()
        
        # 실행 상태 조회
        execution_status = get_current_engine().get_execution_status()
        
        return jsonify({
            'success': True,
            'data': {
                'enabled': config.get('auto_trading_enabled', False),
                'last_execution': last_execution,
                'today_executed': today_executed,
                'is_running': execution_status['is_running'],
                'current_status': execution_status['current_status'],
                'progress_percentage': execution_status['progress_percentage'],
                'last_check_time': mock_scheduler.get_last_check_time()
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
        result = get_current_engine().execute_strategy(manual_execution=True)
        
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
        server_type = get_current_server()
        get_web_logger().info(f"인증 상태 확인 - 현재 서버: {server_type}")
        
        # 현재 서버에 맞는 인증 인스턴스 사용
        from src.api.auth import KiwoomAuth
        current_auth = KiwoomAuth(server_type)
        get_web_logger().info(f"인증 상태 확인 - {server_type} 서버용 인증 인스턴스 사용")
        
        # 토큰 유효성 확인 (토큰 파일 기반)
        is_authenticated = current_auth.is_authenticated()
        get_web_logger().info(f"토큰 파일 기반 인증 상태: {is_authenticated}")
        
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
        data = request.get_json()
        force_realtime = data.get('force_realtime', True)  # 기본값: 실시간 분석
        
        # 키움 API 인증 상태 확인
        try:
            if not kiwoom_auth.is_authenticated():
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
        
        # 분석 실행
        try:
            analysis_result = get_current_engine().analyzer.get_stock_analysis(force_realtime=force_realtime)
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
        
        # 매도 대상 선정
        sell_candidates = []
        try:
            from src.api.account import KiwoomAccount
            from src.utils.server_manager import get_current_server
            
            # 현재 서버 타입에 맞는 API 인스턴스 사용
            server_type = get_current_server()
            account = KiwoomAccount(server_type)
            
            # 보유 종목 조회
            balance_result = account.get_account_balance_detail()
            
            if balance_result and balance_result.get('success') and balance_result.get('acnt_evlt_remn_indv_tot'):
                config = get_current_config_manager().load_config()
                strategy_params = config.get('strategy_params', {})
                
                take_profit_pct = strategy_params.get('take_profit_pct', 5.0)
                stop_loss_pct = strategy_params.get('stop_loss_pct', 3.0)
                max_hold_period = strategy_params.get('max_hold_period', 15)
                
                for stock in balance_result['acnt_evlt_remn_indv_tot']:
                    stock_code = stock.get('stk_cd', '')
                    stock_name = stock.get('stk_nm', '')
                    quantity = int(stock.get('rmnd_qty', 0))
                    avg_price = float(stock.get('pur_pric', 0))
                    current_price = float(stock.get('cur_prc', 0))
                    
                    if quantity <= 0 or avg_price <= 0 or current_price <= 0:
                        continue
                    
                    # 매도 조건 확인
                    should_sell = False
                    sell_reason = ""
                    
                    # 익절/손절 조건
                    profit_rate = ((current_price - avg_price) / avg_price) * 100
                    if profit_rate >= take_profit_pct:
                        should_sell = True
                        sell_reason = f"익절 ({profit_rate:.1f}%)"
                    elif profit_rate <= -stop_loss_pct:
                        should_sell = True
                        sell_reason = f"손절 ({profit_rate:.1f}%)"
                    
                    if should_sell:
                        # 매도 예상금액 계산 (수수료 제외)
                        sell_amount = quantity * current_price
                        sell_proceeds += sell_amount
                        
                        sell_candidates.append({
                            '종목코드': stock_code,
                            '종목명': stock_name,
                            '보유수량': quantity,
                            '평균단가': avg_price,
                            '현재가': current_price,
                            '수익률': profit_rate,
                            '매도사유': sell_reason,
                            '매도예상금액': sell_amount
                        })
            
            get_web_logger().info(f"📉 분석결과확인 테스트: 매도 대상 {len(sell_candidates)}개 종목이 선정되었습니다.")
            
        except Exception as e:
            get_web_logger().error(f"매도 대상 선정 중 오류 발생: {e}")
            sell_candidates = []
        
        # 매수 대상 선정 (매도 후 확보된 현금 고려)
        try:
            config = get_current_config_manager().load_config()
            strategy_params = config.get('strategy_params', {})
            
            buy_candidates = get_current_engine().analyzer.get_top_stocks(
                analysis_result,
                top_n=strategy_params.get('top_n', 5),
                buy_universe_rank=strategy_params.get('buy_universe_rank', 20)
            )
            
            # get_top_stocks() 함수에서 이미 보유종목이 제외되어 반환됨
            get_web_logger().info(f"📋 분석결과확인 테스트: 매수 대상 {len(buy_candidates)}개 종목이 선정되었습니다.")
            
        except Exception as e:
            get_web_logger().error(f"매수 대상 선정 중 오류 발생: {e}")
            buy_candidates = []  # 빈 리스트로 설정하여 계속 진행
        
        # 💰 사용가능금액 계산 (분석결과확인 테스트용)
        # 매도 후 예수금을 고려한 계산
        available_cash = 0
        total_deposit = 0
        reserve_cash = 0
        sell_proceeds = 0  # 매도로 확보될 예상 현금
        
        try:
            from src.api.account import KiwoomAccount
            from src.utils.server_manager import get_current_server
            
            # 현재 서버 타입에 맞는 API 인스턴스 사용
            server_type = get_current_server()
            account = KiwoomAccount(server_type)
            
            # 예수금 정보 조회 (대시보드와 동일한 로직 사용)
            deposit_result = account.get_deposit_detail()
            
            if deposit_result and deposit_result.get('success') is not False:
                # 서버별 분기처리 (대시보드와 동일)
                server_config = get_current_server_config_instance()
                
                if server_config.is_real_server():
                    # 운영서버: kt00002로 최신 예수금 정보 확인
                    today = datetime.now().strftime('%Y%m%d')
                    
                    try:
                        daily_result = account.get_daily_estimated_deposit_assets(today, today)
                        if daily_result and daily_result.get('daly_prsm_dpst_aset_amt_prst'):
                            # 오늘 날짜의 예수금 정보가 있으면 사용
                            today_data = daily_result['daly_prsm_dpst_aset_amt_prst'][0]
                            if 'entr' in today_data:
                                deposit_result['entr'] = today_data['entr']
                                get_web_logger().info(f"운영서버 kt00002에서 최신 예수금 정보 사용: {today_data['entr']}")
                    except Exception as e:
                        get_web_logger().warning(f"운영서버 kt00002 조회 실패, kt00001 결과 사용: {e}")
                        get_web_logger().info("🔄 kt00002 실패로 인해 kt00001 예수금 정보로 대체 호출합니다")
                
                # D+2 추정예수금이 있으면 더 정확한 현재 예수금으로 사용 (모든 서버 공통)
                if 'd2_entra' in deposit_result and deposit_result['d2_entra'] and deposit_result['d2_entra'] != '000000000000000':
                    deposit_result['entr'] = deposit_result['d2_entra']
                    get_web_logger().info(f"D+2 추정예수금 사용: {deposit_result['d2_entra']}")
                # D+1 추정예수금이 있으면 사용 (D+2가 없는 경우)
                elif 'd1_entra' in deposit_result and deposit_result['d1_entra'] and deposit_result['d1_entra'] != '000000000000000':
                    deposit_result['entr'] = deposit_result['d1_entra']
                    get_web_logger().info(f"D+1 추정예수금 사용: {deposit_result['d1_entra']}")
                
                # 예수금 계산 (매도 후 예상금액 반영) - d2_entra 또는 d1_entra 사용
                total_deposit = int(deposit_result.get('entr', 0))
                reserve_cash = strategy_params.get('reserve_cash', 1000000)
                
                # 매도 후 예상 예수금 = 현재 예수금 + 매도 예상금액
                expected_deposit_after_sell = total_deposit + sell_proceeds
                available_cash = expected_deposit_after_sell - reserve_cash
                
                get_web_logger().info(f"💰 분석결과확인 테스트 - 현재 예수금: {total_deposit:,}원")
                get_web_logger().info(f"💰 매도 예상금액: {sell_proceeds:,}원")
                get_web_logger().info(f"💰 매도 후 예상 예수금: {expected_deposit_after_sell:,}원")
                get_web_logger().info(f"💰 매매제외예수금: {reserve_cash:,}원")
                get_web_logger().info(f"💰 매도 후 사용가능금액: {available_cash:,}원")
            else:
                # 상세한 오류 정보 로그
                if deposit_result:
                    error_msg = deposit_result.get('message', '알 수 없는 오류')
                    error_code = deposit_result.get('error_code', 'UNKNOWN')
                    full_response = deposit_result.get('full_response', {})
                    get_web_logger().warning(f"예수금 정보 조회 실패: [{error_code}] {error_msg}")
                    get_web_logger().warning(f"전체 API 응답: {full_response}")
                else:
                    get_web_logger().warning("예수금 정보 조회 결과가 None입니다.")
                
        except Exception as cash_error:
            get_web_logger().warning(f"사용가능금액 계산 중 오류 발생: {cash_error}")
        
        # 결과 정리
        result = {
            'success': True,
            'analysis_date': analysis_result['data'].get('analysis_date'),
            'total_stocks': analysis_result['data'].get('total_stocks', 0),
            'top_stocks': analysis_result['data'].get('top_stocks', [])[:20],  # 상위 20개만
            'sell_candidates': sell_candidates,  # 매도 대상 추가
            'buy_candidates': buy_candidates,
            'strategy_params': strategy_params,
            'cash_info': {
                'current_deposit': total_deposit,
                'sell_proceeds': sell_proceeds,
                'expected_deposit_after_sell': total_deposit + sell_proceeds,
                'reserve_cash': reserve_cash,
                'available_cash': available_cash
            }
        }
        
        return jsonify(result)
        
    except Exception as e:
        get_web_logger().error(f"분석 결과 조회 중 오류: {e}")
        return jsonify({
            'success': False,
            'message': f'분석 결과 조회 중 오류가 발생했습니다: {str(e)}'
        }), 500

@app.route('/api/auto-trading/execute-with-candidates', methods=['POST'])
def execute_auto_trading_with_candidates():
    """선정된 매수 대상으로 자동매매 실행 (테스트용)"""
    try:
        data = request.get_json()
        buy_candidates = data.get('buy_candidates', [])
        manual_execution = data.get('manual_execution', True)
        
        if not buy_candidates:
            return jsonify({
                'success': False,
                'message': '매수 대상이 지정되지 않았습니다.'
            }), 400
        
        # 자동매매 실행 (매수 대상 미리 선정된 상태)
        result = get_current_engine().execute_strategy_with_candidates(
            buy_candidates=buy_candidates,
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
        result = get_current_engine().stop_trading()
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
        days = request.args.get('days', 7, type=int)
        history = get_current_config_manager().get_execution_history(days)
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

if __name__ == '__main__':
    # 실시간 업데이트 스레드 시작
    update_thread = threading.Thread(target=start_real_time_updates, daemon=True)
    update_thread.start()
    
    # 스케줄러 시작
    start_schedulers()
    
    get_web_logger().info(f"웹 서버 시작: http://{WEB_HOST}:{WEB_PORT}")
    socketio.run(app, host=WEB_HOST, port=WEB_PORT, debug=WEB_DEBUG)
