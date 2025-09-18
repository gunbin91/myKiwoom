# -*- coding: utf-8 -*-
"""
키움증권 주문 관련 API 모듈

주의: 이 모듈은 현금 주문만 지원합니다.
신용주문(융자/대주)은 사용하지 않습니다.

신용주문을 사용하지 않는 이유:
- 복잡성: 현금 주문보다 복잡한 구조
- 위험성: 레버리지로 인한 손실 확대 가능
- 비용: 이자 및 추가 수수료 부담
- 규제: 신용거래 한도 및 제한사항
"""
import sys
import os
import io
from typing import Dict, List, Optional, Any
import requests
from src.config.server_config import get_current_server_config
from src.config.settings import API_REQUEST_DELAY

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'
from src.utils import api_logger, trading_logger
from .auth import KiwoomAuth
import time


def convert_stock_code_for_order(stock_code: str) -> str:
    """
    계좌 API 종목코드를 주문 API 종목코드로 변환
    
    Args:
        stock_code: 계좌 API 종목코드 (A005930) 또는 주문 API 종목코드 (005930)
        
    Returns:
        주문 API용 종목코드 (005930)
    """
    if not stock_code:
        return stock_code
    
    # A로 시작하는 경우 A 제거
    if stock_code.startswith('A') and len(stock_code) == 7:
        return stock_code[1:]  # A 제거
    
    # 이미 6자리인 경우 그대로 반환
    if len(stock_code) == 6 and stock_code.isdigit():
        return stock_code
    
    # 기타 경우 원본 반환
    return stock_code


def convert_stock_code_for_account(stock_code: str) -> str:
    """
    주문 API 종목코드를 계좌 API 종목코드로 변환
    
    Args:
        stock_code: 주문 API 종목코드 (005930) 또는 계좌 API 종목코드 (A005930)
        
    Returns:
        계좌 API용 종목코드 (A005930)
    """
    if not stock_code:
        return stock_code
    
    # A로 시작하는 경우 그대로 반환
    if stock_code.startswith('A') and len(stock_code) == 7:
        return stock_code
    
    # 6자리인 경우 A 추가
    if len(stock_code) == 6 and stock_code.isdigit():
        return f"A{stock_code}"
    
    # 기타 경우 원본 반환
    return stock_code


