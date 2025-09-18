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
from src.utils import web_logger


class AutoTradingEngine:
    """자동매매 엔진 클래스"""
    
    def __init__(self, server_type='mock'):
        self.server_type = server_type
        self.config_manager = AutoTradingConfigManager(server_type)
        self.analyzer = deep_learning_analyzer
        self.is_running = False
        self.current_status = "대기 중"
        self.progress_percentage = 0
        
        # 서버 타입에 맞는 API 인스턴스 생성
        self.auth = KiwoomAuth(server_type)
        self.account = KiwoomAccount(server_type)
        self.quote = KiwoomQuote(server_type)
        self.order = KiwoomOrder(server_type)
        
    
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
    
    def execute_strategy(self, manual_execution=False):
        """자동매매 전략 실행"""
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
        buy_count = 0
        sell_count = 0
        
        try:
            web_logger.info(f"🤖 자동매매 전략 실행을 시작합니다... (서버: {self.server_type})")
            
            # 0. 토큰 유효성 확인 및 자동 발급
            self.current_status = "토큰 확인 중"
            self.progress_percentage = 5
            try:
                token = self.auth.get_access_token()
                if not token:
                    web_logger.info(f"토큰이 없습니다. 새로 발급받습니다... (서버: {self.server_type})")
                    token = self.auth.get_access_token(force_refresh=True)
                    if not token:
                        return {
                            'success': False,
                            'message': '토큰 발급에 실패했습니다. 로그인을 다시 시도해주세요.'
                        }
                web_logger.info(f"토큰 확인 완료 (서버: {self.server_type})")
            except Exception as e:
                web_logger.error(f"🚨 토큰 확인 실패: {e}")
                web_logger.error(f"   📍 서버 타입: {self.server_type}")
                import traceback
                web_logger.error(f"   📍 스택 트레이스: {traceback.format_exc()}")
                return {
                    'success': False,
                    'message': f'토큰 확인 실패: {str(e)}'
                }
            
            # 1. 설정 로드
            self.current_status = "설정 로드 중"
            self.progress_percentage = 10
            config = self.config_manager.load_config()
            strategy_params = config.get('strategy_params', {})
            
            web_logger.info(f"📋 전략 파라미터: {strategy_params}")
            
            # 2. 계좌 정보 확인
            self.current_status = "계좌 정보 확인 중"
            self.progress_percentage = 20
            web_logger.info("💰 계좌 정보를 확인하는 중...")
            account_info = self._get_account_info()
            if not account_info['success']:
                return {
                    'success': False,
                    'message': f"계좌 정보 확인 실패: {account_info['message']}"
                }
            
            # 3. 종목 분석
            self.current_status = "종목 분석 중"
            self.progress_percentage = 40
            web_logger.info("🔍 종목 분석을 실행하는 중...")
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔍 종목 분석을 실행하는 중...")
            analysis_result = self.analyzer.get_stock_analysis()
            
            # 🔥 핵심 수정: 분석 결과 검증 강화
            validation_result = self._validate_analysis_result(analysis_result)
            if not validation_result['success']:
                error_message = f"분석 결과 검증 실패: {validation_result['message']}"
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ {error_message}")
                return {
                    'success': False,
                    'message': error_message
                }
            
            # 4. 매도 주문 실행 (기존 보유 종목) - 백테스팅과 동일하게 매도 먼저
            self.current_status = "매도 주문 실행 중"
            self.progress_percentage = 60
            web_logger.info("📉 매도 주문을 실행하는 중...")
            sell_results = self._execute_sell_orders(account_info, strategy_params)
            sell_count = sell_results['success_count']
            sell_orders = sell_results.get('sell_orders', [])
            
            # 5. 매도 체결 확인 및 대기
            if sell_count > 0 and sell_orders:
                self.current_status = "매도 체결 확인 중"
                self.progress_percentage = 65
                web_logger.info("⏳ 매도 주문 체결을 확인하는 중...")
                
                # 매도 체결 확인 (최대 30초 대기)
                execution_confirmed = self._wait_for_sell_execution(sell_orders, max_wait_time=30)
                
                if execution_confirmed:
                    web_logger.info("✅ 매도 체결 확인 완료")
                else:
                    web_logger.warning("⚠️ 매도 체결 확인 시간 초과, 계속 진행합니다.")
            
            # 6. 매도 후 계좌 정보 재조회 (매도로 확보된 현금 반영)
            if sell_count > 0:
                self.current_status = "매도 후 계좌 정보 조회 중"
                self.progress_percentage = 70
                web_logger.info("💰 매도 후 계좌 정보를 재조회하는 중...")
                
                # 계좌 정보 재조회
                updated_account_info = self._get_account_info()
                if updated_account_info:
                    account_info = updated_account_info
                    web_logger.info("✅ 매도 후 계좌 정보 업데이트 완료")
                else:
                    web_logger.warning("⚠️ 매도 후 계좌 정보 조회 실패, 기존 정보 사용")
            
            # 7. 매수 대상 선정
            self.current_status = "매수 대상 선정 중"
            self.progress_percentage = 75
            web_logger.info("📊 매수 대상을 선정하는 중...")
            buy_candidates = self.analyzer.get_top_stocks(
                analysis_result,
                top_n=strategy_params.get('top_n', 5),
                buy_universe_rank=strategy_params.get('buy_universe_rank', 20)
            )
            
            # 🔥 핵심 수정: 매수 대상 검증
            buy_validation = self._validate_buy_candidates(buy_candidates)
            if not buy_validation['success']:
                web_logger.warning(f"매수 대상 검증 실패: {buy_validation['message']}")
                self.current_status = "완료"
                self.progress_percentage = 100
                return {
                    'success': True,
                    'message': f'매수 대상 검증 실패로 실행을 건너뜁니다: {buy_validation["message"]}',
                    'buy_count': 0,
                    'sell_count': sell_count
                }
            
            # 검증된 매수 대상 사용
            buy_candidates = buy_validation['valid_candidates']
            web_logger.info(f"✅ {len(buy_candidates)}개 매수 대상 선정 및 검증 완료")
            
            # 8. 매수 주문 실행 (매도 후 업데이트된 계좌 정보 사용)
            self.current_status = "매수 주문 실행 중"
            self.progress_percentage = 85
            web_logger.info("📈 매수 주문을 실행하는 중...")
            buy_results = self._execute_buy_orders(buy_candidates, account_info, strategy_params)
            buy_count = buy_results['success_count']
            
            # 9. 실행 결과 판단 및 이력 기록
            self.current_status = "이력 기록 중"
            self.progress_percentage = 95
            execution_type = "수동" if manual_execution else "자동"
            
            # 매수 대상이 있었는데 실제 매수가 0건이면 실패로 간주
            if len(buy_candidates) > 0 and buy_count == 0:
                status = 'failed'
                message = f"[{execution_type}] 매수 실패: {len(buy_candidates)}개 종목 중 0건 성공 (현재가 정보 부족)"
                web_logger.error(f"❌ 자동매매 실행 실패: {message}")
                print(f"❌ 자동매매 실행 실패: {message}")
            else:
                status = 'success'
                message = f"[{execution_type}] 매수 {buy_count}건, 매도 {sell_count}건 실행"
                web_logger.info(f"✅ 자동매매 전략 실행 완료 (매수: {buy_count}건, 매도: {sell_count}건)")
            
            self.config_manager.log_execution(
                status=status,
                buy_count=buy_count,
                sell_count=sell_count,
                message=message
            )
            
            # 8. 완료
            self.current_status = "완료"
            self.progress_percentage = 100
            
            return {
                'success': status == 'success',
                'message': message,
                'buy_count': buy_count,
                'sell_count': sell_count,
                'buy_candidates': buy_candidates
            }
            
        except Exception as e:
            web_logger.error(f"🚨 자동매매 실행 중 오류 발생: {e}")
            web_logger.error(f"   📍 서버 타입: {self.server_type}")
            web_logger.error(f"   📍 실행 타입: {'수동' if manual_execution else '자동'}")
            import traceback
            web_logger.error(f"   📍 스택 트레이스: {traceback.format_exc()}")
            execution_type = "수동" if manual_execution else "자동"
            self.config_manager.log_execution(
                status='error',
                buy_count=buy_count,
                sell_count=sell_count,
                message=f"[{execution_type}] 오류: {str(e)}"
            )
            return {
                'success': False,
                'message': f'자동매매 실행 중 오류가 발생했습니다: {str(e)}',
                'buy_count': buy_count,
                'sell_count': sell_count
            }
        finally:
            self.is_running = False
            if self.current_status != "완료":
                self.current_status = "오류 발생"
                self.progress_percentage = 0
    
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
    
    def _execute_buy_orders(self, buy_candidates, account_info, strategy_params):
        """매수 주문 실행 (실시간 시장가 기준)"""
        success_count = 0
        reserve_cash = strategy_params.get('reserve_cash', 1000000)
        transaction_fee_rate = strategy_params.get('transaction_fee_rate', 0.015)
        
        try:
            # 예수금 정보 상세 로그
            total_deposit = int(account_info['deposit'].get('entr', 0))
            web_logger.info(f"💰 총 예수금: {total_deposit:,}원")
            web_logger.info(f"💰 매매제외예수금: {reserve_cash:,}원")
            
            # 사용 가능한 현금 계산
            available_cash = total_deposit - reserve_cash
            web_logger.info(f"💰 사용 가능한 현금: {available_cash:,}원 (총예수금 - 매매제외예수금)")
            
            if available_cash <= 0:
                web_logger.warning(f"사용 가능한 현금이 부족합니다. (예수금: {total_deposit:,}, 예약금: {reserve_cash:,})")
                return {'success_count': 0}
            
            # 실전에서는 종목당 동일한 금액 투자 (수수료 고려)
            investment_per_stock = available_cash // len(buy_candidates)
            
            web_logger.info(f"📊 매수 대상 종목 수: {len(buy_candidates)}개")
            web_logger.info(f"📊 종목당 투자 금액: {investment_per_stock:,}원")
            
            for candidate in buy_candidates:
                try:
                    stock_code = candidate.get('종목코드', '')
                    stock_name = candidate.get('종목명', '')
                    analysis_price = candidate.get('현재가', 0)  # 분석 시점 가격 (참고용)
                    
                    if not stock_code:
                        web_logger.error(f"❌ 종목코드가 없습니다: {candidate}")
                        continue
                    
                    # 🔥 핵심 수정: 키움 API로 실시간 현재가 조회
                    web_logger.info(f"📡 {stock_name}({stock_code}) 실시간 현재가 조회 중...")
                    realtime_price_result = self._get_realtime_price(stock_code)
                    
                    if not realtime_price_result['success']:
                        # 실시간 가격 조회 실패 시 분석 시점 가격 사용
                        if analysis_price > 0:
                            realtime_price = analysis_price
                            web_logger.warning(f"⚠️ {stock_name}({stock_code}) 실시간 가격 조회 실패, 분석 시점 가격 사용: {analysis_price:,}원")
                        else:
                            web_logger.error(f"❌ {stock_name}({stock_code}) 가격 정보 없음 (실시간: {realtime_price_result['message']}, 분석시점: {analysis_price})")
                            continue
                    else:
                        realtime_price = realtime_price_result['price']
                        web_logger.info(f"📊 {stock_name}({stock_code}) 실시간 가격: {realtime_price:,}원 (분석시점: {analysis_price:,}원)")
                    
                    # 수수료를 고려한 매수 수량 계산
                    effective_price = realtime_price * (1 + transaction_fee_rate / 100)
                    quantity = int(investment_per_stock // effective_price)
                    
                    if quantity <= 0:
                        web_logger.warning(f"⚠️ {stock_name}({stock_code}) 매수 수량이 0입니다. (투자금액: {investment_per_stock:,}원, 실시간가격: {realtime_price:,}원)")
                        continue
                    
                    # 매수 주문 실행 (재시도 로직 포함)
                    web_logger.info(f"📈 {stock_name}({stock_code}) 매수 주문: {quantity}주 @ {realtime_price:,}원 (투자금액: {investment_per_stock:,}원)")
                    
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
                            price=0,  # 시장가는 가격을 0으로 설정
                            order_type='3'  # 시장가
                        )
                        
                        if order_result and order_result.get('success') is not False:
                            order_success = True
                            success_count += 1
                            web_logger.info(f"✅ {stock_name} 매수 주문 성공")
                            break
                        else:
                            if retry < max_retries - 1:
                                web_logger.warning(f"⚠️ {stock_name} 매수 주문 실패, {retry + 1}초 후 재시도...")
                                time.sleep(1)  # 1초 대기 후 재시도
                            else:
                                web_logger.error(f"❌ {stock_name} 매수 주문 최종 실패 (재시도 {max_retries}회 완료)")
                    
                    if not order_success:
                        continue
                        
                except Exception as e:
                    web_logger.error(f"매수 주문 실행 중 오류: {e}")
                    continue
            
            # 매수 실패 원인 분석
            if success_count == 0 and len(buy_candidates) > 0:
                web_logger.error(f"❌ 모든 매수 주문이 실패했습니다. 총 {len(buy_candidates)}개 종목 중 0건 성공")
                print(f"❌ 모든 매수 주문이 실패했습니다. 총 {len(buy_candidates)}개 종목 중 0건 성공")
                
                # 실패 원인 상세 분석
                missing_price_count = 0
                for candidate in buy_candidates:
                    if candidate.get('현재가', 0) <= 0:
                        missing_price_count += 1
                
                if missing_price_count > 0:
                    web_logger.error(f"❌ 실패 원인: {missing_price_count}개 종목에 현재가 정보가 없습니다.")
                    print(f"❌ 실패 원인: {missing_price_count}개 종목에 현재가 정보가 없습니다.")
            
            return {'success_count': success_count}
            
        except Exception as e:
            web_logger.error(f"매수 주문 실행 중 오류: {e}")
            print(f"❌ 매수 주문 실행 중 오류: {e}")
            return {'success_count': success_count}
    
    def _wait_for_sell_execution(self, sell_orders, max_wait_time=30):
        """매도 주문 체결 대기 및 확인"""
        import time
        from datetime import datetime, timedelta
        
        if not sell_orders:
            return True
        
        web_logger.info(f"📋 {len(sell_orders)}건의 매도 주문 체결을 확인하는 중...")
        
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
                                web_logger.info(f"✅ {stock_code} 매도 체결 확인: {execution.get('cntr_qty')}주")
                                break
                    
                    if executed_count >= len(sell_orders):
                        web_logger.info(f"✅ 모든 매도 주문 체결 확인 완료: {executed_count}/{len(sell_orders)}건")
                        return True
                    else:
                        web_logger.info(f"⏳ 매도 체결 대기 중: {executed_count}/{len(sell_orders)}건 체결")
                
                # 3초 대기 후 재확인
                time.sleep(3)
                
            except Exception as e:
                web_logger.warning(f"매도 체결 확인 중 오류: {e}")
                time.sleep(3)
        
        web_logger.warning(f"⚠️ 매도 체결 확인 시간 초과 ({max_wait_time}초), 계속 진행합니다.")
        return False

    def _execute_sell_orders(self, account_info, strategy_params):
        """매도 주문 실행 (백테스팅 로직과 일치)"""
        success_count = 0
        sell_orders = []  # 매도 주문 정보 저장
        
        try:
            # 보유 종목 조회
            balance_data = account_info['balance']
            if not balance_data or not balance_data.get('acnt_evlt_remn_indv_tot'):
                return {'success_count': 0}
            
            take_profit_pct = strategy_params.get('take_profit_pct', 5.0)
            stop_loss_pct = strategy_params.get('stop_loss_pct', 3.0)
            max_hold_period = strategy_params.get('max_hold_period', 15)
            
            # 백테스팅과 동일한 매도 조건 계산
            take_profit_multiplier = 1 + (take_profit_pct / 100)
            stop_loss_multiplier = 1 - (stop_loss_pct / 100)
            
            for stock in balance_data['acnt_evlt_remn_indv_tot']:
                try:
                    stock_code = stock.get('stk_cd', '')
                    stock_name = stock.get('stk_nm', '')
                    quantity = int(stock.get('rmnd_qty', 0))
                    avg_price = float(stock.get('pur_pric', 0))
                    current_price = float(stock.get('cur_prc', 0))
                    
                    if quantity <= 0 or avg_price <= 0 or current_price <= 0:
                        continue
                    
                    # 실전 매도 조건 확인
                    # 1. 익절 조건: 현재가 >= 매수가 * (1 + 익절률)
                    # 2. 손절 조건: 현재가 <= 매수가 * (1 - 손절률)
                    # 3. 보유기간 만료: 매수일로부터 max_hold_period일 경과
                    
                    should_sell = False
                    sell_reason = ""
                    
                    # 익절/손절 조건
                    if current_price >= avg_price * take_profit_multiplier:
                        should_sell = True
                        return_rate = ((current_price - avg_price) / avg_price) * 100
                        sell_reason = f"익절 ({return_rate:.2f}%)"
                    elif current_price <= avg_price * stop_loss_multiplier:
                        should_sell = True
                        return_rate = ((current_price - avg_price) / avg_price) * 100
                        sell_reason = f"손절 ({return_rate:.2f}%)"
                    
                    # 보유기간 만료 조건
                    holding_days = self._get_holding_period(stock_code, quantity)
                    if holding_days >= max_hold_period:
                        should_sell = True
                        sell_reason = f"보유기간 만료 ({holding_days}일)"
                    
                    if should_sell:
                        web_logger.info(f"📉 {stock_name}({stock_code}) 매도 주문: {quantity}주 @ {current_price}원 ({sell_reason})")
                        
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
                            # 매도 주문 정보 저장 (체결 확인용)
                            sell_orders.append({
                                'stock_code': stock_code,
                                'stock_name': stock_name,
                                'quantity': quantity,
                                'price': current_price,
                                'reason': sell_reason
                            })
                            web_logger.info(f"✅ {stock_name} 매도 주문 성공")
                        else:
                            web_logger.warning(f"❌ {stock_name} 매도 주문 실패")
                            
                except Exception as e:
                    web_logger.error(f"매도 주문 실행 중 오류: {e}")
                    continue
            
            return {'success_count': success_count, 'sell_orders': sell_orders}
            
        except Exception as e:
            web_logger.error(f"매도 주문 실행 중 오류: {e}")
            return {'success_count': success_count, 'sell_orders': sell_orders}
    
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
                web_logger.warning(f"⚠️ {len(invalid_stocks)}개 종목의 데이터가 무효합니다:")
                for invalid in invalid_stocks[:5]:  # 최대 5개만 로그
                    web_logger.warning(f"   - {invalid}")
                if len(invalid_stocks) > 5:
                    web_logger.warning(f"   ... 외 {len(invalid_stocks) - 5}개")
            
            web_logger.info(f"✅ 분석 결과 검증 완료: {len(valid_stocks)}개 유효 종목")
            
            return {
                'success': True,
                'message': f"검증 완료: {len(valid_stocks)}개 유효 종목",
                'valid_stocks': valid_stocks,
                'invalid_count': len(invalid_stocks)
            }
            
        except Exception as e:
            web_logger.error(f"분석 결과 검증 중 오류: {e}")
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
                    web_logger.warning(f"⚠️ 매수 대상에서 제외: 기본정보 누락 - {candidate}")
                    continue
                
                valid_candidates.append(candidate)
            
            if not valid_candidates:
                return {
                    'success': False,
                    'message': "유효한 매수 대상이 없습니다."
                }
            
            web_logger.info(f"✅ 매수 대상 검증 완료: {len(valid_candidates)}개 종목")
            
            return {
                'success': True,
                'message': f"검증 완료: {len(valid_candidates)}개 매수 대상",
                'valid_candidates': valid_candidates
            }
            
        except Exception as e:
            web_logger.error(f"매수 대상 검증 중 오류: {e}")
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
            web_logger.error(f"실시간 가격 조회 중 오류: {e}")
            return {
                'success': False,
                'price': 0,
                'message': f'가격 조회 중 예외 발생: {str(e)}'
            }
    
    def _get_holding_period(self, stock_code, current_quantity):
        """보유기간 계산 (체결내역에서 매수일 정보 가져오기)"""
        try:
            # 체결내역에서 매수 정보 가져오기
            # 서버 타입에 맞는 order 인스턴스 사용
            
            # 최근 30일간의 체결내역 조회
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
            
            # 체결내역 조회 (매수만) - 계좌 API용 종목코드로 변환
            from src.api.order import convert_stock_code_for_account
            account_stock_code = convert_stock_code_for_account(stock_code)
            
            order_history = self.order.get_order_history(
                start_date=start_date,
                end_date=end_date,
                stock_code=account_stock_code,  # 변환된 종목코드 사용
                order_type='2'  # 매수만
            )
            
            if not order_history or not order_history.get('acnt_ord_cntr_prps_dtl'):
                return 0
            
            # 현재 보유 수량에 맞는 매수일 계산
            remaining_quantity = current_quantity
            oldest_purchase_date = None
            
            # 체결내역을 날짜순으로 정렬 (오래된 것부터)
            order_list = order_history['acnt_ord_cntr_prps_dtl']
            order_list.sort(key=lambda x: x.get('ord_dt', ''))
            
            for order in order_list:
                if remaining_quantity <= 0:
                    break
                
                cntr_qty = int(order.get('cntr_qty', 0))
                if cntr_qty <= 0:
                    continue
                
                if remaining_quantity >= cntr_qty:
                    remaining_quantity -= cntr_qty
                    oldest_purchase_date = order.get('ord_dt', '')
                else:
                    oldest_purchase_date = order.get('ord_dt', '')
                    break
            
            if oldest_purchase_date:
                # YYYYMMDD 형식을 YYYY-MM-DD로 변환
                purchase_date = datetime.strptime(oldest_purchase_date, '%Y%m%d')
                current_date = datetime.now()
                holding_days = (current_date - purchase_date).days
                return holding_days
            
            return 0
            
        except Exception as e:
            web_logger.error(f"보유기간 계산 중 오류: {e}")
            return 0
    

    def execute_strategy_with_candidates(self, buy_candidates, manual_execution=True):
        """미리 선정된 매수 대상으로 자동매매 실행 (테스트용)"""
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
        buy_count = 0
        sell_count = 0
        
        try:
            web_logger.info("🤖 자동매매 전략 실행을 시작합니다 (미리 선정된 매수 대상)...")
            
            # 1. 설정 로드
            self.current_status = "설정 로드 중"
            self.progress_percentage = 20
            config = self.config_manager.load_config()
            strategy_params = config.get('strategy_params', {})
            
            web_logger.info(f"📋 전략 파라미터: {strategy_params}")
            
            # 2. 계좌 정보 확인
            self.current_status = "계좌 정보 확인 중"
            self.progress_percentage = 40
            web_logger.info("💰 계좌 정보를 확인하는 중...")
            account_info = self._get_account_info()
            if not account_info['success']:
                return {
                    'success': False,
                    'message': f"계좌 정보 확인 실패: {account_info['message']}"
                }
            
            # 3. 매수 대상 검증
            self.current_status = "매수 대상 검증 중"
            self.progress_percentage = 60
            buy_validation = self._validate_buy_candidates(buy_candidates)
            if not buy_validation['success']:
                return {
                    'success': False,
                    'message': f"매수 대상 검증 실패: {buy_validation['message']}"
                }
            
            validated_candidates = buy_validation['valid_candidates']
            web_logger.info(f"✅ {len(validated_candidates)}개 매수 대상 검증 완료")
            
            # 4. 매도 주문 실행 (기존 보유 종목)
            self.current_status = "매도 주문 실행 중"
            self.progress_percentage = 70
            web_logger.info("📉 매도 주문을 실행하는 중...")
            sell_results = self._execute_sell_orders(account_info, strategy_params)
            sell_count = sell_results['success_count']
            sell_orders = sell_results.get('sell_orders', [])
            
            # 5. 매도 체결 확인 및 대기
            if sell_count > 0 and sell_orders:
                self.current_status = "매도 체결 확인 중"
                self.progress_percentage = 75
                web_logger.info("⏳ 매도 주문 체결을 확인하는 중...")
                
                # 매도 체결 확인 (최대 30초 대기)
                execution_confirmed = self._wait_for_sell_execution(sell_orders, max_wait_time=30)
                
                if execution_confirmed:
                    web_logger.info("✅ 매도 체결 확인 완료")
                else:
                    web_logger.warning("⚠️ 매도 체결 확인 시간 초과, 계속 진행합니다.")
            
            # 6. 매도 후 계좌 정보 재조회 (매도로 확보된 현금 반영)
            if sell_count > 0:
                self.current_status = "매도 후 계좌 정보 조회 중"
                self.progress_percentage = 80
                web_logger.info("💰 매도 후 계좌 정보를 재조회하는 중...")
                
                # 계좌 정보 재조회
                updated_account_info = self._get_account_info()
                if updated_account_info:
                    account_info = updated_account_info
                    web_logger.info("✅ 매도 후 계좌 정보 업데이트 완료")
                else:
                    web_logger.warning("⚠️ 매도 후 계좌 정보 조회 실패, 기존 정보 사용")
            
            # 7. 매수 주문 실행 (매도 후 업데이트된 계좌 정보 사용)
            self.current_status = "매수 주문 실행 중"
            self.progress_percentage = 85
            web_logger.info("📈 매수 주문을 실행하는 중...")
            buy_results = self._execute_buy_orders(validated_candidates, account_info, strategy_params)
            buy_count = buy_results['success_count']
            
            # 7. 실행 결과 판단 및 이력 기록
            self.current_status = "이력 기록 중"
            self.progress_percentage = 95
            execution_type = "수동" if manual_execution else "자동"
            
            if len(validated_candidates) > 0 and buy_count == 0:
                status = 'failed'
                message = f"[{execution_type}] 매수 실패: {len(validated_candidates)}개 종목 중 0건 성공"
                web_logger.error(f"❌ 자동매매 실행 실패: {message}")
            else:
                status = 'success'
                message = f"[{execution_type}] 매수 {buy_count}건, 매도 {sell_count}건 실행"
                web_logger.info(f"✅ 자동매매 전략 실행 완료 (매수: {buy_count}건, 매도: {sell_count}건)")
            
            self.config_manager.log_execution(
                status=status,
                buy_count=buy_count,
                sell_count=sell_count,
                message=message
            )
            
            # 8. 완료
            self.current_status = "완료"
            self.progress_percentage = 100
            
            return {
                'success': status == 'success',
                'message': message,
                'buy_count': buy_count,
                'sell_count': sell_count,
                'buy_candidates': validated_candidates
            }
            
        except Exception as e:
            web_logger.error(f"자동매매 실행 중 오류 발생: {e}")
            execution_type = "수동" if manual_execution else "자동"
            self.config_manager.log_execution(
                status='error',
                buy_count=buy_count,
                sell_count=sell_count,
                message=f"[{execution_type}] 오류: {str(e)}"
            )
            return {
                'success': False,
                'message': f'자동매매 실행 중 오류가 발생했습니다: {str(e)}',
                'buy_count': buy_count,
                'sell_count': sell_count
            }
        finally:
            self.is_running = False
            if self.current_status != "완료":
                self.current_status = "오류 발생"
                self.progress_percentage = 0

    def stop_trading(self):
        """자동매매 중지"""
        self.is_running = False
        web_logger.info("🛑 자동매매가 중지되었습니다.")
        return {
            'success': True,
            'message': '자동매매가 중지되었습니다.'
        }


# 전역 인스턴스들 (서버별)
mock_engine = AutoTradingEngine('mock')
real_engine = AutoTradingEngine('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
auto_trading_engine = mock_engine
