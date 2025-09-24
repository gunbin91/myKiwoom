# -*- coding: utf-8 -*-
"""
키움증권 계좌 관련 API 모듈
"""
import sys
import os
import io
from typing import Dict, List, Optional, Any
import requests
from datetime import datetime, timedelta
from src.config.server_config import get_current_server_config
from src.config.settings import API_REQUEST_DELAY
from src.utils import api_logger
from .auth import KiwoomAuth
import time

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'


class KiwoomAccount:
    """키움증권 계좌 관련 API 클래스"""
    
    def __init__(self, server_type: str = None):
        if server_type:
            from src.config.server_config import get_server_config
            self.server_config = get_server_config(server_type)
        else:
            self.server_config = get_current_server_config()
        self.base_url = self.server_config.account_url
        self.server_type = server_type
        
    
    def _make_request(self, api_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API 요청 공통 메서드 (재시도 로직 포함)"""
        from src.config.settings import MAX_RETRY_COUNT
        
        
        for attempt in range(MAX_RETRY_COUNT):
            try:
                # API 호출 간격 지연 (429 오류 방지)
                if attempt > 0:  # 첫 번째 시도가 아닌 경우에만 지연
                    time.sleep(API_REQUEST_DELAY)
                
                # 현재 서버 타입에 맞는 인증 인스턴스 사용
                current_auth = KiwoomAuth(self.server_type)
                headers = current_auth.get_auth_headers()
                headers['api-id'] = api_id
                
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=data,
                    timeout=30
                )
                
                # 429 오류인 경우 재시도
                if response.status_code == 429:
                    if attempt < MAX_RETRY_COUNT - 1:
                        wait_time = (attempt + 1) * 2  # 2초, 4초, 6초 대기
                        api_logger.warning(f"API {api_id} 429 오류, {wait_time}초 후 재시도 ({attempt + 1}/{MAX_RETRY_COUNT})")
                        time.sleep(wait_time)
                        continue
                    else:
                        api_logger.error(f"API {api_id} 최대 재시도 횟수 초과")
                        return None
                
                response.raise_for_status()
                result = response.json()
                
                # return_code 체크 (다른 API 클래스들과 동일한 로직)
                if result.get('return_code') == 0:
                    # 성공 응답에 success 플래그 추가
                    result['success'] = True
                    return result
                else:
                    # API 오류 처리
                    error_msg = result.get('return_msg', '알 수 없는 오류')
                    error_code = result.get('return_code', 'UNKNOWN')
                    api_logger.error(f"API {api_id} 호출 실패: [{error_code}]{error_msg}")
                    
                    # kt00002 실패 시 대체 호출 메시지 추가
                    if api_id == 'kt00002':
                        api_logger.info("🔄 kt00002 실패로 인해 kt00001 예수금 정보로 대체 호출합니다")
                    
                    # 오류 정보를 포함한 결과 반환
                    return {
                        'success': False,
                        'error_code': error_code,
                        'error_message': error_msg,
                        'api_id': api_id
                    }
                    
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRY_COUNT - 1:
                    wait_time = (attempt + 1) * 2
                    api_logger.warning(f"🔄 API {api_id} 요청 실패, {wait_time}초 후 재시도 ({attempt + 1}/{MAX_RETRY_COUNT}): {e}")
                    api_logger.warning(f"   📍 요청 URL: {url}")
                    api_logger.warning(f"   📍 요청 데이터: {data}")
                    time.sleep(wait_time)
                    continue
                else:
                    api_logger.error(f"🚨 API {api_id} 최대 재시도 횟수 초과: {e}")
                    api_logger.error(f"   📍 요청 URL: {url}")
                    api_logger.error(f"   📍 요청 데이터: {data}")
                    # kt00002 실패 시 대체 호출 메시지 추가
                    if api_id == 'kt00002':
                        api_logger.info("🔄 kt00002 실패로 인해 kt00001 예수금 정보로 대체 호출합니다")
                    return None
            except Exception as e:
                api_logger.error(f"🚨 API {api_id} 처리 중 예상치 못한 오류: {e}")
                api_logger.error(f"   📍 요청 URL: {url}")
                api_logger.error(f"   📍 요청 데이터: {data}")
                # kt00002 실패 시 대체 호출 메시지 추가
                if api_id == 'kt00002':
                    api_logger.info("🔄 kt00002 실패로 인해 kt00001 예수금 정보로 대체 호출합니다")
                import traceback
                api_logger.error(f"   📍 스택 트레이스: {traceback.format_exc()}")
                return None
        
        return None
    
    def get_deposit_detail(self, query_type: str = "2") -> Optional[Dict[str, Any]]:
        """
        예수금상세현황요청 (kt00001)
        
        Args:
            query_type: 조회구분 ("2": 일반조회, "3": 추정조회)
            
        Returns:
            예수금 상세 정보
        """
        api_logger.info(f"예수금상세현황 조회 (조회구분: {query_type})")
        
        data = {
            'qry_tp': query_type
        }
        
        return self._make_request('kt00001', data)
    
    def get_daily_estimated_deposit_assets(self, start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
        """
        일별추정예탁자산현황요청 (kt00002)
        
        Args:
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            일별 추정예탁자산 현황
        """
        api_logger.info(f"일별추정예탁자산현황 조회 (시작일: {start_date}, 종료일: {end_date})")
        
        data = {
            'start_dt': start_date,
            'end_dt': end_date
        }
        
        return self._make_request('kt00002', data)
    
    def get_estimated_assets(self, query_type: str = "0") -> Optional[Dict[str, Any]]:
        """
        추정자산조회요청 (kt00003)
        
        Args:
            query_type: 상장폐지조회구분 ("0": 전체, "1": 상장폐지종목제외)
            
        Returns:
            추정자산 정보
        """
        api_logger.info(f"추정자산 조회 (조회구분: {query_type})")
        
        data = {
            'qry_tp': query_type
        }
        
        return self._make_request('kt00003', data)
    
    def get_account_evaluation(self, query_type: str = "0", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        계좌평가현황요청 (kt00004)
        
        Args:
            query_type: 상장폐지조회구분 ("0": 전체, "1": 상장폐지종목제외)
            exchange: 국내거래소구분 ("KRX": 한국거래소, "NXT": 넥스트트레이드)
            
        Returns:
            계좌 평가 현황
        """
        api_logger.info(f"계좌평가현황 조회 (조회구분: {query_type}, 거래소: {exchange})")
        
        data = {
            'qry_tp': query_type,
            'dmst_stex_tp': exchange
        }
        
        return self._make_request('kt00004', data)
    
    def get_daily_account_status(self) -> Optional[Dict[str, Any]]:
        """
        계좌별당일현황요청 (kt00017)
        
        Returns:
            당일 계좌 현황
        """
        api_logger.info("계좌별당일현황 조회")
        
        data = {}
        return self._make_request('kt00017', data)
    
    def get_account_balance_detail(self, query_type: str = "0", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        계좌평가잔고내역요청 (kt00018)
        
        Args:
            query_type: 조회구분
            exchange: 국내거래소구분
            
        Returns:
            계좌 평가 잔고 내역
        """
        api_logger.info(f"계좌평가잔고내역 조회 (조회구분: {query_type}, 거래소: {exchange})")
        
        data = {
            'qry_tp': query_type,
            'dmst_stex_tp': exchange
        }
        
        return self._make_request('kt00018', data)
    
    def get_account_profit_rate(self, exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        계좌수익률요청 (ka10085)
        
        Args:
            exchange: 거래소구분
            
        Returns:
            계좌 수익률 정보
        """
        api_logger.info(f"계좌수익률 조회 (거래소: {exchange})")
        
        data = {
            'stex_tp': exchange
        }
        
        return self._make_request('ka10085', data)
    
    def get_daily_balance_profit_rate(self, query_date: str) -> Optional[Dict[str, Any]]:
        """
        일별잔고수익률 (ka01690)
        
        Args:
            query_date: 조회일자 (YYYYMMDD)
            
        Returns:
            일별 잔고 수익률
        """
        api_logger.info(f"일별잔고수익률 조회 (조회일자: {query_date})")
        
        data = {
            'qry_dt': query_date
        }
        
        return self._make_request('ka01690', data)
    
    def get_unexecuted_orders(self, all_stock_type: str = "0", trade_type: str = "0", stock_code: str = "", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        미체결요청 (ka10075)
        
        Args:
            all_stock_type: 전체종목구분
            trade_type: 매매구분
            stock_code: 종목코드 (선택사항)
            exchange: 거래소구분 (KRX: 한국거래소, NXT: 넥스트트레이드)
            
        Returns:
            미체결 주문 내역
        """
        api_logger.info(f"미체결 주문 조회 (전체종목: {all_stock_type}, 매매구분: {trade_type}, 거래소: {exchange})")
        
        data = {
            'all_stk_tp': all_stock_type,
            'trde_tp': trade_type,
            'stex_tp': exchange
        }
        
        if stock_code:
            data['stk_cd'] = stock_code
        
        return self._make_request('ka10075', data)
    
    def get_executed_orders(self, query_type: str = "0", sell_type: str = "0", 
                           start_date: str = "", end_date: str = "", exchange: str = "KRX",
                           stock_code: str = "", from_order_no: str = "") -> Optional[Dict[str, Any]]:
        """
        체결요청 (ka10076) - 수수료/세금 정보 포함된 완전한 API 사용
        
        Args:
            query_type: 조회구분 ("0": 전체, "1": 종목)
            sell_type: 매도수구분 ("0": 전체, "1": 매도, "2": 매수)
            start_date: 시작일자 (YYYYMMDD) - ka10076은 날짜 필터링 미지원
            end_date: 종료일자 (YYYYMMDD) - ka10076은 날짜 필터링 미지원
            exchange: 거래소구분 ("0": 통합, "1": KRX, "2": NXT)
            stock_code: 종목코드 (공백시 전체종목)
            from_order_no: 주문번호 (검색 기준값)
            
        Returns:
            체결 주문 내역 (수수료/세금 정보 포함)
        """
        api_logger.info(f"체결 주문 조회 (조회구분: {query_type}, 매도수구분: {sell_type}, 거래소: {exchange}, 종목: {stock_code})")
        
        data = {
            'qry_tp': query_type,
            'sell_tp': sell_type,
            'stex_tp': exchange
        }
        
        # 종목코드 필터링
        if stock_code:
            data['stk_cd'] = stock_code
        
        # 주문번호 필터링 (검색 기준값)
        if from_order_no:
            data['ord_no'] = from_order_no
        
        return self._make_request('ka10076', data)
    
    def get_executed_orders_history(self, order_date: str = "", query_type: str = "1", 
                                   stock_bond_type: str = "0", sell_type: str = "0",
                                   stock_code: str = "", from_order_no: str = "", 
                                   exchange: str = "%") -> Optional[Dict[str, Any]]:
        """
        계좌별주문체결내역상세요청 (kt00007) - 과거 이력 조회용
        
        Args:
            order_date: 주문일자 (YYYYMMDD, 공백시 전체)
            query_type: 조회구분 ("1": 주문순, "2": 역순, "3": 미체결, "4": 체결내역만)
            stock_bond_type: 주식채권구분 ("0": 전체, "1": 주식, "2": 채권)
            sell_type: 매도수구분 ("0": 전체, "1": 매도, "2": 매수)
            stock_code: 종목코드 (공백시 전체종목)
            from_order_no: 시작주문번호 (공백시 전체주문)
            exchange: 국내거래소구분 ("%": 전체, "KRX": 한국거래소, "NXT": 넥스트트레이드, "SOR": 최선주문집행)
            
        Returns:
            체결 주문 내역 (과거 이력 포함)
        """
        api_logger.info(f"체결 주문 이력 조회 (주문일자: {order_date}, 조회구분: {query_type}, 매도수구분: {sell_type}, 거래소: {exchange}, 종목: {stock_code})")
        
        data = {
            'qry_tp': query_type,
            'stk_bond_tp': stock_bond_type,
            'sell_tp': sell_type,
            'dmst_stex_tp': exchange
        }
        
        # 주문일자 필터링 (kt00007 API는 ord_dt 파라미터 사용)
        if order_date:
            data['ord_dt'] = order_date
        
        # 종목코드 필터링
        if stock_code:
            data['stk_cd'] = stock_code
        
        # 주문번호 필터링
        if from_order_no:
            data['fr_ord_no'] = from_order_no
        
        return self._make_request('kt00007', data)
    
    def get_order_status(self, start_date: str = "", end_date: str = "", 
                        query_type: str = "0", sell_type: str = "0", 
                        stock_code: str = "", from_order_no: str = "",
                        market_type: str = "0", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        계좌별주문체결현황요청 (kt00009) - 통합 주문내역 조회
        
        Args:
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            query_type: 조회구분 ("0": 전체, "1": 체결)
            sell_type: 매도수구분 ("0": 전체, "1": 매도, "2": 매수)
            stock_code: 종목코드 (공백시 전체종목)
            from_order_no: 시작주문번호 (공백시 전체주문)
            market_type: 시장구분 ("0": 전체, "1": 코스피, "2": 코스닥, "3": OTCBB, "4": ECN)
            exchange: 국내거래소구분 ("KRX": 한국거래소, "NXT": 넥스트트레이드, "%": 전체)
            
        Returns:
            통합 주문내역 (체결/미체결 포함)
        """
        api_logger.info(f"계좌별주문체결현황 조회 (조회구분: {query_type}, 매도수구분: {sell_type}, 거래소: {exchange}, 종목: {stock_code})")
        
        data = {
            'qry_tp': query_type,
            'stk_bond_tp': '1',  # 1: 주식만
            'mrkt_tp': market_type,
            'sell_tp': sell_type,
            'dmst_stex_tp': exchange
        }
        
        # 날짜 필터링 (kt00009 API는 ord_dt 파라미터 사용)
        if start_date:
            data['ord_dt'] = start_date
        
        # 종목코드 필터링
        if stock_code:
            data['stk_cd'] = stock_code
        
        # 주문번호 필터링
        if from_order_no:
            data['fr_ord_no'] = from_order_no
        
        return self._make_request('kt00009', data)
    
    def get_today_trading_diary(self, base_date: str = "", odd_lot_type: str = "0", 
                               cash_credit_type: str = "0") -> Optional[Dict[str, Any]]:
        """
        당일매매일지요청 (ka10170)
        
        Args:
            base_date: 기준일자 (YYYYMMDD, 빈 문자열이면 당일)
            odd_lot_type: 단주구분
            cash_credit_type: 현금신용구분
            
        Returns:
            당일 매매일지
        """
        api_logger.info(f"당일매매일지 조회 (기준일자: {base_date or '당일'})")
        
        data = {
            'ottks_tp': odd_lot_type,
            'ch_crd_tp': cash_credit_type
        }
        
        if base_date:
            data['base_dt'] = base_date
        
        return self._make_request('ka10170', data)
    
    def get_account_profit_rate(self, stex_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        계좌수익률요청 (ka10085)
        
        Args:
            stex_tp: 거래소구분 (0: 통합, 1: KRX, 2: NXT)
            
        Returns:
            계좌 수익률 정보
        """
        api_logger.info(f"계좌수익률 조회 (거래소구분: {stex_tp})")
        
        data = {
            'stex_tp': stex_tp
        }
        
        return self._make_request('ka10085', data)
    
    def get_realized_profit_by_period(self, stock_code: str, start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
        """
        일자별종목별실현손익요청_기간 (ka10073)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            일자별 종목별 실현손익 정보
        """
        api_logger.info(f"일자별종목별실현손익 조회 (종목: {stock_code}, 기간: {start_date}~{end_date})")
        
        data = {
            'stk_cd': stock_code,
            'strt_dt': start_date,
            'end_dt': end_date
        }
        
        return self._make_request('ka10073', data)
    
    def get_realized_profit_by_date(self, stock_code: str, start_date: str) -> Optional[Dict[str, Any]]:
        """
        일자별종목별실현손익요청_일자 (ka10072)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            
        Returns:
            특정 일자 종목별 실현손익 정보
        """
        api_logger.info(f"일자별종목별실현손익 조회 (종목: {stock_code}, 시작일자: {start_date})")
        
        data = {
            'stk_cd': stock_code,
            'strt_dt': start_date
        }
        
        return self._make_request('ka10072', data)
    
    def get_daily_realized_profit(self, start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
        """
        일자별실현손익요청 (ka10074)
        
        Args:
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            일자별 실현손익 정보 (실현손익이 발생한 일자에 대해서만 데이터 제공)
        """
        api_logger.info(f"일자별실현손익 조회 (기간: {start_date}~{end_date})")
        
        data = {
            'strt_dt': start_date,
            'end_dt': end_date
        }
        
        return self._make_request('ka10074', data)
    
    def get_daily_realized_profit_detail(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        당일실현손익상세요청 (ka10077)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            당일 실현손익 상세 내역
        """
        api_logger.info(f"당일실현손익상세 조회 (종목: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        return self._make_request('ka10077', data)
    
    def get_trust_overall_trade_history(self, start_date: str, end_date: str, trade_type: str = "3",
                                       stock_code: str = "", goods_type: str = "1", 
                                       domestic_exchange_type: str = "%") -> Optional[Dict[str, Any]]:
        """
        위탁종합거래내역요청 (kt00015)
        
        Args:
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            trade_type: 구분 (3:매매, 4:매수, 5:매도)
            stock_code: 종목코드 (공백:전체)
            goods_type: 상품구분 (1:국내주식)
            domestic_exchange_type: 국내거래소구분 (%:전체)
            
        Returns:
            위탁종합거래내역 정보
        """
        api_logger.info(f"위탁종합거래내역 조회 (기간: {start_date}~{end_date}, 구분: {trade_type}, 종목: {stock_code or '전체'})")
        
        data = {
            'strt_dt': start_date,
            'end_dt': end_date,
            'tp': trade_type,
            'gds_tp': goods_type,
            'dmst_stex_tp': domestic_exchange_type
        }
        
        if stock_code:
            data['stk_cd'] = stock_code
        
        return self._make_request('kt00015', data)
    
    def get_order_possible_amount(self, stock_code: str, price: str, quantity: str) -> Optional[Dict[str, Any]]:
        """
        주문인출가능금액요청 (kt00010)
        
        Args:
            stock_code: 종목번호
            price: 매수가격
            quantity: 매매수량
            
        Returns:
            주문 가능 금액 정보
        """
        api_logger.info(f"주문가능금액 조회 (종목: {stock_code}, 가격: {price}, 수량: {quantity})")
        
        data = {
            'stk_cd': stock_code,
            'uv': price,
            'trde_qty': quantity
        }
        
        return self._make_request('kt00010', data)

    def get_daily_trading_diary(self, base_dt: str = "", ottks_tp: str = "2", ch_crd_tp: str = "0") -> Optional[Dict[str, Any]]:
        """당일매매일지요청 (ka10170)"""
        data = {
            'base_dt': base_dt,
            'ottks_tp': ottks_tp,  # 1:당일매수에 대한 당일매도, 2:당일매도 전체
            'ch_crd_tp': ch_crd_tp  # 0:전체, 1:현금매매만, 2:신용매매만
        }
        return self._make_request('ka10170', data)


# 전역 계좌 API 인스턴스들 (서버별)
mock_account = KiwoomAccount('mock')
real_account = KiwoomAccount('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
kiwoom_account = mock_account
