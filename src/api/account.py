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
from src.config import KIWOOM_ACCOUNT_URL, API_REQUEST_DELAY
from src.utils import api_logger
from src.utils.cache import api_cache
from .auth import kiwoom_auth
import time

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'


class KiwoomAccount:
    """키움증권 계좌 관련 API 클래스"""
    
    def __init__(self):
        self.base_url = KIWOOM_ACCOUNT_URL
    
    def _make_request(self, api_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API 요청 공통 메서드 (재시도 로직 포함, 캐싱 지원)"""
        from src.config import MAX_RETRY_COUNT
        
        # 캐시에서 먼저 확인
        cached_result = api_cache.get(api_id, data)
        if cached_result is not None:
            api_logger.info(f"API {api_id} 캐시에서 조회")
            return cached_result
        
        for attempt in range(MAX_RETRY_COUNT):
            try:
                headers = kiwoom_auth.get_auth_headers()
                headers['api-id'] = api_id
                
                # API 요청 지연
                time.sleep(API_REQUEST_DELAY)
                
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
                
                if result.get('return_code') == 0:
                    # 성공적인 응답을 캐시에 저장
                    api_cache.set(api_id, data, result)
                    return result
                else:
                    error_msg = result.get('return_msg', '알 수 없는 오류')
                    error_code = result.get('return_code', 'UNKNOWN')
                    api_logger.error(f"API {api_id} 호출 실패: [{error_code}]{error_msg}")
                    api_logger.error(f"전체 응답: {result}")  # 전체 응답 로그 추가
                    
                    # 오류 정보를 포함한 결과 반환
                    return {
                        'success': False,
                        'error_code': error_code,
                        'error_message': error_msg,
                        'message': error_msg,  # 호환성을 위해 추가
                        'api_id': api_id,
                        'full_response': result  # 디버깅을 위해 전체 응답 포함
                    }
                    
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRY_COUNT - 1:
                    wait_time = (attempt + 1) * 2
                    api_logger.warning(f"API {api_id} 요청 실패, {wait_time}초 후 재시도 ({attempt + 1}/{MAX_RETRY_COUNT}): {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    api_logger.error(f"API {api_id} 최대 재시도 횟수 초과: {e}")
                    return None
            except Exception as e:
                api_logger.error(f"API {api_id} 처리 중 오류: {e}")
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
                           start_date: str = "", end_date: str = "", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        체결요청 (ka10076)
        
        Args:
            query_type: 조회구분
            sell_type: 매도수구분
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            exchange: 거래소구분 (KRX: 한국거래소, NXT: 넥스트트레이드)
            
        Returns:
            체결 주문 내역
        """
        api_logger.info(f"체결 주문 조회 (조회구분: {query_type}, 매도수구분: {sell_type}, 거래소: {exchange})")
        
        data = {
            'qry_tp': query_type,
            'sell_tp': sell_type,
            'stex_tp': exchange
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10076', data)
    
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


# 전역 계좌 API 인스턴스
kiwoom_account = KiwoomAccount()
