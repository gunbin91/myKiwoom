# -*- coding: utf-8 -*-
"""
매수 체결내역 수집 및 관리 모듈
"""
import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from src.api.account import KiwoomAccount
from src.utils.logger import get_current_system_logger

logger = get_current_system_logger()


class OrderHistoryManager:
    """매수 체결내역 수집 및 관리 클래스"""
    
    def __init__(self, server_type: str):
        self.server_type = server_type
        self.account = KiwoomAccount(server_type)
        self.data_dir = os.path.join('data', 'order_history', server_type)
        self.data_file = os.path.join(self.data_dir, 'order_history.json')
        self.meta_file = os.path.join(self.data_dir, 'meta.json')
        
        # 디렉토리 생성
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 메모리 캐시
        self.orders_data = []
        self.stock_index = {}
        self.last_update = None
        
        # 로드된 데이터가 있는지 확인
        self._load_data()
    
    def _load_data(self):
        """파일에서 데이터 로드"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.orders_data = data.get('orders', [])
                    self.stock_index = data.get('stock_index', {})
                    self.last_update = data.get('last_update')
                    logger.info(f"📁 {self.server_type} 서버 체결내역 데이터 로드 완료: {len(self.orders_data)}개 주문")
            else:
                logger.info(f"📁 {self.server_type} 서버 체결내역 데이터 파일이 없습니다. 새로 생성합니다.")
        except Exception as e:
            logger.error(f"🚨 체결내역 데이터 로드 실패: {e}")
            self.orders_data = []
            self.stock_index = {}
            self.last_update = None
    
    def _save_data(self):
        """데이터를 파일에 저장"""
        try:
            data = {
                'orders': self.orders_data,
                'stock_index': self.stock_index,
                'last_update': datetime.now().isoformat(),
                'server_type': self.server_type
            }
            
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"💾 {self.server_type} 서버 체결내역 데이터 저장 완료: {len(self.orders_data)}개 주문")
        except Exception as e:
            logger.error(f"🚨 체결내역 데이터 저장 실패: {e}")
    
    def _update_stock_index(self, new_orders: List[Dict]):
        """종목별 인덱스 업데이트"""
        # 기존 인덱스 초기화 후 전체 데이터로 다시 빌드
        self.stock_index = {}
        for i, order in enumerate(self.orders_data):
            stock_code = order['stock_code']
            if stock_code not in self.stock_index:
                self.stock_index[stock_code] = []
            self.stock_index[stock_code].append(i)
        logger.debug(f"인덱스 업데이트 완료. {len(self.stock_index)}개 종목")
    
    def _fetch_orders_for_date(self, date_str: str, max_retries: int = 3) -> List[Dict]:
        """특정 날짜의 매수 체결내역 조회"""
        for attempt in range(max_retries):
            try:
                logger.info(f"📅 {date_str} 매수 체결내역 조회 시도 ({attempt + 1}/{max_retries})")
                
                # kt00007 API 호출 - 매수만 조회
                result = self.account.get_executed_orders_history(
                    order_date=date_str,  # 주문일자
                    query_type="4",       # 체결내역만
                    sell_type="2",         # 매수만
                    exchange="KRX"         # 한국거래소
                )
                
                if result and result.get('success'):
                    # API 응답에서 직접 acnt_ord_cntr_prps_dtl 가져오기
                    orders = result.get('acnt_ord_cntr_prps_dtl', [])
                    
                    # acnt_ord_cntr_prps_dtl 배열 길이로 데이터 존재 여부 판단
                    if len(orders) == 0:
                        logger.info(f"ℹ️ {date_str} 체결내역 없음: acnt_ord_cntr_prps_dtl 배열이 비어있음")
                        return []
                    
                    logger.info(f"🔍 {date_str} API 응답: {len(orders)}개 주문 데이터 수신")
                    
                    # 데이터 정규화
                    normalized_orders = []
                    for order in orders:
                        # 매수 주문만 필터링 (io_tp_nm에 "매수"가 포함된 경우)
                        if '매수' in order.get('io_tp_nm', ''):
                            # A 프리픽스 유지 (보유종목과 매칭을 위해)
                            stock_code = order.get('stk_cd', '')
                            # A 프리픽스가 없으면 추가
                            if not stock_code.startswith('A'):
                                stock_code = 'A' + stock_code
                            
                            normalized_order = {
                                'date': date_str,
                                'stock_code': stock_code,
                                'stock_name': order.get('stk_nm', ''),
                                'order_no': order.get('ord_no', ''),
                                'quantity': int(order.get('cntr_qty', '0')),
                                'price': int(order.get('cntr_uv', '0')),
                                'time': order.get('cnfm_tm', ''),
                                'order_type': order.get('io_tp_nm', ''),
                                'exchange': order.get('dmst_stex_tp', 'KRX')
                            }
                            normalized_orders.append(normalized_order)
                    
                    logger.info(f"✅ {date_str} 매수 체결내역 {len(normalized_orders)}개 조회 완료")
                    return normalized_orders
                else:
                    error_msg = result.get('return_msg', '알 수 없는 오류') if result else 'API 응답 없음'
                    logger.warning(f"⚠️ {date_str} 매수 체결내역 조회 실패: {error_msg}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(2)  # 2초 대기 후 재시도
                        continue
                    else:
                        return []
                        
            except Exception as e:
                logger.error(f"🚨 {date_str} 매수 체결내역 조회 중 오류: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                else:
                    return []
        
        return []
    
    def _get_holding_stocks(self) -> List[str]:
        """현재 보유종목 코드 목록 조회"""
        try:
            # kt00004 계좌평가현황요청으로 보유종목 조회
            result = self.account.get_account_evaluation()
            
            logger.info(f"🔍 보유종목 조회 API 응답: {result}")
            
            if result and result.get('success'):
                # kt00004 API 응답 구조에 맞게 수정: stk_acnt_evlt_prst 배열 사용
                stocks = result.get('stk_acnt_evlt_prst', [])
                if not stocks:
                    # stk_acnt_evlt_prst가 없으면 stk_cntr_remn도 확인
                    stocks = result.get('stk_cntr_remn', [])
                
                if stocks:
                    stock_codes = []
                    for stock in stocks:
                        stock_code = stock.get('stk_cd', '')
                        # rmnd_qty (잔고수량) 필드 사용
                        remaining_qty = int(stock.get('rmnd_qty', '0'))
                        
                        # A 프리픽스 유지 (일관성을 위해)
                        # A 프리픽스가 없으면 추가
                        if not stock_code.startswith('A'):
                            stock_code = 'A' + stock_code
                        
                        # 수량이 0보다 큰 종목만 포함
                        if stock_code and remaining_qty > 0:
                            stock_codes.append(stock_code)
                            logger.debug(f"보유종목 추가: {stock_code} (수량: {remaining_qty})")
                    
                    logger.info(f"📊 현재 보유종목 {len(stock_codes)}개 조회 완료: {stock_codes}")
                    return stock_codes
                else:
                    logger.info("📊 현재 보유종목이 없습니다.")
                    return []
            else:
                logger.warning(f"⚠️ 보유종목 조회 실패 - 응답: {result}")
                return []
                
        except Exception as e:
            logger.error(f"🚨 보유종목 조회 중 오류: {e}")
            import traceback
            logger.error(f"   📍 스택 트레이스: {traceback.format_exc()}")
            return []
    
    def collect_order_history(self, max_days: int = 30) -> bool:
        """매수 체결내역 수집 (보유종목 기준으로 최적화)"""
        try:
            logger.info(f"🚀 {self.server_type} 서버 매수 체결내역 수집 시작")
            
            # 현재 보유종목 조회
            holding_stocks = self._get_holding_stocks()
            if not holding_stocks:
                logger.info("📊 보유종목이 없어 체결내역 수집을 건너뜁니다.")
                # 빈 데이터로 파일 저장 (보유기간 계산을 위해)
                self.orders_data = []
                self.stock_index = {}
                self._save_data()
                return True
            
            logger.info(f"📊 보유종목 {len(holding_stocks)}개: {holding_stocks}")
            
            # 수집할 날짜 범위 결정
            today = datetime.now()
            if self.last_update:
                # 기존 데이터가 있으면 마지막 업데이트 날짜 + 1일부터 오늘까지 (역순)
                try:
                    last_update_date = datetime.fromisoformat(self.last_update.replace('Z', '+00:00')).date()
                    # 마지막 업데이트가 오늘보다 미래인 경우 오늘부터 시작
                    if last_update_date >= today.date():
                        start_date = today.date() - timedelta(days=max_days - 1)
                        logger.info(f"📅 마지막 업데이트가 미래이므로 신규 수집: {start_date} ~ {today.date()} (역순)")
                    else:
                        start_date = last_update_date + timedelta(days=1)
                        # 최대 30일 이전까지만 수집
                        max_start_date = today.date() - timedelta(days=max_days - 1)
                        start_date = max(start_date, max_start_date)
                        logger.info(f"📅 기존 데이터 업데이트: {start_date} ~ {today.date()} (역순)")
                except ValueError:
                    # 날짜 파싱 실패 시 신규 수집
                    start_date = today.date() - timedelta(days=max_days - 1)
                    logger.info(f"📅 날짜 파싱 실패로 신규 수집: {start_date} ~ {today.date()} (역순)")
            else:
                # 새로 수집하는 경우 오늘부터 역순으로 최대 30일
                start_date = today.date() - timedelta(days=max_days - 1)
                logger.info(f"📅 신규 데이터 수집: {start_date} ~ {today.date()} (역순)")
            
            logger.info(f"🔍 수집 대상 보유종목: {holding_stocks}")
            logger.info(f"📅 수집 기간: {start_date} ~ {today.date()}")
            
            # 날짜별로 체결내역 수집 (오늘부터 역순으로)
            collected_orders = []
            current_date = today.date()  # 오늘부터 시작
            found_stocks = set()  # 찾은 보유종목 추적
            
            while current_date >= start_date:
                date_str = current_date.strftime('%Y%m%d')
                
                # 해당 날짜의 체결내역 조회
                daily_orders = self._fetch_orders_for_date(date_str)
                
                if daily_orders:
                    # 매수 주문에서 보유종목 확인
                    for order in daily_orders:
                        if order['stock_code'] in holding_stocks:
                            found_stocks.add(order['stock_code'])
                            logger.info(f"🔍 {date_str} {order['stock_code']} 매수 주문 발견")
                    
                    collected_orders.extend(daily_orders)
                
                # API 호출 간격 (429 오류 방지)
                time.sleep(0.5)
                
                # 모든 보유종목의 매수 주문을 찾았으면 수집 종료
                if len(found_stocks) == len(holding_stocks):
                    logger.info(f"✅ 모든 보유종목({len(holding_stocks)}개)의 매수 주문을 찾았습니다. 수집 종료.")
                    break
                
                current_date -= timedelta(days=1)  # 역순으로 진행
            
            # 수집된 데이터를 기존 데이터에 추가
            if collected_orders:
                # 중복 제거 (주문번호 기준)
                existing_order_nos = {order['order_no'] for order in self.orders_data}
                new_orders = [order for order in collected_orders if order['order_no'] not in existing_order_nos]
                
                if new_orders:
                    # 날짜순으로 정렬 (오래된 것부터)
                    new_orders.sort(key=lambda x: (x['date'], x['time']))
                    
                    # 기존 데이터에 추가
                    self.orders_data.extend(new_orders)
                    
                    # 인덱스 업데이트
                    self._update_stock_index(new_orders)
                    
                    logger.info(f"✅ {self.server_type} 서버 체결내역 수집 완료: {len(new_orders)}개 새 주문 추가")
                else:
                    logger.info(f"ℹ️ {self.server_type} 서버 새로운 체결내역이 없습니다.")
            else:
                logger.info(f"ℹ️ {self.server_type} 서버 수집된 체결내역이 없습니다.")
            
            # 수집 완료 후 항상 파일 저장 (빈 데이터라도)
            self._save_data()
            
            return True
            
        except Exception as e:
            logger.error(f"🚨 {self.server_type} 서버 체결내역 수집 실패: {e}")
            import traceback
            logger.error(f"   📍 스택 트레이스: {traceback.format_exc()}")
            return False
    
    def get_holding_period(self, stock_code: str, current_quantity: int) -> int:
        """특정 종목의 보유기간 계산 (일 단위)"""
        try:
            # 1차: 원본 코드로 검사
            if stock_code in self.stock_index:
                return self._calculate_holding_period(stock_code, current_quantity)
            
            # 2차: A 프리픽스 변환해서 검사 (양방향)
            if stock_code.startswith('A'):
                # A 프리픽스가 있으면 제거해서 검사
                clean_code = stock_code[1:]
                if clean_code in self.stock_index:
                    return self._calculate_holding_period(clean_code, current_quantity)
            else:
                # A 프리픽스가 없으면 추가해서 검사
                a_code = 'A' + stock_code
                if a_code in self.stock_index:
                    return self._calculate_holding_period(a_code, current_quantity)
            
            return -1  # 체결일 수집 안됨을 의미
            
        except Exception as e:
            logger.error(f"🚨 보유기간 계산 중 오류 (종목: {stock_code}): {e}")
            return 0
    
    def _calculate_holding_period(self, stock_code: str, current_quantity: int) -> int:
        """실제 보유기간 계산 로직"""
        try:
            # 해당 종목의 주문 인덱스들 가져오기
            order_indices = self.stock_index[stock_code]

            # 자동매매는 전량 매수/전량 매도 전제를 두는 경우가 많으므로,
            # 현재 보유기간은 '가장 최근(마지막) 매수 체결일' 기준으로 계산한다.
            # (당일 매도 후 재매수 시, 과거 매수일부터로 잡히는 문제를 방지)
            latest_date = None
            latest_time = ""

            for idx in order_indices:
                if idx >= len(self.orders_data):
                    continue
                order = self.orders_data[idx]
                d = order.get('date')
                t = order.get('time') or ""
                if not d:
                    continue

                if (latest_date is None) or (d > latest_date) or (d == latest_date and t > latest_time):
                    latest_date = d
                    latest_time = t

            # 보유기간 계산
            if latest_date:
                try:
                    purchase_date = datetime.strptime(latest_date, '%Y%m%d').date()
                    today = datetime.now().date()
                    holding_days = (today - purchase_date).days
                    return max(0, holding_days)
                except ValueError:
                    logger.error(f"🚨 날짜 형식 오류: {latest_date}")
                    return 0
            
            return 0
            
        except Exception as e:
            logger.error(f"🚨 보유기간 계산 중 오류 (종목: {stock_code}): {e}")
            return 0
    
    def get_stock_order_history(self, stock_code: str) -> List[Dict]:
        """특정 종목의 매수 체결내역 조회"""
        try:
            if stock_code not in self.stock_index:
                return []
            
            order_indices = self.stock_index[stock_code]
            orders = [self.orders_data[idx] for idx in order_indices if idx < len(self.orders_data)]
            
            # 날짜순으로 정렬 (최신순)
            orders.sort(key=lambda x: (x['date'], x['time']), reverse=True)
            
            return orders
            
        except Exception as e:
            logger.error(f"🚨 종목 체결내역 조회 중 오류 (종목: {stock_code}): {e}")
            return []
    
    def get_data_summary(self) -> Dict[str, Any]:
        """수집된 데이터 요약 정보"""
        return {
            'server_type': self.server_type,
            'total_orders': len(self.orders_data),
            'stock_count': len(self.stock_index),
            'last_update': self.last_update,
            'data_file_exists': os.path.exists(self.data_file)
        }
