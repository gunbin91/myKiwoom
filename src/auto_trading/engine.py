# -*- coding: utf-8 -*-
"""
자동매매 엔진
"""
import sys
import os
import io
import json
import time
from datetime import datetime, timedelta
import pandas as pd

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.utils.deep_learning import deep_learning_analyzer
from src.auto_trading.config_manager import AutoTradingConfigManager
from src.api.auth import KiwoomAuth
from src.api.account import KiwoomAccount
from src.api.quote import KiwoomQuote
from src.api.order import KiwoomOrder
from src.utils import get_current_auto_trading_logger
from src.utils.order_history_manager import OrderHistoryManager


class AutoTradingEngine:
    """자동매매 엔진 클래스"""
    
    def __init__(self, server_type='mock'):
        self.server_type = server_type
        self.config_manager = AutoTradingConfigManager(server_type)
        self.analyzer = deep_learning_analyzer
        self.is_running = False
        self.current_status = "대기 중"
        self.progress_percentage = 0
        
        # 로거는 사용 시점에 생성 (멀티프로세싱 문제 방지)
        self.auto_trading_logger = None
        
        # 서버 타입에 맞는 API 인스턴스 생성
        self.auth = KiwoomAuth(server_type)
        self.account = KiwoomAccount(server_type)
        self.quote = KiwoomQuote(server_type)
        self.order = KiwoomOrder(server_type)
        
        # 체결내역 관리자 초기화
        self.order_history_manager = OrderHistoryManager(server_type)
    
    def _get_logger(self):
        """로거 초기화 (지연 로딩)"""
        if self.auto_trading_logger is None:
            # 서버 타입을 명시적으로 지정하여 올바른 로그 파일에 기록
            from src.utils import get_server_logger
            self.auto_trading_logger = get_server_logger(server_type=self.server_type, log_type="auto_trading").bind(server=self.server_type)
        return self.auto_trading_logger

    def _prepare_trading_data(self):
        """체결내역 수집 + 추천종목 분석 (공통)"""
        # 1. 체결내역 수집
        self.current_status = "체결내역 수집 중"
        self.progress_percentage = 10
        self._get_logger().info("🔍 매수 체결내역 수집 시작")
        
        try:
            collection_success = self.order_history_manager.collect_order_history(max_days=30)
            if collection_success:
                summary = self.order_history_manager.get_data_summary()
                self._get_logger().info(f"✅ 매수 체결내역 수집 완료: {summary['total_orders']}개 주문, {summary['stock_count']}개 종목")
            else:
                self._get_logger().warning("⚠️ 매수 체결내역 수집 실패 (자동매매는 계속 진행)")
        except Exception as collection_error:
            self._get_logger().error(f"🚨 체결내역 수집 중 오류: {collection_error}")
        
        # 2. 계좌 정보 조회
        self.current_status = "계좌 정보 조회 중"
        self.progress_percentage = 15
        account_info = self._get_account_info()
        
        # 3. 추천종목 분석
        self.current_status = "추천종목 분석 중"
        self.progress_percentage = 25
        analysis_result = self.analyzer.get_stock_analysis(force_realtime=True)
        
        # 4. 설정 로드
        config = self.config_manager.load_config()
        strategy_params = config.get('strategy_params', {})
        
        return {
            'analysis_result': analysis_result,
            'account_info': account_info,
            'strategy_params': strategy_params
        }

    def _execute_trading_orders(self, analysis_result, account_info, strategy_params):
        """공통 매매 로직 (순차적 실행)"""
        
        # 1. 매도 대상 선별 (보유종목 기준)
        self.current_status = "매도 대상 선별 중"
        self.progress_percentage = 60
        sell_candidates = self._get_sell_candidates(account_info, strategy_params)
        
        # 2. 매도 실행
        self.current_status = "매도 주문 실행 중"
        self.progress_percentage = 65
        self._get_logger().info("📉 매도 주문을 실행하는 중...")
        sell_results = self._execute_sell_orders(sell_candidates, account_info, strategy_params)
        sell_count = sell_results['success_count']
        sell_orders = sell_results.get('sell_orders', [])
        
        # 3. 매도 체결 확인 및 대기
        if sell_count > 0 and sell_orders:
            self.current_status = "매도 체결 확인 중"
            self.progress_percentage = 70
            self._get_logger().info("⏳ 매도 주문 체결을 확인하는 중...")
            
            execution_confirmed = self._wait_for_sell_execution(sell_orders, max_wait_time=30)
            
            if execution_confirmed:
                self._get_logger().info("✅ 매도 체결 확인 완료")
            else:
                self._get_logger().warning("⚠️ 매도 체결 확인 시간 초과, 계속 진행합니다.")
        
        # 4. 예수금 재조회 (매도로 확보된 현금 반영)
        if sell_count > 0:
            self.current_status = "매도 후 계좌 정보 조회 중"
            self.progress_percentage = 75
            self._get_logger().info("💰 매도 후 계좌 정보를 재조회하는 중...")
            
            updated_account_info = self._get_account_info()
            if updated_account_info:
                account_info = updated_account_info
                self._get_logger().info("✅ 매도 후 계좌 정보 업데이트 완료")
            else:
                self._get_logger().warning("⚠️ 매도 후 계좌 정보 조회 실패, 기존 정보 사용")
        
        # 5. 매수 대상 선별 (매도 후 확보된 현금 + 매도된 종목 재매수 가능)
        self.current_status = "매수 대상 선별 중"
        self.progress_percentage = 80
        self._get_logger().info("📊 매수 대상을 선정하는 중...")
        
        buy_candidates = self._get_buy_candidates(
            analysis_result, 
            account_info, 
            strategy_params,
            sell_candidates,  # 매도된 종목들을 매수 대상에 포함
            sell_results  # 매도 주문 결과 전달
        )
        
        # 6. 매수 실행
        self.current_status = "매수 주문 실행 중"
        self.progress_percentage = 85
        self._get_logger().info("📈 매수 주문을 실행하는 중...")
        buy_results = self._execute_buy_orders(buy_candidates, account_info, strategy_params)
        buy_count = buy_results['success_count']
        buy_orders = buy_results.get('buy_orders', [])
        
        # 7. 매수 체결 확인 및 대기
        if buy_count > 0 and buy_orders:
            self.current_status = "매수 체결 확인 중"
            self.progress_percentage = 90
            self._get_logger().info("⏳ 매수 주문 체결을 확인하는 중...")
            
            execution_confirmed = self._wait_for_buy_execution(buy_orders, max_wait_time=30)
            
            if execution_confirmed:
                self._get_logger().info("✅ 매수 체결 확인 완료")
            else:
                self._get_logger().warning("⚠️ 매수 체결 확인 시간 초과, 계속 진행합니다.")
                # 미체결 잔량에 대해: 가드 허용% 상한 내에서 매도2호가로 재시도(정책은 limit_buy_guard_action 사용)
                try:
                    unfilled_failures = self._retry_unfilled_buy_orders_with_ask2(buy_orders, strategy_params, max_total_wait=20)
                    if unfilled_failures:
                        buy_results['unfilled_failures'] = unfilled_failures
                except Exception as retry_err:
                    self._get_logger().warning(f"미체결 매수 재시도 처리 중 오류(무시하고 진행): {retry_err}")
        
        return {
            'sell_results': sell_results,
            'buy_results': buy_results,
            'sell_count': sell_count,
            'buy_count': buy_count,
            'sell_candidates': sell_candidates,
            'buy_candidates': buy_candidates
        }

    def _get_sell_candidates(self, account_info, strategy_params):
        """매도 대상 선별 (보유종목 기준)"""
        sell_candidates = []
        
        try:
            # 보유 종목 조회 - 올바른 구조로 수정
            balance_info = account_info.get('balance', {})
            balance_result = balance_info.get('acnt_evlt_remn_indv_tot', [])
            self._get_logger().debug(f"보유종목 조회: {len(balance_result)}개 종목")
            
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
                    
                    # 종목코드에서 A 프리픽스 제거 (6자리 숫자만 사용)
                    clean_stock_code = stock_code.replace('A', '') if stock_code.startswith('A') else stock_code
                    
                    self._get_logger().debug(f"보유종목 확인: {stock_name}({stock_code} → {clean_stock_code}) - 수량:{quantity}, 평균단가:{avg_price}, 현재가:{current_price}")
                    
                    if quantity <= 0 or avg_price <= 0 or current_price <= 0:
                        self._get_logger().debug(f"보유종목 스킵: {stock_name}({clean_stock_code}) - 유효하지 않은 데이터")
                        continue
                    
                    # 매도 조건 확인
                    should_sell = False
                    sell_reason = ""
                    
                    # 익절/손절 조건
                    profit_rate = ((current_price - avg_price) / avg_price) * 100
                    self._get_logger().debug(f"수익률 계산: {stock_name}({clean_stock_code}) - {profit_rate:.1f}% (익절:{take_profit_pct}%, 손절:{stop_loss_pct}%)")
                    
                    if profit_rate >= take_profit_pct:
                        should_sell = True
                        sell_reason = f"익절 ({profit_rate:.1f}%)"
                        self._get_logger().info(f"📈 익절 조건 만족: {stock_name}({clean_stock_code}) - {profit_rate:.1f}%")
                    elif profit_rate <= -stop_loss_pct:
                        should_sell = True
                        sell_reason = f"손절 ({profit_rate:.1f}%)"
                        self._get_logger().info(f"📉 손절 조건 만족: {stock_name}({clean_stock_code}) - {profit_rate:.1f}%")
                    
                    # 보유기간 만료 조건 추가
                    if not should_sell:
                        try:
                            holding_days = self.order_history_manager.get_holding_period(clean_stock_code, quantity)
                            self._get_logger().debug(f"보유기간 확인: {stock_name}({clean_stock_code}) - {holding_days}일 (최대:{max_hold_period}일)")
                            if holding_days >= max_hold_period:
                                should_sell = True
                                sell_reason = f"보유기간 만료 ({holding_days}일)"
                                self._get_logger().info(f"⏰ 보유기간 만료: {stock_name}({clean_stock_code}) - {holding_days}일")
                        except Exception as holding_error:
                            self._get_logger().warning(f"보유기간 계산 실패 ({clean_stock_code}): {holding_error}")
                    
                    if should_sell:
                        # 보유기간 계산
                        holding_days = -1  # 기본값
                        try:
                            holding_days = self.order_history_manager.get_holding_period(clean_stock_code, quantity)
                        except Exception as holding_error:
                            self._get_logger().warning(f"보유기간 계산 실패 ({clean_stock_code}): {holding_error}")
                        
                        sell_candidates.append({
                            '종목코드': clean_stock_code,  # A 프리픽스 제거된 종목코드 사용
                            '종목명': stock_name,
                            '보유수량': quantity,
                            '평균단가': avg_price,
                            '현재가': current_price,
                            '수익률': profit_rate,
                            '보유기간': holding_days,
                            '매도사유': sell_reason,
                            '매도예상금액': quantity * current_price
                        })
                        self._get_logger().info(f"✅ 매도 대상 추가: {stock_name}({clean_stock_code}) - {sell_reason}")
                
                self._get_logger().info(f"📉 매도 대상 {len(sell_candidates)}개 종목이 선정되었습니다.")
            
        except Exception as e:
            self._get_logger().error(f"매도 대상 선별 중 오류 발생: {e}")
            sell_candidates = []
        
        return sell_candidates

    def _get_buy_candidates(self, analysis_result, account_info, strategy_params, sell_candidates=None, sell_results=None):
        """매수 대상 선별 (analysis_result에서 가져오기)"""
        try:
            # 매도된 종목들을 매수 대상에 포함 (재매수 가능)
            include_sell_candidates = None
            if sell_candidates:
                include_sell_candidates = [candidate['종목코드'] for candidate in sell_candidates]
                self._get_logger().info(f"📋 매도된 종목 {len(include_sell_candidates)}개를 매수 대상에 포함합니다.")
            
            buy_candidates = self.analyzer.get_top_stocks(
                analysis_result,
                top_n=strategy_params.get('top_n', 5),
                buy_universe_rank=strategy_params.get('buy_universe_rank', 20),
                include_sell_candidates=include_sell_candidates,
                sell_results=sell_results,  # 매도 주문 결과 전달
                server_type=self.server_type
            )
            
            self._get_logger().info(f"📋 매수 대상 {len(buy_candidates)}개 종목이 선정되었습니다.")
            return buy_candidates
            
        except Exception as e:
            self._get_logger().error(f"매수 대상 선별 중 오류 발생: {e}")
            return []
    
    def can_execute(self, manual_execution=False):
        """실행 가능 여부 확인"""
        # 1. 오늘 이미 실행했는지 확인 (수동 실행 시에는 체크하지 않음)
        if not manual_execution and self.config_manager.is_today_executed():
            return False, "오늘 이미 실행되었습니다."
        
        # 2. 자동매매가 활성화되어 있는지 확인 (수동 실행 시에는 체크하지 않음)
        if not manual_execution:
            config = self.config_manager.load_config()
            if not config.get('auto_trading_enabled', False):
                return False, "자동매매가 비활성화되어 있습니다."
        
        # 3. 거래 시간 확인 (간단한 체크) - 수동 실행 시에는 경고만
        now = datetime.now()
        if now.hour < 9 or now.hour > 15:
            if manual_execution:
                return True, "거래 시간이 아니지만 수동 실행을 진행합니다."
            else:
                return False, "거래 시간이 아닙니다."
        
        return True, "실행 가능합니다."
    
    def execute_strategy(self, manual_execution=False, test_mode=False):
        """자동매매 전략 실행"""
        if self.is_running:
            return {
                'success': False,
                'message': '이미 실행 중입니다.'
            }
        
        # test_mode가 아닐 때만 실행 가능 여부 확인 (분석결과확인은 자동매매 활성화 체크 안함)
        if not test_mode:
            can_execute, message = self.can_execute(manual_execution)
            if not can_execute:
                return {
                    'success': False,
                    'message': message
                }
        
        self.is_running = True
        self.current_status = "시작 중"
        self.progress_percentage = 0
        
        try:
            self._get_logger().info(f"🤖 자동매매 전략 실행을 시작합니다... (서버: {self.server_type})")
            
            # 0. 토큰 유효성 확인 및 자동 발급
            self.current_status = "토큰 확인 중"
            self.progress_percentage = 5
            token = self.auth.get_access_token()
            
            if not token:
                return {
                    'success': False,
                    'message': '토큰 발급 실패'
                }
            
            # 1. 공통 준비 단계
            trading_data = self._prepare_trading_data()
            
            if test_mode:
                # 분석결과확인: 결과만 반환 (팝업용)
                return {
                    'success': True,
                    'test_mode': True,
                    'analysis_result': trading_data['analysis_result'],
                    'account_info': trading_data['account_info'],
                    'strategy_params': trading_data['strategy_params']
                }
            else:
                # 실제 매매 실행
                trading_results = self._execute_trading_orders(
                    trading_data['analysis_result'],
                    trading_data['account_info'],
                    trading_data['strategy_params']
                )
                
                # 실행 결과 로그 기록
                sell_count = trading_results['sell_count']
                buy_count = trading_results['buy_count']
                sell_results = trading_results['sell_results']
                buy_results = trading_results['buy_results']
                
                # 성공/실패 메시지 생성
                if buy_count > 0 or sell_count > 0:
                    message = f"[자동] 매수 {buy_count}건, 매도 {sell_count}건 실행 완료"
                    status = "success"
                else:
                    message = f"[자동] 매수 실패: {buy_results.get('total_attempts', 0)}개 종목 중 {buy_count}건 성공"
                    status = "failed"

                # 최종 미체결(잔량) 요약을 메시지에 포함(사용자 편의)
                unfilled = buy_results.get('unfilled_failures', []) or []
                if unfilled:
                    preview = ", ".join([f"{x.get('stock_code')}({x.get('unfilled_qty')}주)" for x in unfilled[:3]])
                    suffix = f"{preview}" + (f" 외 {len(unfilled) - 3}개" if len(unfilled) > 3 else "")
                    message = f"{message} | 미체결: {suffix}"
                
                # 실행 결과 로그 기록
                self.config_manager.log_execution(
                    status=status,
                    buy_count=buy_count,
                    sell_count=sell_count,
                    message=message,
                    strategy_params=trading_data['strategy_params'],
                    buy_candidates=trading_results.get('buy_candidates'),
                    sell_candidates=trading_results.get('sell_candidates'),
                    execution_type="자동",
                    buy_results=buy_results,
                    sell_results=sell_results,
                    account_info=trading_data['account_info']
                )
                
                return {
                    'success': True,
                    'test_mode': False,
                    'message': message,  # ✅ message 키 추가
                    'sell_count': sell_count,
                    'buy_count': buy_count,
                    'sell_results': sell_results,
                    'buy_results': buy_results
                }
        
        except Exception as e:
            self._get_logger().error(f"자동매매 실행 중 오류: {e}")
            return {
                'success': False,
                'message': f'자동매매 실행 중 오류가 발생했습니다: {str(e)}'
            }
        finally:
            self.is_running = False
            self.current_status = "완료"
            self.progress_percentage = 100
    
    def get_execution_status(self):
        """실행 상태 조회"""
        return {
            'is_running': self.is_running,
            'current_status': self.current_status,
            'progress_percentage': self.progress_percentage
        }
    
    def _get_account_info(self):
        """계좌 정보 조회"""
        try:
            # 예수금 정보
            deposit_result = self.account.get_deposit_detail()
            if not deposit_result or deposit_result.get('success') is False:
                return {
                    'success': False,
                    'message': '예수금 정보를 가져올 수 없습니다.'
                }
            
            # 주문가능금액을 우선적으로 사용 (100stk_ord_alow_amt)
            if '100stk_ord_alow_amt' in deposit_result and deposit_result['100stk_ord_alow_amt'] and deposit_result['100stk_ord_alow_amt'] != '000000000000000':
                original_entr = deposit_result.get('entr', '0')
                deposit_result['entr'] = deposit_result['100stk_ord_alow_amt']
                deposit_result['entr_type'] = '주문가능금액'
                self._get_logger().info(f"✅ 자동매매: 주문가능금액 사용: {deposit_result['100stk_ord_alow_amt']} (기본 예수금: {original_entr})")
            # D+2 추정예수금 사용 (주문가능금액이 없는 경우)
            elif 'd2_entra' in deposit_result and deposit_result['d2_entra'] and deposit_result['d2_entra'] != '000000000000000':
                original_entr = deposit_result.get('entr', '0')
                deposit_result['entr'] = deposit_result['d2_entra']
                deposit_result['entr_type'] = 'D+2'
                self._get_logger().info(f"✅ 자동매매: D+2 추정예수금 사용: {deposit_result['d2_entra']} (기본 예수금: {original_entr})")
            # D+1 추정예수금 사용 (D+2가 없는 경우)
            elif 'd1_entra' in deposit_result and deposit_result['d1_entra'] and deposit_result['d1_entra'] != '000000000000000':
                original_entr = deposit_result.get('entr', '0')
                deposit_result['entr'] = deposit_result['d1_entra']
                deposit_result['entr_type'] = 'D+1'
                self._get_logger().info(f"✅ 자동매매: D+1 추정예수금 사용: {deposit_result['d1_entra']} (기본 예수금: {original_entr})")
            else:
                deposit_result['entr_type'] = 'D+0'
                self._get_logger().info(f"✅ 자동매매: 기본 예수금 사용: {deposit_result.get('entr', '0')}")
            
            # 보유 종목 정보
            balance_result = self.account.get_account_balance_detail()
            if not balance_result:
                return {
                    'success': False,
                    'message': '보유 종목 정보를 가져올 수 없습니다.'
                }
            
            return {
                'success': True,
                'deposit': deposit_result,
                'balance': balance_result
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'계좌 정보 조회 실패: {str(e)}'
            }

    def execute_intraday_stop_loss(self, threshold_pct: float = -7.0, skip_stock_codes=None):
        """
        장중 손절 감시 실행 (자동매매와 별개)

        - 보유종목의 평가손익률(%)이 threshold_pct 이하로 하락하면 전량 시장가 매도
        - skip_stock_codes: 중복 매도 방지용(쿨다운) 제외 목록
        """
        try:
            now = datetime.now()
            # 장중만 동작 (주말/비거래시간 제외)
            if now.weekday() >= 5:
                return {'success': True, 'message': '주말은 손절 감시를 실행하지 않습니다.', 'sell_results': None}
            if now.hour < 9 or now.hour > 15:
                return {'success': True, 'message': '거래 시간이 아니므로 손절 감시를 실행하지 않습니다.', 'sell_results': None}

            try:
                threshold_pct = float(threshold_pct)
            except Exception:
                threshold_pct = -7.0

            skip_set = set(skip_stock_codes or [])

            balance_result = self.account.get_account_balance_detail()
            if not balance_result:
                return {'success': False, 'message': '보유 종목 정보를 가져올 수 없습니다.', 'sell_results': None}

            holdings = balance_result.get('acnt_evlt_remn_indv_tot', []) or []
            if not holdings:
                return {'success': True, 'message': '보유 종목이 없습니다.', 'sell_results': None}

            sell_candidates = []
            for stock in holdings:
                try:
                    stock_code = stock.get('stk_cd', '') or ''
                    stock_name = stock.get('stk_nm', '') or ''
                    quantity = int(stock.get('rmnd_qty', 0) or 0)
                    avg_price = float(stock.get('pur_pric', 0) or 0)
                    current_price = float(stock.get('cur_prc', 0) or 0)

                    clean_stock_code = stock_code.replace('A', '') if stock_code.startswith('A') else stock_code

                    if not clean_stock_code or quantity <= 0 or avg_price <= 0 or current_price <= 0:
                        continue
                    if clean_stock_code in skip_set:
                        continue

                    profit_rate = ((current_price - avg_price) / avg_price) * 100
                    if profit_rate <= threshold_pct:
                        sell_candidates.append({
                            '종목코드': clean_stock_code,
                            '종목명': stock_name,
                            '보유수량': quantity,
                            '평균단가': avg_price,
                            '현재가': current_price,
                            '수익률': profit_rate,
                            '매도사유': f"장중 손절 감시 ({profit_rate:.1f}% <= {threshold_pct:.1f}%)",
                            '매도예상금액': quantity * current_price
                        })
                except Exception:
                    continue

            if not sell_candidates:
                return {'success': True, 'message': '손절 조건을 만족하는 종목이 없습니다.', 'sell_results': None}

            self._get_logger().warning(
                f"🛡️ 장중 손절 감시 조건 충족: {len(sell_candidates)}개 종목 (기준: {threshold_pct:.1f}%)"
            )

            sell_results = self._execute_sell_orders(sell_candidates, account_info=None, strategy_params=None)
            success_count = sell_results.get('success_count', 0)
            failed_count = sell_results.get('failed_count', 0)

            if success_count > 0:
                return {
                    'success': True,
                    'message': f'장중 손절 감시 매도 {success_count}건 성공, {failed_count}건 실패',
                    'sell_results': sell_results
                }
            return {
                'success': False,
                'message': f'장중 손절 감시 매도 성공 0건, {failed_count}건 실패',
                'sell_results': sell_results
            }

        except Exception as e:
            self._get_logger().error(f"장중 손절 감시 실행 실패: {e}")
            return {'success': False, 'message': f'장중 손절 감시 실행 실패: {str(e)}', 'sell_results': None}
    
    def _execute_buy_orders(self, buy_candidates, account_info, strategy_params):
        """매수 주문 실행 (시장가/호가 기반 지정가 옵션 지원)"""
        success_count = 0
        failed_count = 0
        total_buy_amount = 0
        total_buy_quantity = 0
        buy_details = []
        buy_orders = []  # 매수 주문 정보 저장 (체결 확인용)
        reserve_cash = strategy_params.get('reserve_cash', 1000000)
        transaction_fee_rate = strategy_params.get('transaction_fee_rate', 0.015)
        
        try:
            # 예수금 정보 상세 로그 (100stk_ord_alow_amt 사용)
            total_deposit = int(account_info['deposit'].get('100stk_ord_alow_amt', 0))
            entr_type = account_info['deposit'].get('entr_type', 'D+0')
            self._get_logger().info(f"💰 주문가능금액 ({entr_type}): {total_deposit:,}원")
            self._get_logger().info(f"💰 매매제외예수금: {reserve_cash:,}원")
            
            # 사용 가능한 현금 계산
            available_cash = total_deposit - reserve_cash
            self._get_logger().info(f"💰 사용 가능한 현금: {available_cash:,}원 (총예수금 - 매매제외예수금)")
            
            if available_cash <= 0:
                self._get_logger().warning(f"사용 가능한 현금이 부족합니다. (예수금: {total_deposit:,}, 예약금: {reserve_cash:,})")
                return {'success_count': 0}
            
            # 매수 대상이 없는 경우 조기 종료
            if not buy_candidates or len(buy_candidates) == 0:
                self._get_logger().info("📊 매수 대상 종목이 없습니다.")
                return {'success_count': 0}
            
            # 실전에서는 종목당 동일한 금액 투자 (수수료 고려)
            investment_per_stock = available_cash // len(buy_candidates)
            
            self._get_logger().info(f"📊 매수 대상 종목 수: {len(buy_candidates)}개")
            self._get_logger().info(f"📊 종목당 투자 금액: {investment_per_stock:,}원")
            
            buy_order_method = (strategy_params.get('buy_order_method', 'market') or 'market').strip()
            limit_buy_max_premium_pct = float(strategy_params.get('limit_buy_max_premium_pct', 1.0) or 1.0)
            limit_buy_guard_action = (strategy_params.get('limit_buy_guard_action', 'skip') or 'skip').strip()

            for candidate in buy_candidates:
                try:
                    stock_code = candidate.get('종목코드', '')
                    stock_name = candidate.get('종목명', '')
                    analysis_price = candidate.get('현재가', 0)  # 분석 시점 가격 (참고용)
                    
                    if not stock_code:
                        self._get_logger().error(f"❌ 종목코드가 없습니다: {candidate}")
                        continue
                    
                    # 🔥 핵심 수정: 키움 API로 실시간 현재가 조회
                    self._get_logger().info(f"📡 {stock_name}({stock_code}) 실시간 현재가 조회 중...")
                    realtime_price_result = self._get_realtime_price(stock_code)
                    
                    if not realtime_price_result['success']:
                        # 실시간 가격 조회 실패 시 분석 시점 가격 사용
                        if analysis_price > 0:
                            realtime_price = analysis_price
                            self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 실시간 가격 조회 실패, 분석 시점 가격 사용: {analysis_price:,}원")
                        else:
                            self._get_logger().error(f"❌ {stock_name}({stock_code}) 가격 정보 없음 (실시간: {realtime_price_result['message']}, 분석시점: {analysis_price})")
                            continue
                    else:
                        realtime_price = realtime_price_result['price']
                        self._get_logger().info(f"📊 {stock_name}({stock_code}) 실시간 가격: {realtime_price:,}원 (분석시점: {analysis_price:,}원)")
                    
                    # 수수료를 고려한 매수 수량 계산
                    effective_price = realtime_price * (1 + transaction_fee_rate / 100)
                    quantity = int(investment_per_stock // effective_price)
                    
                    if quantity <= 0:
                        self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 매수 수량이 0입니다. (투자금액: {investment_per_stock:,}원, 실시간가격: {realtime_price:,}원)")
                        continue
                    
                    # 매수 주문 실행 (재시도 로직 포함)
                    # 주문 방식 선택: market(기존) / limit_ask1(매도1호가 지정가)
                    order_type_to_send = '3'  # 기본 시장가
                    order_price_to_send = 0

                    if buy_order_method == 'limit_ask1':
                        hoga = self._get_best_ask_price(stock_code)
                        best_ask_price = int(hoga.get('price', 0) or 0) if hoga.get('success') else 0

                        if best_ask_price <= 0:
                            if limit_buy_guard_action == 'market_fallback':
                                self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 매도1호가 조회 실패 → 시장가로 폴백")
                                order_type_to_send = '3'
                                order_price_to_send = 0
                            else:
                                self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 매도1호가 조회 실패 → 매수 스킵")
                                continue
                        else:
                            # 현재가 대비 과도한 프리미엄 방지
                            if realtime_price > 0:
                                premium_pct = ((best_ask_price - realtime_price) / realtime_price) * 100
                                if premium_pct > limit_buy_max_premium_pct:
                                    msg = (f"🛑 {stock_name}({stock_code}) 가드 발동: "
                                           f"매도1호가 {best_ask_price:,}원이 현재가 {realtime_price:,}원 대비 "
                                           f"+{premium_pct:.2f}% (허용 {limit_buy_max_premium_pct:.2f}%)")
                                    if limit_buy_guard_action == 'market_fallback':
                                        self._get_logger().warning(msg + " → 시장가로 폴백")
                                        order_type_to_send = '3'
                                        order_price_to_send = 0
                                    else:
                                        self._get_logger().warning(msg + " → 매수 스킵")
                                        continue
                                else:
                                    order_type_to_send = '0'
                                    order_price_to_send = best_ask_price
                            else:
                                # 현재가가 없으면 보수적으로 스킵(또는 폴백)
                                if limit_buy_guard_action == 'market_fallback':
                                    self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 현재가 부족 → 시장가로 폴백")
                                    order_type_to_send = '3'
                                    order_price_to_send = 0
                                else:
                                    self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 현재가 부족 → 매수 스킵")
                                    continue

                    if order_type_to_send == '0':
                        self._get_logger().info(
                            f"📈 {stock_name}({stock_code}) 지정가 매수 주문: {quantity}주 @ {order_price_to_send:,}원 (매도1호가)"
                        )
                    else:
                        self._get_logger().info(
                            f"📈 {stock_name}({stock_code}) 시장가 매수 주문: {quantity}주 (참고 현재가: {realtime_price:,}원)"
                        )
                    
                    # 매수 주문 재시도 (최대 2회)
                    max_retries = 2
                    order_success = False
                    
                    for retry in range(max_retries):
                        # 주문 API용 종목코드로 변환 (A 제거)
                        from src.api.order import convert_stock_code_for_order
                        order_stock_code = convert_stock_code_for_order(stock_code)
                        
                        order_result = self.order.buy_stock(
                            stock_code=order_stock_code,  # 변환된 종목코드 사용
                            quantity=quantity,
                            price=order_price_to_send,
                            order_type=order_type_to_send
                        )
                        
                        if order_result and order_result.get('success') is not False:
                            order_success = True
                            success_count += 1
                            total_buy_amount += quantity * realtime_price
                            total_buy_quantity += quantity
                            
                            # 매수 성공 상세 정보 기록
                            buy_reason = candidate.get('매수사유', 'AI 분석 추천')
                            buy_details.append({
                                'stock_name': stock_name,
                                'stock_code': stock_code,
                                'quantity': quantity,
                                'price': order_price_to_send if order_type_to_send == '0' else realtime_price,
                                'amount': quantity * (order_price_to_send if order_type_to_send == '0' else realtime_price),
                                'status': '성공',
                                'error_message': '',
                                'reason': buy_reason
                            })

                            # 매수 주문 정보 저장 (체결 확인용)
                            buy_orders.append({
                                'stock_code': stock_code,
                                'stock_name': stock_name,
                                'quantity': quantity,
                                'price': order_price_to_send if order_type_to_send == '0' else realtime_price,
                                'reason': buy_reason,
                                'order_type': order_type_to_send,
                                'ord_no': order_result.get('ord_no') if isinstance(order_result, dict) else None
                            })
                            
                            self._get_logger().info(f"✅ {stock_name} 매수 주문 성공")
                            break
                        else:
                            # API 에러 메시지를 더 명확하게 표시
                            if order_result:
                                error_code = order_result.get('error_code', '')
                                error_message = order_result.get('error_message', '')
                                if error_code and error_message:
                                    error_msg = f"[{error_code}] {error_message}"
                                else:
                                    error_msg = order_result.get('message', '알 수 없는 오류')
                            else:
                                error_msg = 'API 응답 없음'
                            if retry < max_retries - 1:
                                self._get_logger().warning(f"⚠️ {stock_name} 매수 주문 실패, {retry + 1}초 후 재시도... (오류: {error_msg})")
                                time.sleep(1)  # 1초 대기 후 재시도
                            else:
                                failed_count += 1
                                
                                # 매수 실패 상세 정보 기록
                                buy_reason = candidate.get('매수사유', 'AI 분석 추천')
                                buy_details.append({
                                    'stock_name': stock_name,
                                    'stock_code': stock_code,
                                    'quantity': quantity,
                                    'price': realtime_price,
                                    'amount': quantity * realtime_price,
                                    'status': '실패',
                                    'error_message': error_msg,
                                    'reason': buy_reason
                                })
                                
                                self._get_logger().error(f"❌ {stock_name} 매수 주문 최종 실패 (재시도 {max_retries}회 완료): {error_msg}")
                    
                    if not order_success:
                        continue
                        
                except Exception as e:
                    self._get_logger().error(f"매수 주문 실행 중 오류: {e}")
                    continue
            
            # 매수 실패 원인 분석
            if success_count == 0 and len(buy_candidates) > 0:
                self._get_logger().error(f"❌ 모든 매수 주문이 실패했습니다. 총 {len(buy_candidates)}개 종목 중 0건 성공")
                print(f"❌ 모든 매수 주문이 실패했습니다. 총 {len(buy_candidates)}개 종목 중 0건 성공")
                
                # 실패 원인 상세 분석
                missing_price_count = 0
                for candidate in buy_candidates:
                    if candidate.get('현재가', 0) <= 0:
                        missing_price_count += 1
                
                if missing_price_count > 0:
                    self._get_logger().error(f"❌ 실패 원인: {missing_price_count}개 종목에 현재가 정보가 없습니다.")
                    print(f"❌ 실패 원인: {missing_price_count}개 종목에 현재가 정보가 없습니다.")
            
            return {
                'success_count': success_count,
                'failed_count': failed_count,
                'total_attempts': success_count + failed_count,
                'total_buy_amount': total_buy_amount,
                'total_buy_quantity': total_buy_quantity,
                'details': buy_details,
                'buy_orders': buy_orders
            }
            
        except Exception as e:
            self._get_logger().error(f"매수 주문 실행 중 오류: {e}")
            print(f"❌ 매수 주문 실행 중 오류: {e}")
            return {
                'success_count': 0,
                'failed_count': 0,
                'total_attempts': 0,
                'total_buy_amount': 0,
                'total_buy_quantity': 0,
                'details': [],
                'buy_orders': []
            }
    
    def _wait_for_sell_execution(self, sell_orders, max_wait_time=30):
        """매도 주문 체결 대기 및 확인"""
        import time
        from datetime import datetime, timedelta
        
        if not sell_orders:
            return True
        
        self._get_logger().info(f"📋 {len(sell_orders)}건의 매도 주문 체결을 확인하는 중...")
        
        start_time = datetime.now()
        max_wait = timedelta(seconds=max_wait_time)
        
        while datetime.now() - start_time < max_wait:
            try:
                # 오늘 날짜로 체결내역 조회
                today = datetime.now().strftime('%Y%m%d')
                execution_result = self.order.get_order_history(
                    start_date=today,
                    end_date=today,
                    order_type="1"  # 매도만
                )
                
                if execution_result and execution_result.get('acnt_ord_cntr_prps_dtl'):
                    executed_orders = execution_result['acnt_ord_cntr_prps_dtl']
                    
                    # 매도 주문 중 체결된 것들 확인
                    executed_count = 0
                    for sell_order in sell_orders:
                        stock_code = sell_order.get('stock_code', '')
                        order_qty = sell_order.get('quantity', 0)
                        
                        # 해당 종목의 체결내역 확인 (종목코드 형식 통일)
                        for execution in executed_orders:
                            execution_stock_code = execution.get('stk_cd', '')
                            # 계좌 API에서 받은 종목코드(A005930)에서 A 제거하여 비교
                            if (execution_stock_code.replace('A', '') == stock_code.replace('A', '') and
                                int(execution.get('cntr_qty', 0)) >= order_qty):
                                executed_count += 1
                                self._get_logger().info(f"✅ {stock_code} 매도 체결 확인: {execution.get('cntr_qty')}주")
                                break
                    
                    if executed_count >= len(sell_orders):
                        self._get_logger().info(f"✅ 모든 매도 주문 체결 확인 완료: {executed_count}/{len(sell_orders)}건")
                        return True
                    else:
                        self._get_logger().info(f"⏳ 매도 체결 대기 중: {executed_count}/{len(sell_orders)}건 체결")
                
                # 3초 대기 후 재확인
                time.sleep(3)
                
            except Exception as e:
                self._get_logger().warning(f"매도 체결 확인 중 오류: {e}")
                time.sleep(3)
        
        self._get_logger().warning(f"⚠️ 매도 체결 확인 시간 초과 ({max_wait_time}초), 계속 진행합니다.")
        return False

    def _wait_for_buy_execution(self, buy_orders, max_wait_time=30):
        """매수 주문 체결 대기 및 확인 (매도 체결 확인과 동일 패턴)"""
        import time
        from datetime import datetime, timedelta

        if not buy_orders:
            return True

        self._get_logger().info(f"📋 {len(buy_orders)}건의 매수 주문 체결을 확인하는 중...")

        start_time = datetime.now()
        max_wait = timedelta(seconds=max_wait_time)

        while datetime.now() - start_time < max_wait:
            try:
                # 오늘 날짜로 체결내역 조회
                today = datetime.now().strftime('%Y%m%d')
                execution_result = self.order.get_order_history(
                    start_date=today,
                    end_date=today,
                    order_type="2"  # 매수만
                )

                if execution_result and execution_result.get('acnt_ord_cntr_prps_dtl'):
                    executed_orders = execution_result['acnt_ord_cntr_prps_dtl']

                    # 매수 주문 중 체결된 것들 확인
                    executed_count = 0
                    for buy_order in buy_orders:
                        stock_code = buy_order.get('stock_code', '')
                        order_qty = buy_order.get('quantity', 0)

                        for execution in executed_orders:
                            execution_stock_code = execution.get('stk_cd', '')
                            # 계좌 API에서 받은 종목코드(A005930)에서 A 제거하여 비교
                            if (execution_stock_code.replace('A', '') == stock_code.replace('A', '') and
                                int(execution.get('cntr_qty', 0)) >= order_qty):
                                executed_count += 1
                                self._get_logger().info(f"✅ {stock_code} 매수 체결 확인: {execution.get('cntr_qty')}주")
                                break

                    if executed_count >= len(buy_orders):
                        self._get_logger().info(f"✅ 모든 매수 주문 체결 확인 완료: {executed_count}/{len(buy_orders)}건")
                        return True
                    else:
                        self._get_logger().info(f"⏳ 매수 체결 대기 중: {executed_count}/{len(buy_orders)}건 체결")

                # 3초 대기 후 재확인
                time.sleep(3)

            except Exception as e:
                self._get_logger().warning(f"매수 체결 확인 중 오류: {e}")
                time.sleep(3)

        self._get_logger().warning(f"⚠️ 매수 체결 확인 시간 초과 ({max_wait_time}초), 계속 진행합니다.")
        return False

    def _get_unexecuted_buy_qty_by_ord_no(self, order_no: str) -> int:
        """미체결 조회(ka10075)로 주문번호 기준 미체결 잔량 조회"""
        try:
            if not order_no:
                return 0

            # trade_type은 브로커/문서별로 값 의미가 다를 수 있어 전체 조회 후 주문번호로 필터링
            result = self.account.get_unexecuted_orders(all_stock_type="0", trade_type="0", exchange="KRX")
            if not result or result.get('success') is False:
                return 0

            oso_list = result.get('oso', []) or []
            for row in oso_list:
                if str(row.get('ord_no', '')).strip() == str(order_no).strip():
                    try:
                        return int(row.get('oso_qty', 0) or 0)
                    except Exception:
                        return 0
            return 0
        except Exception as e:
            self._get_logger().warning(f"미체결 잔량 조회 실패(ord_no={order_no}): {e}")
            return 0

    def _retry_unfilled_buy_orders_with_ask2(self, buy_orders, strategy_params, max_total_wait=20):
        """
        미체결(잔량)인 매수 주문에 대해:
        - max_price(현재가*(1+허용%)) 이내에서 매도2~10호가로 단계적으로 상향 재주문
          - 재주문 전 항상 '현재 주문 잔량만' 취소하여, 미체결 주문이 여러 개 남지 않게 한다.
        - max_price 초과/호가조회 실패면: strategy_params.limit_buy_guard_action 사용
          - skip: 마지막 주문(현재 미체결)을 그대로 둔다.
          - market_fallback: 잔량 취소 후 시장가로 재주문한다.

        주의: 사용자가 요청한 정책에 따라 '마지막 시도' 주문만 남길 수 있으며,
        재시도 과정에서 여러 주문이 남지 않도록 항상 취소 확인 후 진행한다.
        """
        if not buy_orders:
            return []

        buy_order_method = (strategy_params.get('buy_order_method', 'market') or 'market').strip()
        if buy_order_method != 'limit_ask1':
            return []

        limit_buy_max_premium_pct = float(strategy_params.get('limit_buy_max_premium_pct', 1.0) or 1.0)
        limit_buy_guard_action = (strategy_params.get('limit_buy_guard_action', 'skip') or 'skip').strip()

        start_time = datetime.now()
        retry_orders = []  # 재주문 체결 확인용(선택)
        unfilled_failures = []  # 최종 미체결/실패 요약(사용자 노출용)

        def _get_ask_price_by_level(quote_data: dict, level: int) -> int:
            if level == 1:
                return self._parse_int_field(quote_data.get('sel_fpr_bid', 0), default=0)
            return self._parse_int_field(quote_data.get(f"sel_{level}th_pre_bid", 0), default=0)

        for bo in buy_orders:
            if (datetime.now() - start_time).total_seconds() > max_total_wait:
                break

            current_order_no = bo.get('ord_no') or ''
            stock_code = bo.get('stock_code') or ''
            stock_name = bo.get('stock_name') or stock_code
            if not current_order_no or not stock_code:
                continue

            # 현재 미체결 잔량 확인(0이면 종료)
            unfilled_qty = self._get_unexecuted_buy_qty_by_ord_no(current_order_no)
            if unfilled_qty <= 0:
                continue

            # 현재가 재조회 + max_price 산정 (재시도 상한)
            rt = self._get_realtime_price(stock_code)
            current_price = int(rt.get('price', 0) or 0) if rt.get('success') else 0
            if current_price <= 0:
                self._get_logger().warning(f"⚠️ {stock_name}({stock_code}) 현재가 조회 실패 → 미체결 처리 생략(주문 유지)")
                continue

            max_price = int(current_price * (1 + limit_buy_max_premium_pct / 100))

            # 매도2~10호가까지 단계적으로 올리며 재시도
            escalated = False
            for level in range(2, 11):
                if (datetime.now() - start_time).total_seconds() > max_total_wait:
                    break

                # 현재 주문의 잔량 재확인
                unfilled_qty = self._get_unexecuted_buy_qty_by_ord_no(current_order_no)
                if unfilled_qty <= 0:
                    break  # 이미 체결됨

                quote = self.quote.get_stock_quote(stock_code) or {}
                ask_price = _get_ask_price_by_level(quote, level)

                if ask_price <= 0:
                    continue

                if ask_price > max_price:
                    # 상한 초과: 정책 적용 (마지막 주문만 남기기)
                    if limit_buy_guard_action == 'market_fallback':
                        self._get_logger().warning(
                            f"🛑 {stock_name}({stock_code}) max_price 초과: 매도{level}호가 {ask_price:,} > max {max_price:,} "
                            f"→ 잔량 취소 후 시장가 폴백(잔량:{unfilled_qty})"
                        )
                        cancel_res = self.order.cancel_order(order_no=current_order_no, stock_code=stock_code, quantity=unfilled_qty)
                        if cancel_res and cancel_res.get('success') is not False:
                            mr = self.order.buy_stock(stock_code=stock_code, quantity=unfilled_qty, price=0, order_type='3')
                            if mr and mr.get('success') is not False:
                                current_order_no = mr.get('ord_no') or current_order_no
                                retry_orders.append({'stock_code': stock_code, 'quantity': unfilled_qty, 'ord_no': current_order_no})
                        # 폴백 후에는 더 이상 호가 상향 재시도 안 함
                    else:
                        self._get_logger().warning(
                            f"🛑 {stock_name}({stock_code}) max_price 초과: 매도{level}호가 {ask_price:,} > max {max_price:,} "
                            f"→ 마지막 주문 유지(잔량:{unfilled_qty})"
                        )
                    escalated = True
                    break

                # 잔량 취소 후, 해당 호가로 재주문 (이전 주문이 남지 않도록)
                self._get_logger().info(
                    f"🔁 {stock_name}({stock_code}) 미체결 잔량 {unfilled_qty}주 재시도: "
                    f"기존 주문 취소 → 매도{level}호가 {ask_price:,}원 지정가 재주문 (max:{max_price:,})"
                )

                cancel_res = self.order.cancel_order(order_no=current_order_no, stock_code=stock_code, quantity=unfilled_qty)
                if not (cancel_res and cancel_res.get('success') is not False):
                    # 취소 실패하면 중복 미체결이 생길 수 있어 재시도 중단
                    self._get_logger().warning(
                        f"⚠️ {stock_name}({stock_code}) 잔량 취소 실패(ord_no={current_order_no}) → 중복 주문 방지 위해 재시도 중단"
                    )
                    escalated = True
                    break

                nr = self.order.buy_stock(stock_code=stock_code, quantity=unfilled_qty, price=ask_price, order_type='0')
                if nr and nr.get('success') is not False:
                    current_order_no = nr.get('ord_no') or current_order_no
                    retry_orders.append({'stock_code': stock_code, 'quantity': unfilled_qty, 'ord_no': current_order_no})
                    escalated = True
                else:
                    # 재주문 실패 시 더 진행하지 않음(마지막 주문 없음/취소되어 버림 가능)
                    self._get_logger().warning(
                        f"⚠️ {stock_name}({stock_code}) 매도{level}호가 재주문 실패 → 추가 재시도 중단 (잔량:{unfilled_qty})"
                    )
                    escalated = True
                    break

                # 너무 빠르게 연속 호출하지 않도록 짧게 대기 후 다음 단계 판단
                time.sleep(0.6)

            # 최종 잔량 로그(실패 종목으로 남기기)
            final_unfilled = self._get_unexecuted_buy_qty_by_ord_no(current_order_no)
            if final_unfilled > 0:
                self._get_logger().warning(
                    f"❌ {stock_name}({stock_code}) 미체결 잔량 남음: {final_unfilled}주 (최종 ord_no={current_order_no})"
                )
                unfilled_failures.append({
                    'stock_name': stock_name,
                    'stock_code': stock_code,
                    'unfilled_qty': final_unfilled,
                    'ord_no': current_order_no,
                    'max_price': max_price,
                    'guard_action': limit_buy_guard_action
                })
            elif escalated:
                self._get_logger().info(f"✅ {stock_name}({stock_code}) 재시도 후 미체결 잔량 없음(체결 확인)")

        if retry_orders:
            # 재주문이 있었다면 짧게 체결 확인(선택적)
            self._wait_for_buy_execution(retry_orders, max_wait_time=15)

        return unfilled_failures

    def _execute_sell_orders(self, sell_candidates, account_info, strategy_params):
        """매도 주문 실행 (백테스팅 로직과 일치)"""
        success_count = 0
        failed_count = 0
        total_sell_amount = 0
        total_sell_quantity = 0
        sell_details = []
        sell_orders = []  # 매도 주문 정보 저장
        
        if sell_candidates is None:
            sell_candidates = []
        
        try:
            # sell_candidates가 없으면 매도하지 않음
            if not sell_candidates:
                return {
                    'success_count': 0,
                    'failed_count': 0,
                    'total_attempts': 0,
                    'total_sell_amount': 0,
                    'total_sell_quantity': 0,
                    'details': [],
                    'sell_orders': []
                }
            
            # sell_candidates를 기반으로 매도 주문 실행
            for sell_candidate in sell_candidates:
                try:
                    stock_code = sell_candidate.get('종목코드', '')
                    stock_name = sell_candidate.get('종목명', '')
                    quantity = int(sell_candidate.get('보유수량', 0))
                    avg_price = float(sell_candidate.get('평균단가', 0))
                    current_price = float(sell_candidate.get('현재가', 0))
                    
                    if quantity <= 0 or avg_price <= 0 or current_price <= 0:
                        continue
                    
                    # sell_candidate에서 이미 계산된 정보 사용
                    sell_reason = sell_candidate.get('매도사유', '')
                    return_rate = sell_candidate.get('수익률', 0)
                    
                    self._get_logger().info(f"📉 {stock_name}({stock_code}) 매도 주문: {quantity}주 @ {current_price}원 ({sell_reason})")
                    
                    # 주문 API용 종목코드로 변환 (A 제거)
                    from src.api.order import convert_stock_code_for_order
                    order_stock_code = convert_stock_code_for_order(stock_code)
                    
                    order_result = self.order.sell_stock(
                        stock_code=order_stock_code,  # 변환된 종목코드 사용
                        quantity=quantity,
                        price=0,  # 시장가는 가격을 0으로 설정
                        order_type='3'  # 시장가
                    )
                    
                    if order_result and order_result.get('success') is not False:
                        success_count += 1
                        total_sell_amount += quantity * current_price
                        total_sell_quantity += quantity
                        
                        # 매도 성공 상세 정보 기록
                        sell_details.append({
                            'stock_name': stock_name,
                            'stock_code': stock_code,
                            'quantity': quantity,
                            'price': current_price,
                            'amount': quantity * current_price,
                            'status': '성공',
                            'error_message': '',
                            'reason': sell_reason
                        })
                        
                        # 매도 주문 정보 저장 (체결 확인용)
                        sell_orders.append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'quantity': quantity,
                            'price': current_price,
                            'reason': sell_reason
                        })
                        self._get_logger().info(f"✅ {stock_name} 매도 주문 성공")
                    else:
                        failed_count += 1
                        # API 에러 메시지를 더 명확하게 표시
                        if order_result:
                            error_code = order_result.get('error_code', '')
                            error_message = order_result.get('error_message', '')
                            if error_code and error_message:
                                error_msg = f"[{error_code}] {error_message}"
                            else:
                                error_msg = order_result.get('message', '알 수 없는 오류')
                        else:
                            error_msg = 'API 응답 없음'
                        
                        # 매도 실패 상세 정보 기록
                        sell_details.append({
                            'stock_name': stock_name,
                            'stock_code': stock_code,
                            'quantity': quantity,
                            'price': current_price,
                            'amount': quantity * current_price,
                            'status': '실패',
                            'error_message': error_msg,
                            'reason': sell_reason
                        })
                        
                        self._get_logger().warning(f"❌ {stock_name} 매도 주문 실패: {error_msg}")
                        
                except Exception as e:
                    self._get_logger().error(f"매도 주문 실행 중 오류: {e}")
                    continue
            
            return {
                'success_count': success_count,
                'failed_count': failed_count,
                'total_attempts': len(sell_candidates),
                'total_sell_amount': total_sell_amount,
                'total_sell_quantity': total_sell_quantity,
                'details': sell_details,
                'sell_orders': sell_orders
            }
            
        except Exception as e:
            self._get_logger().error(f"매도 주문 실행 중 오류: {e}")
            return {
                'success_count': success_count,
                'failed_count': failed_count,
                'total_attempts': len(sell_candidates) if sell_candidates else 0,
                'total_sell_amount': total_sell_amount,
                'total_sell_quantity': total_sell_quantity,
                'details': sell_details,
                'sell_orders': sell_orders
            }
    
    def _validate_analysis_result(self, analysis_result):
        """분석 결과 검증"""
        try:
            # 1. 기본 성공 여부 확인
            if not analysis_result.get('success'):
                return {
                    'success': False,
                    'message': f"분석 실행 실패: {analysis_result.get('message', '알 수 없는 오류')}"
                }
            
            # 2. 데이터 구조 확인
            data = analysis_result.get('data', {})
            if not data:
                return {
                    'success': False,
                    'message': "분석 결과 데이터가 없습니다."
                }
            
            # 3. 분석 결과 리스트 확인
            analysis_list = data.get('analysis_result', [])
            if not analysis_list:
                return {
                    'success': False,
                    'message': "분석된 종목이 없습니다."
                }
            
            # 4. 최소 종목 수 확인 (최소 5개 이상)
            if len(analysis_list) < 5:
                return {
                    'success': False,
                    'message': f"분석된 종목 수가 부족합니다. (현재: {len(analysis_list)}개, 최소: 5개)"
                }
            
            # 5. 필수 컬럼 확인
            required_columns = ['종목코드', '종목명', '현재가', '최종순위']
            missing_columns = []
            
            for column in required_columns:
                if not any(column in item for item in analysis_list):
                    missing_columns.append(column)
            
            if missing_columns:
                return {
                    'success': False,
                    'message': f"필수 컬럼이 누락되었습니다: {', '.join(missing_columns)}"
                }
            
            # 6. 현재가 정보 검증
            valid_stocks = []
            invalid_stocks = []
            
            for item in analysis_list:
                stock_code = item.get('종목코드', '')
                stock_name = item.get('종목명', '')
                current_price = item.get('현재가', 0)
                
                if not stock_code or not stock_name:
                    invalid_stocks.append(f"{stock_name}({stock_code}) - 기본정보 누락")
                elif current_price <= 0:
                    invalid_stocks.append(f"{stock_name}({stock_code}) - 현재가 정보 없음")
                else:
                    valid_stocks.append(item)
            
            # 7. 유효한 종목 수 확인 (완화된 기준)
            if len(valid_stocks) < 1:
                return {
                    'success': False,
                    'message': f"유효한 종목이 없습니다. (유효: {len(valid_stocks)}개, 무효: {len(invalid_stocks)}개)"
                }
            
            # 8. 경고 로그 (무효 종목이 있는 경우)
            if invalid_stocks:
                self._get_logger().warning(f"⚠️ {len(invalid_stocks)}개 종목의 데이터가 무효합니다:")
                for invalid in invalid_stocks[:5]:  # 최대 5개만 로그
                    self._get_logger().warning(f"   - {invalid}")
                if len(invalid_stocks) > 5:
                    self._get_logger().warning(f"   ... 외 {len(invalid_stocks) - 5}개")
            
            self._get_logger().info(f"✅ 분석 결과 검증 완료: {len(valid_stocks)}개 유효 종목")
            
            return {
                'success': True,
                'message': f"검증 완료: {len(valid_stocks)}개 유효 종목",
                'valid_stocks': valid_stocks,
                'invalid_count': len(invalid_stocks)
            }
            
        except Exception as e:
            self._get_logger().error(f"분석 결과 검증 중 오류: {e}")
            return {
                'success': False,
                'message': f"검증 중 예외 발생: {str(e)}"
            }
    
    def _validate_buy_candidates(self, buy_candidates):
        """매수 대상 검증"""
        try:
            if not buy_candidates:
                return {
                    'success': False,
                    'message': "매수 대상 종목이 없습니다."
                }
            
            # 각 매수 대상의 필수 정보 확인
            valid_candidates = []
            for candidate in buy_candidates:
                stock_code = candidate.get('종목코드', '')
                stock_name = candidate.get('종목명', '')
                
                if not stock_code or not stock_name:
                    self._get_logger().warning(f"⚠️ 매수 대상에서 제외: 기본정보 누락 - {candidate}")
                    continue
                
                valid_candidates.append(candidate)
            
            if not valid_candidates:
                return {
                    'success': False,
                    'message': "유효한 매수 대상이 없습니다."
                }
            
            self._get_logger().info(f"✅ 매수 대상 검증 완료: {len(valid_candidates)}개 종목")
            
            return {
                'success': True,
                'message': f"검증 완료: {len(valid_candidates)}개 매수 대상",
                'valid_candidates': valid_candidates
            }
            
        except Exception as e:
            self._get_logger().error(f"매수 대상 검증 중 오류: {e}")
            return {
                'success': False,
                'message': f"매수 대상 검증 중 예외 발생: {str(e)}"
            }
    
    def _get_realtime_price(self, stock_code):
        """키움 API로 실시간 현재가 조회"""
        try:
            # 서버 타입에 맞는 quote 인스턴스 사용
            
            # 키움 API로 실시간 현재가 조회
            quote_result = self.quote.get_current_price(stock_code)
            
            if quote_result and quote_result.get('success') is not False:
                current_price = quote_result.get('current_price', 0)
                if current_price > 0:
                    return {
                        'success': True,
                        'price': current_price,
                        'message': '실시간 가격 조회 성공'
                    }
                else:
                    return {
                        'success': False,
                        'price': 0,
                        'message': '유효하지 않은 가격 정보'
                    }
            else:
                return {
                    'success': False,
                    'price': 0,
                    'message': f'키움 API 조회 실패: {quote_result.get("message", "알 수 없는 오류")}'
                }
                
        except Exception as e:
            self._get_logger().error(f"실시간 가격 조회 중 오류: {e}")
            return {
                'success': False,
                'price': 0,
                'message': f'가격 조회 중 예외 발생: {str(e)}'
            }

    def _parse_int_field(self, value, default=0):
        """키움 API 응답의 숫자 필드를 안전하게 int로 변환"""
        try:
            if value is None:
                return default
            if isinstance(value, (int, float)):
                return int(value)
            s = str(value).strip()
            if not s:
                return default
            # +, - 기호 / 쉼표 제거
            s = s.replace('+', '').replace('-', '').replace(',', '')
            return int(s) if s.isdigit() else default
        except Exception:
            return default

    def _get_best_ask_price(self, stock_code):
        """
        주식호가요청(ka10004) 기반 매도1호가(최우선 매도호가, sel_fpr_bid) 조회
        """
        try:
            quote = self.quote.get_stock_quote(stock_code)
            if not quote or quote.get('success') is False:
                return {'success': False, 'price': 0, 'message': '호가 조회 실패'}

            best_ask = self._parse_int_field(quote.get('sel_fpr_bid', 0), default=0)
            if best_ask <= 0:
                return {'success': False, 'price': 0, 'message': '유효하지 않은 매도1호가'}

            return {'success': True, 'price': best_ask, 'raw': quote, 'message': '매도1호가 조회 성공'}
        except Exception as e:
            return {'success': False, 'price': 0, 'message': f'호가 조회 중 예외: {str(e)}'}
    
    def _get_holding_period(self, stock_code, current_quantity):
        """보유기간 계산 (OrderHistoryManager 사용) - A 프리픽스 유무와 관계없이 매칭"""
        try:
            # OrderHistoryManager를 사용하여 보유기간 계산 (A 프리픽스 유무와 관계없이 매칭)
            holding_days = self.order_history_manager.get_holding_period(stock_code, current_quantity)
            
            # -1이면 체결일 수집 안됨, 0 이상이면 실제 보유일수
            if holding_days == -1:
                self._get_logger().warning(f"⚠️ {stock_code} 종목의 체결일이 수집되지 않았습니다.")
                return 0  # 자동매매에서는 0으로 처리 (매도 조건에서 제외)
            
            return holding_days
            
        except Exception as e:
            self._get_logger().error(f"보유기간 계산 중 오류: {e}")
            return 0
    

    def execute_strategy_with_candidates(self, analysis_result, manual_execution=True):
        """팝업에서 매매실행 버튼 클릭 시 호출"""
        if self.is_running:
            return {
                'success': False,
                'message': '이미 실행 중입니다.'
            }
        
        # 실행 가능 여부 확인
        can_execute, message = self.can_execute(manual_execution)
        if not can_execute:
            return {
                'success': False,
                'message': message
            }
        
        self.is_running = True
        self.current_status = "시작 중"
        self.progress_percentage = 0
        
        try:
            self._get_logger().info("🤖 자동매매 전략 실행을 시작합니다 (팝업에서 실행)...")
            
            # 0. 토큰 유효성 확인 및 자동 발급
            self.current_status = "토큰 확인 중"
            self.progress_percentage = 5
            token = self.auth.get_access_token()
            
            if not token:
                return {
                    'success': False,
                    'message': '토큰 발급 실패'
                }
            
            # 1. 계좌 정보 조회
            self.current_status = "계좌 정보 조회 중"
            self.progress_percentage = 15
            account_info = self._get_account_info()
            
            # 2. 설정 로드
            config = self.config_manager.load_config()
            strategy_params = config.get('strategy_params', {})
            
            # 3. 공통 매매 로직 실행
            trading_results = self._execute_trading_orders(
                analysis_result,
                account_info,
                strategy_params
            )
            
            # 4. 실행 결과 로그 기록
            sell_count = trading_results['sell_count']
            buy_count = trading_results['buy_count']
            sell_results = trading_results['sell_results']
            buy_results = trading_results['buy_results']
            
            # 성공/실패 메시지 생성
            if buy_count > 0 or sell_count > 0:
                message = f"[수동] 매수 {buy_count}건, 매도 {sell_count}건 실행 완료"
                status = "success"
            else:
                message = f"[수동] 매수 실패: {buy_results.get('total_attempts', 0)}개 종목 중 {buy_count}건 성공"
                status = "failed"
            
            # 실행 결과 로그 기록
            self.config_manager.log_execution(
                status=status,
                buy_count=buy_count,
                sell_count=sell_count,
                message=message,
                strategy_params=strategy_params,
                buy_candidates=trading_results.get('buy_candidates'),
                sell_candidates=trading_results.get('sell_candidates'),
                execution_type="수동",
                buy_results=buy_results,
                sell_results=sell_results,
                account_info=account_info
            )
            
            return {
                'success': True,
                'message': message,
                'sell_count': sell_count,
                'buy_count': buy_count,
                'sell_results': sell_results,
                'buy_results': buy_results
            }
        
        except Exception as e:
            self._get_logger().error(f"자동매매 실행 중 오류: {e}")
            return {
                'success': False,
                'message': f'자동매매 실행 중 오류가 발생했습니다: {str(e)}'
            }
        finally:
            self.is_running = False
            self.current_status = "완료"
            self.progress_percentage = 100

    def stop_trading(self):
        """자동매매 중지"""
        self.is_running = False
        self._get_logger().info("🛑 자동매매가 중지되었습니다.")
        return {
            'success': True,
            'message': '자동매매가 중지되었습니다.'
        }


# 전역 인스턴스들 (서버별)
mock_engine = AutoTradingEngine('mock')
real_engine = AutoTradingEngine('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
auto_trading_engine = mock_engine
