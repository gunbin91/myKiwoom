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
from src.config import WEB_HOST, WEB_PORT, WEB_DEBUG, SECRET_KEY, SESSION_TIMEOUT
from src.utils import web_logger
from src.utils.cache import api_cache
from src.api import kiwoom_auth, kiwoom_account, kiwoom_quote, kiwoom_order
from src.auto_trading.config_manager import config_manager
from src.auto_trading.engine import auto_trading_engine
from src.auto_trading.scheduler import auto_trading_scheduler
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

# Flask 로깅 레벨 설정 (INFO 레벨로 설정하여 일반적인 요청 로그는 숨김)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

# Flask 애플리케이션 로깅 레벨도 조정
app.logger.setLevel(logging.WARNING)

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
    return render_template('dashboard.html')


@app.route('/portfolio')
def portfolio():
    """포트폴리오 페이지"""
    return render_template('portfolio.html')


@app.route('/orders')
def orders():
    """주문내역 페이지"""
    return render_template('orders.html')


@app.route('/trading-diary')
def trading_diary():
    """매매일지 페이지"""
    return render_template('trading_diary.html')


@app.route('/auto-trading')
def auto_trading():
    """자동매매 페이지"""
    return render_template('auto_trading.html')


@app.route('/api/auth/status')
def auth_status():
    """인증 상태 확인"""
    try:
        # 세션과 토큰 상태를 모두 확인
        session_authenticated = session.get('authenticated', False)
        token_valid = kiwoom_auth.is_token_valid()
        
        # 둘 다 유효해야 인증된 것으로 간주
        is_authenticated = session_authenticated and token_valid
        
        # 세션과 토큰 상태가 다르면 세션을 정리
        if session_authenticated and not token_valid:
            session.clear()
            web_logger.info("토큰이 무효화되어 세션을 정리했습니다.")
        
        return jsonify({
            'success': True,
            'authenticated': is_authenticated,
            'message': '인증됨' if is_authenticated else '인증 필요'
        })
    except Exception as e:
        web_logger.error(f"인증 상태 확인 실패: {e}")
        return jsonify({
            'success': False,
            'authenticated': False,
            'message': f'오류: {str(e)}'
        })


@app.route('/api/auth/login', methods=['POST'])
def login():
    """OAuth 인증 로그인"""
    try:
        token = kiwoom_auth.get_access_token(force_refresh=True)
        if token:
            session['authenticated'] = True
            session['login_time'] = datetime.now().isoformat()
            web_logger.info("사용자 로그인 성공")
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
        web_logger.error(f"로그인 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'로그인 실패: {str(e)}'
        })


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """로그아웃"""
    try:
        kiwoom_auth.revoke_token()
        session.clear()
        web_logger.info("사용자 로그아웃")
        return jsonify({
            'success': True,
            'message': '로그아웃 성공'
        })
    except Exception as e:
        web_logger.error(f"로그아웃 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'로그아웃 실패: {str(e)}'
        })


def check_auth():
    """인증 상태 체크 데코레이터"""
    session_authenticated = session.get('authenticated', False)
    token_valid = kiwoom_auth.is_token_valid()
    
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
        result = kiwoom_account.get_deposit_detail()
        if result and result.get('success') is not False:
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
        web_logger.error(f"예수금 조회 실패: {e}")
        error_response = create_error_response("2000", f"예수금 조회 실패: {str(e)}", "get_deposit")
        return jsonify(error_response)


@app.route('/api/account/assets')
def get_assets():
    """추정자산 조회"""
    auth_ok, error_response = check_auth()
    if not auth_ok:
        return error_response
    
    try:
        result = kiwoom_account.get_estimated_assets()
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
        web_logger.error(f"자산 조회 실패: {e}")
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
        result = kiwoom_account.get_account_evaluation()
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '계좌 평가 정보 조회 실패'
            })
    except Exception as e:
        web_logger.error(f"계좌 평가 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'계좌 평가 조회 실패: {str(e)}'
        })


@app.route('/api/account/balance')
def get_balance():
    """계좌 잔고 내역 조회"""
    try:
        result = kiwoom_account.get_account_balance_detail()
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
        web_logger.error(f"잔고 조회 실패: {e}")
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
        result = kiwoom_account.get_unexecuted_orders()
        if result:
            return jsonify({
                'success': True,
                'data': result
            })
        else:
            return jsonify({
                'success': False,
                'message': '미체결 주문 조회 실패'
            })
    except Exception as e:
        web_logger.error(f"미체결 주문 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'미체결 주문 조회 실패: {str(e)}'
        })