class KiwoomOrder:
    """키움증권 주문 관련 API 클래스"""
    
    def __init__(self, server_type: str = None):
        if server_type:
            from src.config.server_config import get_server_config
            self.server_config = get_server_config(server_type)
        else:
            self.server_config = get_current_server_config()
        self.base_url = self.server_config.order_url
        self.server_type = server_type
    
    def _make_request(self, api_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API 요청 공통 메서드"""
        try:
            # 현재 서버 타입에 맞는 인증 인스턴스 사용
            current_auth = KiwoomAuth(self.server_type)
            headers = current_auth.get_auth_headers()
            headers['api-id'] = api_id
            
            # API ID에 따라 올바른 엔드포인트 선택
            if api_id == 'kt00007':
                # kt00007은 계좌 API이므로 계좌 엔드포인트 사용
                url = self.server_config.account_url
            else:
                # 기타 주문 관련 API는 주문 엔드포인트 사용
                url = self.base_url
            
            # API 요청 지연
            time.sleep(API_REQUEST_DELAY)
            
            response = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('return_code') == 0:
                return result
            else:
                error_msg = result.get('return_msg', '알 수 없는 오류')
                error_code = result.get('return_code', 'UNKNOWN')
                api_logger.error(f"API {api_id} 호출 실패: [{error_code}]{error_msg}")
                
                # 오류 정보를 포함한 결과 반환
                return {
                    'success': False,
                    'error_code': error_code,
                    'error_message': error_msg,
                    'api_id': api_id
                }
                
        except requests.exceptions.RequestException as e:
            api_logger.error(f"🚨 API {api_id} 요청 실패: {e}")
            api_logger.error(f"   📍 요청 URL: {url}")
            api_logger.error(f"   📍 요청 데이터: {data}")
            return None
        except Exception as e:
            api_logger.error(f"🚨 API {api_id} 처리 중 예상치 못한 오류: {e}")
            api_logger.error(f"   📍 요청 URL: {url}")
            api_logger.error(f"   📍 요청 데이터: {data}")
            import traceback
            api_logger.error(f"   📍 스택 트레이스: {traceback.format_exc()}")
            return None
    
    def buy_stock(self, stock_code: str, quantity: int, price: int, 
                  order_type: str = "0", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        주식 매수주문 (kt10000)
        
        Args:
            stock_code: 종목코드
            quantity: 주문수량
            price: 주문가격 (시장가는 0)
            order_type: 매매구분 ("0": 보통, "3": 시장가, "5": 조건부지정가)
            exchange: 국내거래소구분 ("KRX": 한국거래소, "NXT": 넥스트트레이드)
            
        Returns:
            주문 결과
        """
        # 수량을 정수로 변환 (키움 API는 정수만 허용)
        quantity = int(quantity)
        
        # 주문 API용 종목코드로 변환 (A 제거)
        order_stock_code = convert_stock_code_for_order(stock_code)
        
        trading_logger.info(f"매수주문 (종목: {stock_code} -> {order_stock_code}, 수량: {quantity}, 가격: {price}, 구분: {order_type}, 거래소: {exchange})")
        
        data = {
            'dmst_stex_tp': exchange,
            'stk_cd': order_stock_code,  # 변환된 종목코드 사용
            'ord_qty': str(quantity),
            'trde_tp': order_type
        }
        
        # 지정가 주문인 경우에만 주문단가 추가
        if order_type == "0" and price > 0:
            data['ord_uv'] = str(price)
        elif order_type == "3":  # 시장가
            data['ord_uv'] = "0"
        
        result = self._make_request('kt10000', data)
        
        if result:
            trading_logger.info(f"매수주문 성공: {result}")
        else:
            trading_logger.error(f"매수주문 실패: {stock_code}")
        
        return result
    
    def sell_stock(self, stock_code: str, quantity: int, price: int, 
                   order_type: str = "0", exchange: str = "KRX") -> Optional[Dict[str, Any]]:
        """
        주식 매도주문 (kt10001)
        
        Args:
            stock_code: 종목코드
            quantity: 주문수량
            price: 주문가격 (시장가는 0)
            order_type: 매매구분 ("0": 보통, "3": 시장가, "5": 조건부지정가)
            exchange: 국내거래소구분 ("KRX": 한국거래소, "NXT": 넥스트트레이드)
            
        Returns:
            주문 결과
        """
        # 수량을 정수로 변환 (키움 API는 정수만 허용)
        quantity = int(quantity)
        
        # 주문 API용 종목코드로 변환 (A 제거)
        order_stock_code = convert_stock_code_for_order(stock_code)
        
        trading_logger.info(f"매도주문 (종목: {stock_code} -> {order_stock_code}, 수량: {quantity}, 가격: {price}, 구분: {order_type}, 거래소: {exchange})")
        
        data = {
            'dmst_stex_tp': exchange,
            'stk_cd': order_stock_code,  # 변환된 종목코드 사용
            'ord_qty': str(quantity),
            'trde_tp': order_type
        }
        
        # 지정가 주문인 경우에만 주문단가 추가
        if order_type == "0" and price > 0:
            data['ord_uv'] = str(price)
        elif order_type == "3":  # 시장가
            data['ord_uv'] = "0"
        
        result = self._make_request('kt10001', data)
        
        if result:
            trading_logger.info(f"매도주문 성공: {result}")
        else:
            trading_logger.error(f"매도주문 실패: {stock_code}")
        
        return result
    
    def modify_order(self, order_no: str, stock_code: str, quantity: int, price: int, 
                     order_type: str = "00", account_type: str = "01") -> Optional[Dict[str, Any]]:
        """
        주식 정정주문 (kt10002)
        
        Args:
            order_no: 주문번호
            stock_code: 종목코드
            quantity: 정정수량
            price: 정정가격
            order_type: 주문구분
            account_type: 계좌구분
            
        Returns:
            정정 결과
        """
        # 주문 API용 종목코드로 변환 (A 제거)
        order_stock_code = convert_stock_code_for_order(stock_code)
        
        trading_logger.info(f"정정주문 (주문번호: {order_no}, 종목: {stock_code} -> {order_stock_code}, 수량: {quantity}, 가격: {price})")
        
        data = {
            'ord_no': order_no,
            'stk_cd': order_stock_code,  # 변환된 종목코드 사용
            'ord_qty': str(quantity),
            'ord_pric': str(price),
            'ord_tp': order_type,
            'acnt_tp': account_type
        }
        
        result = self._make_request('kt10002', data)
        
        if result:
            trading_logger.info(f"정정주문 성공: {result}")
        else:
            trading_logger.error(f"정정주문 실패: {order_no}")
        
        return result
    
    def cancel_order(self, order_no: str, stock_code: str, quantity: int, 
                     account_type: str = "01") -> Optional[Dict[str, Any]]:
        """
        주식 취소주문 (kt10003)
        
        Args:
            order_no: 주문번호
            stock_code: 종목코드
            quantity: 취소수량
            account_type: 계좌구분
            
        Returns:
            취소 결과
        """
        # 주문 API용 종목코드로 변환 (A 제거)
        order_stock_code = convert_stock_code_for_order(stock_code)
        
        trading_logger.info(f"취소주문 (주문번호: {order_no}, 종목: {stock_code} -> {order_stock_code}, 수량: {quantity})")
        
        data = {
            'ord_no': order_no,
            'stk_cd': order_stock_code,  # 변환된 종목코드 사용
            'ord_qty': str(quantity),
            'acnt_tp': account_type
        }
        
        result = self._make_request('kt10003', data)
        
        if result:
            trading_logger.info(f"취소주문 성공: {result}")
        else:
            trading_logger.error(f"취소주문 실패: {order_no}")
        
        return result
    
    def get_order_history(self, start_date: str = "", end_date: str = "", 
                         stock_code: str = "", order_type: str = "0") -> Optional[Dict[str, Any]]:
        """
        계좌별주문체결내역상세요청 (kt00007)
        
        Args:
            start_date: 시작일자 (YYYYMMDD, 공백시 전체)
            end_date: 종료일자 (YYYYMMDD, 공백시 전체)
            stock_code: 종목코드 (공백시 전체종목)
            order_type: 매도수구분 ("0": 전체, "1": 매도, "2": 매수)
            
        Returns:
            주문체결내역
        """
        # 계좌 API용 종목코드로 변환 (A 추가)
        account_stock_code = convert_stock_code_for_account(stock_code)
        
        trading_logger.info(f"주문체결내역 조회 (시작일: {start_date}, 종료일: {end_date}, 종목: {stock_code} -> {account_stock_code}, 구분: {order_type})")
        
        data = {
            'ord_dt': start_date,  # 주문일자
            'qry_tp': '4',  # 체결내역만
            'stk_bond_tp': '1',  # 주식만
            'sell_tp': order_type,  # 매도수구분
            'stk_cd': account_stock_code,  # 변환된 종목코드 사용
            'fr_ord_no': '',  # 시작주문번호
            'dmst_stex_tp': '%'  # 전체거래소
        }
        
        result = self._make_request('kt00007', data)
        
        if result:
            trading_logger.info(f"주문체결내역 조회 성공: {len(result.get('acnt_ord_cntr_prps_dtl', []))}건")
        else:
            trading_logger.error(f"주문체결내역 조회 실패")
        
        return result
    
    # =============================================================================
    # 신용주문 관련 메서드들은 제거됨
    # 
    # 이유: 일반적인 자동매매 시스템에서는 신용주문(융자/대주)을 사용하지 않음
    # - 복잡성: 현금 주문보다 복잡한 구조
    # - 위험성: 레버리지로 인한 손실 확대 가능
    # - 비용: 이자 및 추가 수수료 부담
    # - 규제: 신용거래 한도 및 제한사항
    # 
    # 신용주문 API: kt10006(신용매수), kt10007(신용매도), kt10008(신용정정), kt10009(신용취소)
    # URL: /api/dostk/crdordr
    # =============================================================================
    


# 전역 주문 API 인스턴스들 (서버별)
mock_order = KiwoomOrder('mock')
real_order = KiwoomOrder('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
kiwoom_order = mock_order

