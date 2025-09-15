# -*- coding: utf-8 -*-
"""
자동매매 엔진
"""
import sys
import os
import io
import json
from datetime import datetime, timedelta
import pandas as pd

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.utils.deep_learning import deep_learning_analyzer
from src.auto_trading.config_manager import config_manager
from src.api import kiwoom_account, kiwoom_order
from src.utils import web_logger


class AutoTradingEngine:
    """자동매매 엔진 클래스"""
    
    def __init__(self):
        self.config_manager = config_manager
        self.analyzer = deep_learning_analyzer
        self.is_running = False
        self.current_status = "대기 중"
        self.progress_percentage = 0
        
    
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
            web_logger.info("🤖 자동매매 전략 실행을 시작합니다...")
            
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
            
            # 5. 매수 대상 선정
            self.current_status = "매수 대상 선정 중"
            self.progress_percentage = 70
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
            
            # 6. 매수 주문 실행
            self.current_status = "매수 주문 실행 중"
            self.progress_percentage = 85
            web_logger.info("📈 매수 주문을 실행하는 중...")
            buy_results = self._execute_buy_orders(buy_candidates, account_info, strategy_params)
            buy_count = buy_results['success_count']
            
            # 7. 실행 결과 판단 및 이력 기록
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
            deposit_result = kiwoom_account.get_deposit_detail()
            if not deposit_result or deposit_result.get('success') is False:
                return {
                    'success': False,
                    'message': '예수금 정보를 가져올 수 없습니다.'
                }
            
            # 보유 종목 정보
            balance_result = kiwoom_account.get_account_balance_detail()
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
        
        try:
            # 사용 가능한 현금 계산
            available_cash = int(account_info['deposit'].get('entr', 0)) - reserve_cash
            if available_cash <= 0:
                web_logger.warning(f"사용 가능한 현금이 부족합니다. (예수금: {account_info['deposit'].get('entr', 0)}, 예약금: {reserve_cash})")
                return {'success_count': 0}
            
            # 실전에서는 종목당 동일한 금액 투자 (수수료는 자동 차감)
            investment_per_stock = available_cash // len(buy_candidates)
            
            web_logger.info(f"💰 총 투자 가능 금액: {available_cash:,}원")
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
                        web_logger.error(f"❌ {stock_name}({stock_code}) 실시간 가격 조회 실패: {realtime_price_result['message']}")
                        continue
                    
                    realtime_price = realtime_price_result['price']
                    web_logger.info(f"📊 {stock_name}({stock_code}) 실시간 가격: {realtime_price:,}원 (분석시점: {analysis_price:,}원)")
                    
                    # 실시간 가격으로 매수 수량 계산
                    quantity = investment_per_stock // realtime_price
                    
                    if quantity <= 0:
                        web_logger.warning(f"⚠️ {stock_name}({stock_code}) 매수 수량이 0입니다. (투자금액: {investment_per_stock:,}원, 실시간가격: {realtime_price:,}원)")
                        continue
                    
                    # 매수 주문 실행
                    web_logger.info(f"📈 {stock_name}({stock_code}) 매수 주문: {quantity}주 @ {realtime_price:,}원 (투자금액: {investment_per_stock:,}원)")
                    
                    order_result = kiwoom_order.buy_stock(
                        stock_code=stock_code,
                        quantity=quantity,
                        price=0,  # 시장가는 가격을 0으로 설정
                        order_type='3'  # 시장가
                    )
                    
                    if order_result and order_result.get('success') is not False:
                        success_count += 1
                        web_logger.info(f"✅ {stock_name} 매수 주문 성공")
                        # 매수일은 체결내역에서 자동으로 가져옴
                    else:
                        web_logger.warning(f"❌ {stock_name} 매수 주문 실패")
                        
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
    
    def _execute_sell_orders(self, account_info, strategy_params):
        """매도 주문 실행 (백테스팅 로직과 일치)"""
        success_count = 0
        
        try:
            # 보유 종목 조회
            balance_data = account_info['balance']
            if not balance_data or not balance_data.get('bal'):
                return {'success_count': 0}
            
            take_profit_pct = strategy_params.get('take_profit_pct', 5.0)
            stop_loss_pct = strategy_params.get('stop_loss_pct', 3.0)
            max_hold_period = strategy_params.get('max_hold_period', 15)
            
            # 백테스팅과 동일한 매도 조건 계산
            take_profit_multiplier = 1 + (take_profit_pct / 100)
            stop_loss_multiplier = 1 - (stop_loss_pct / 100)
            
            for stock in balance_data['bal']:
                try:
                    stock_code = stock.get('stk_cd', '')
                    stock_name = stock.get('stk_nm', '')
                    quantity = int(stock.get('cntr_qty', 0))
                    avg_price = float(stock.get('avg_prc', 0))
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
                        
                        order_result = kiwoom_order.sell_stock(
                            stock_code=stock_code,
                            quantity=quantity,
                            price=0,  # 시장가는 가격을 0으로 설정
                            order_type='3'  # 시장가
                        )
                        
                        if order_result and order_result.get('success') is not False:
                            success_count += 1
                            web_logger.info(f"✅ {stock_name} 매도 주문 성공")
                            # 매도 기록은 체결내역에서 자동으로 관리됨
                        else:
                            web_logger.warning(f"❌ {stock_name} 매도 주문 실패")
                            
                except Exception as e:
                    web_logger.error(f"매도 주문 실행 중 오류: {e}")
                    continue
            
            return {'success_count': success_count}
            
        except Exception as e:
            web_logger.error(f"매도 주문 실행 중 오류: {e}")
            return {'success_count': success_count}
    
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
            
            # 7. 유효한 종목 수 확인
            if len(valid_stocks) < 3:
                return {
                    'success': False,
                    'message': f"유효한 종목이 부족합니다. (유효: {len(valid_stocks)}개, 무효: {len(invalid_stocks)}개)"
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
            
            # 최소 매수 대상 수 확인
            if len(buy_candidates) < 1:
                return {
                    'success': False,
                    'message': "매수 대상 종목이 1개 미만입니다."
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
            from src.api.quote import kiwoom_quote
            
            # 키움 API로 실시간 현재가 조회
            quote_result = kiwoom_quote.get_current_price(stock_code)
            
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
            from src.api.order import kiwoom_order
            
            # 최근 30일간의 체결내역 조회
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
            
            # 체결내역 조회 (매수만)
            order_history = kiwoom_order.get_order_history(
                start_date=start_date,
                end_date=end_date,
                stock_code=stock_code,
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
            
            # 5. 매수 주문 실행
            self.current_status = "매수 주문 실행 중"
            self.progress_percentage = 85
            web_logger.info("📈 매수 주문을 실행하는 중...")
            buy_results = self._execute_buy_orders(validated_candidates, account_info, strategy_params)
            buy_count = buy_results['success_count']
            
            # 6. 실행 결과 판단 및 이력 기록
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
            
            # 7. 완료
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


# 전역 인스턴스
auto_trading_engine = AutoTradingEngine()