@app.route('/api/account/orders/executed')
def get_executed_orders():
    """체결 주문 조회"""
    try:
        # 쿼리 파라미터에서 날짜 범위 가져오기
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=7)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        result = kiwoom_account.get_executed_orders(
            query_type="0",
            sell_type="0", 
            start_date=start_date,
            end_date=end_date,
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
                'message': '체결 주문 조회 실패'
            })
    except Exception as e:
        web_logger.error(f"체결 주문 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'체결 주문 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading-diary')
def get_trading_diary():
    """당일 매매일지 조회"""
    try:
        result = kiwoom_account.get_today_trading_diary()
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
        web_logger.error(f"매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/daily')
def get_daily_trading():
    """일별 매매일지 조회"""
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 체결 내역을 기반으로 일별 매매일지 생성
        result = kiwoom_account.get_executed_orders(
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
        web_logger.error(f"일별 매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'일별 매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/monthly')
def get_monthly_trading():
    """월별 매매일지 조회"""
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=365)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 체결 내역을 기반으로 월별 매매일지 생성
        result = kiwoom_account.get_executed_orders(
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
        web_logger.error(f"월별 매매일지 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'월별 매매일지 조회 실패: {str(e)}'
        })


@app.route('/api/account/trading/analysis')
def get_trading_analysis():
    """매매 분석 조회"""
    try:
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y%m%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y%m%d'))
        
        # 체결 내역을 기반으로 분석 데이터 생성
        result = kiwoom_account.get_executed_orders(
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
        web_logger.error(f"매매 분석 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'매매 분석 조회 실패: {str(e)}'
        })


@app.route('/api/cache/clear')
def clear_cache():
    """API 캐시 클리어"""
    try:
        api_cache.clear()
        return jsonify({
            'success': True,
            'message': '캐시가 성공적으로 클리어되었습니다.'
        })
    except Exception as e:
        web_logger.error(f"캐시 클리어 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'캐시 클리어 실패: {str(e)}'
        })


@app.route('/api/account/trading/daily/<trade_date>')
def get_daily_trading_detail(trade_date):
    """특정 날짜의 매매 상세 조회"""
    try:
        result = kiwoom_account.get_executed_orders(
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
        web_logger.error(f"일별 매매 상세 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'일별 매매 상세 조회 실패: {str(e)}'
        })


@app.route('/api/quote/stock/<stock_code>')
def get_stock_info(stock_code):
    """종목 정보 조회"""
    try:
        result = kiwoom_quote.get_stock_info(stock_code)
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
        web_logger.error(f"종목 정보 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'종목 정보 조회 실패: {str(e)}'
        })


@app.route('/api/quote/price/<stock_code>')
def get_stock_price(stock_code):
    """주식 호가 조회"""
    try:
        result = kiwoom_quote.get_stock_quote(stock_code)
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
        web_logger.error(f"주식 호가 조회 실패: {e}")
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
            result = kiwoom_quote.get_stock_daily_chart(stock_code, start_date, end_date)
        elif period == 'W':
            result = kiwoom_quote.get_stock_weekly_chart(stock_code, start_date, end_date)
        elif period == 'M':
            result = kiwoom_quote.get_stock_monthly_chart(stock_code, start_date, end_date)
        else:
            result = kiwoom_quote.get_stock_daily_chart(stock_code, start_date, end_date)
        
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
        web_logger.error(f"차트 데이터 조회 실패: {e}")
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
        
        result = kiwoom_order.buy_stock(stock_code, quantity, price, order_type)
        
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
        web_logger.error(f"매수 주문 실패: {e}")
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
        
        result = kiwoom_order.sell_stock(stock_code, quantity, price, order_type)
        
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
        web_logger.error(f"매도 주문 실패: {e}")
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
        
        result = kiwoom_order.cancel_order(order_no, stock_code, quantity)
        
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
        web_logger.error(f"주문 취소 실패: {e}")
        error_response = create_error_response("2000", f"주문 취소 실패: {str(e)}", "cancel_order")
        return jsonify(error_response)


# 자동매매 API 엔드포인트들
@app.route('/api/auto-trading/config')
def get_auto_trading_config():
    """자동매매 설정 조회"""
    try:
        config = config_manager.load_config()
        return jsonify({
            'success': True,
            'data': config
        })
    except Exception as e:
        web_logger.error(f"자동매매 설정 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'설정 조회 실패: {str(e)}'
        })


@app.route('/api/auto-trading/config', methods=['POST'])
def save_auto_trading_config():
    """자동매매 설정 저장"""
    try:
        config = request.get_json()
        if config_manager.save_config(config):
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
        web_logger.error(f"자동매매 설정 저장 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'설정 저장 실패: {str(e)}'
        })


