# -*- coding: utf-8 -*-
"""
키움증권 시세 관련 API 모듈
"""
import sys
import os
import io
from typing import Dict, List, Optional, Any
import requests
from src.config.server_config import get_current_server_config
from src.config.settings import API_REQUEST_DELAY
from src.utils import api_logger
from .auth import KiwoomAuth
import time

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'


class KiwoomQuote:
    """키움증권 시세 관련 API 클래스"""
    
    def __init__(self, server_type: str = None):
        if server_type:
            from src.config.server_config import get_server_config
            self.server_config = get_server_config(server_type)
        else:
            self.server_config = get_current_server_config()
        self.base_url = self.server_config.quote_url
        self.server_type = server_type
    
    def _make_request(self, api_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API 요청 공통 메서드"""
        try:
            # 현재 서버 타입에 맞는 인증 인스턴스 사용
            current_auth = KiwoomAuth(self.server_type)
            headers = current_auth.get_auth_headers()
            headers['api-id'] = api_id
            
            # API 요청 지연
            time.sleep(API_REQUEST_DELAY)
            
            response = requests.post(
                self.base_url,
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
            api_logger.error(f"API {api_id} 요청 실패: {e}")
            return None
        except Exception as e:
            api_logger.error(f"API {api_id} 처리 중 오류: {e}")
            return None
    
    def get_stock_basic_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        주식기본정보요청 (ka10001)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            주식 기본 정보
        """
        api_logger.info(f"주식기본정보 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        return self._make_request('ka10001', data)
    
    def get_stock_quote(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        주식호가요청 (ka10004)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            주식 호가 정보
        """
        api_logger.info(f"주식호가 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        return self._make_request('ka10004', data)
    
    def get_stock_price_chart(self, stock_code: str, period: str = "D", 
                             start_date: str = "", end_date: str = "") -> Optional[Dict[str, Any]]:
        """
        주식일주월시분요청 (ka10005)
        
        Args:
            stock_code: 종목코드
            period: 기간구분 ("D": 일, "W": 주, "M": 월, "H": 시, "M": 분)
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            주식 가격 차트 데이터
        """
        api_logger.info(f"주식가격차트 조회 (종목코드: {stock_code}, 기간: {period})")
        
        data = {
            'stk_cd': stock_code,
            'prd_tp': period
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10005', data)
    
    def get_stock_tick_chart(self, stock_code: str, start_date: str = "", end_date: str = "") -> Optional[Dict[str, Any]]:
        """
        주식틱차트조회요청 (ka10075)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            틱 차트 데이터
        """
        api_logger.info(f"주식틱차트 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10075', data)
    
    def get_stock_minute_chart(self, stock_code: str, start_date: str = "", end_date: str = "") -> Optional[Dict[str, Any]]:
        """
        주식분봉차트조회요청 (ka10080)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            분봉 차트 데이터
        """
        api_logger.info(f"주식분봉차트 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10080', data)
    
    def get_stock_daily_chart(self, stock_code: str, start_date: str = "", end_date: str = "") -> Optional[Dict[str, Any]]:
        """
        주식일봉차트조회요청 (ka10081)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            일봉 차트 데이터
        """
        api_logger.info(f"주식일봉차트 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10081', data)
    
    def get_stock_weekly_chart(self, stock_code: str, start_date: str = "", end_date: str = "") -> Optional[Dict[str, Any]]:
        """
        주식주봉차트조회요청 (ka10082)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            주봉 차트 데이터
        """
        api_logger.info(f"주식주봉차트 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10082', data)
    
    def get_stock_monthly_chart(self, stock_code: str, start_date: str = "", end_date: str = "") -> Optional[Dict[str, Any]]:
        """
        주식월봉차트조회요청 (ka10083)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            월봉 차트 데이터
        """
        api_logger.info(f"주식월봉차트 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        if start_date:
            data['strt_dt'] = start_date
        if end_date:
            data['end_dt'] = end_date
        
        return self._make_request('ka10083', data)
    
    def get_stock_list(self) -> Optional[Dict[str, Any]]:
        """
        종목정보 리스트 (ka10099)
        
        Returns:
            종목 정보 리스트
        """
        api_logger.info("종목정보 리스트 조회")
        
        data = {}
        return self._make_request('ka10099', data)
    
    def get_stock_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        주식기본정보 조회 (ka10001)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            종목 기본 정보
        """
        api_logger.info(f"주식기본정보 조회 (종목코드: {stock_code})")
        
        data = {
            'stk_cd': stock_code
        }
        
        return self._make_request('ka10001', data)
    
    def get_sector_list(self) -> Optional[Dict[str, Any]]:
        """
        업종코드 리스트 (ka10101)
        
        Returns:
            업종코드 리스트
        """
        api_logger.info("업종코드 리스트 조회")
        
        data = {}
        return self._make_request('ka10101', data)
    
    def get_daily_price(self, stock_code: str, start_date: str, end_date: str) -> Optional[Dict[str, Any]]:
        """
        일별주가요청 (ka10086)
        
        Args:
            stock_code: 종목코드
            start_date: 시작일자 (YYYYMMDD)
            end_date: 종료일자 (YYYYMMDD)
            
        Returns:
            일별 주가 데이터
        """
        api_logger.info(f"일별주가 조회 (종목코드: {stock_code}, 기간: {start_date}~{end_date})")
        
        data = {
            'stk_cd': stock_code,
            'strt_dt': start_date,
            'end_dt': end_date
        }
        
        return self._make_request('ka10086', data)
    
    def get_current_price(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        실시간 현재가 조회 (주식기본정보요청 활용)
        
        Args:
            stock_code: 종목코드
            
        Returns:
            실시간 현재가 정보
        """
        api_logger.info(f"실시간 현재가 조회 (종목코드: {stock_code})")
        
        # 주식기본정보요청을 통해 현재가 조회
        result = self.get_stock_basic_info(stock_code)
        
        if result and result.get('return_code') == 0:
            # 주식기본정보에서 현재가 추출
            current_price_str = result.get('cur_prc', '0')
            
            # +, - 기호 제거하고 숫자만 추출
            try:
                # +76500, -12300 같은 형태에서 숫자만 추출
                current_price = int(current_price_str.replace('+', '').replace('-', ''))
                
                if current_price > 0:
                    return {
                        'success': True,
                        'current_price': current_price,
                        'stock_code': stock_code,
                        'message': '현재가 조회 성공'
                    }
                else:
                    return {
                        'success': False,
                        'current_price': 0,
                        'message': '유효하지 않은 가격 정보'
                    }
            except (ValueError, TypeError) as e:
                return {
                    'success': False,
                    'current_price': 0,
                    'message': f'가격 파싱 오류: {str(e)}'
                }
        else:
            error_msg = result.get('return_msg', '알 수 없는 오류') if result else 'API 호출 실패'
            return {
                'success': False,
                'current_price': 0,
                'message': f'현재가 조회 실패: {error_msg}'
            }


# 전역 시세 API 인스턴스들 (서버별)
mock_quote = KiwoomQuote('mock')
real_quote = KiwoomQuote('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
kiwoom_quote = mock_quote