@app.route('/api/auto-trading/status')
def get_auto_trading_status():
    """자동매매 상태 조회"""
    try:
        config = config_manager.load_config()
        last_execution = config_manager.get_last_execution_time()
        today_executed = config_manager.is_today_executed()
        
        # 실행 상태 조회
        execution_status = auto_trading_engine.get_execution_status()
        
        return jsonify({
            'success': True,
            'data': {
                'enabled': config.get('auto_trading_enabled', False),
                'last_execution': last_execution,
                'today_executed': today_executed,
                'is_running': execution_status['is_running'],
                'current_status': execution_status['current_status'],
                'progress_percentage': execution_status['progress_percentage'],
                'last_check_time': auto_trading_scheduler.get_last_check_time()
            }
        })
    except Exception as e:
        web_logger.error(f"자동매매 상태 조회 실패: {e}")
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
        result = auto_trading_engine.execute_strategy(manual_execution=True)
        
        if result['success']:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 자동매매 실행 성공: {result['message']}")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 자동매매 실행 실패: {result['message']}")
        
        return jsonify(result)
    except Exception as e:
        from datetime import datetime
        error_message = f'자동매매 실행 실패: {str(e)}'
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ {error_message}")
        web_logger.error(f"자동매매 실행 실패: {e}")
        return jsonify({
            'success': False,
            'message': error_message
        })


@app.route('/api/auto-trading/analysis', methods=['POST'])
def get_analysis_result():
    """분석 결과 조회 (테스트용)"""
    try:
        data = request.get_json()
        force_realtime = data.get('force_realtime', True)  # 기본값: 실시간 분석
        
        # 분석 실행
        analysis_result = auto_trading_engine.analyzer.get_stock_analysis(force_realtime=force_realtime)
        
        if not analysis_result.get('success'):
            return jsonify({
                'success': False,
                'message': f"분석 실행 실패: {analysis_result.get('message', '알 수 없는 오류')}"
            }), 400
        
        # 매수 대상 선정
        config = config_manager.load_config()
        strategy_params = config.get('strategy_params', {})
        
        buy_candidates = auto_trading_engine.analyzer.get_top_stocks(
            analysis_result,
            top_n=strategy_params.get('top_n', 5),
            buy_universe_rank=strategy_params.get('buy_universe_rank', 20)
        )
        
        # 결과 정리
        result = {
            'success': True,
            'analysis_date': analysis_result['data'].get('analysis_date'),
            'total_stocks': analysis_result['data'].get('total_stocks', 0),
            'top_stocks': analysis_result['data'].get('top_stocks', [])[:20],  # 상위 20개만
            'buy_candidates': buy_candidates,
            'strategy_params': strategy_params
        }
        
        return jsonify(result)
        
    except Exception as e:
        web_logger.error(f"분석 결과 조회 중 오류: {e}")
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
        result = auto_trading_engine.execute_strategy_with_candidates(
            buy_candidates=buy_candidates,
            manual_execution=manual_execution
        )
        
        return jsonify(result)
        
    except Exception as e:
        web_logger.error(f"자동매매 실행 중 오류: {e}")
        return jsonify({
            'success': False,
            'message': f'자동매매 실행 중 오류가 발생했습니다: {str(e)}'
        }), 500

@app.route('/api/auto-trading/stop', methods=['POST'])
def stop_auto_trading():
    """자동매매 긴급 중지"""
    try:
        result = auto_trading_engine.stop_trading()
        return jsonify(result)
    except Exception as e:
        web_logger.error(f"자동매매 중지 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'자동매매 중지 실패: {str(e)}'
        })


@app.route('/api/auto-trading/history')
def get_auto_trading_history():
    """자동매매 실행 이력 조회"""
    try:
        days = request.args.get('days', 7, type=int)
        history = config_manager.get_execution_history(days)
        return jsonify({
            'success': True,
            'data': history
        })
    except Exception as e:
        web_logger.error(f"자동매매 이력 조회 실패: {e}")
        return jsonify({
            'success': False,
            'message': f'이력 조회 실패: {str(e)}'
        })


@socketio.on('connect')
def handle_connect():
    """웹소켓 연결 처리"""
    global is_connected
    is_connected = True
    web_logger.info(f"클라이언트 연결: {request.sid}")
    emit('status', {'message': '연결됨', 'timestamp': datetime.now().isoformat()})


@socketio.on('disconnect')
def handle_disconnect():
    """웹소켓 연결 해제 처리"""
    global is_connected
    is_connected = False
    web_logger.info(f"클라이언트 연결 해제: {request.sid}")


@socketio.on('subscribe_stock')
def handle_subscribe_stock(data):
    """종목 실시간 데이터 구독"""
    stock_code = data.get('stock_code')
    if stock_code:
        web_logger.info(f"종목 구독: {stock_code}")
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
            web_logger.error(f"실시간 업데이트 오류: {e}")
            time.sleep(10)


if __name__ == '__main__':
    # 실시간 업데이트 스레드 시작
    update_thread = threading.Thread(target=start_real_time_updates, daemon=True)
    update_thread.start()
    
    # 자동매매 스케줄러 시작
    auto_trading_scheduler.start()
    
    web_logger.info(f"웹 서버 시작: http://{WEB_HOST}:{WEB_PORT}")
    socketio.run(app, host=WEB_HOST, port=WEB_PORT, debug=WEB_DEBUG)
