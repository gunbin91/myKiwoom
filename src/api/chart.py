# -*- coding: utf-8 -*-
"""
키움증권 차트 관련 API 모듈
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


class KiwoomChart:
    """키움증권 차트 관련 API 클래스"""
    
    def __init__(self, server_type: str = None):
        if server_type:
            from src.config.server_config import get_server_config
            self.server_config = get_server_config(server_type)
        else:
            self.server_config = get_current_server_config()
        self.base_url = self.server_config.chart_url
        self.server_type = server_type
    
    def _make_request(self, api_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """API 요청 공통 메서드"""
        try:
            # 현재 서버 타입에 맞는 인증 인스턴스 사용
            current_auth = KiwoomAuth(self.server_type)
            headers = current_auth.get_auth_headers()
            headers['api-id'] = api_id
            
            # 모든 차트 관련 API는 차트 엔드포인트 사용
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
    
    def get_stock_tick_chart(self, stock_code: str, tick_scope: str = "1", 
                           upd_stkpc_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        주식틱차트조회요청 (ka10079)
        
        Args:
            stock_code: 종목코드
            tick_scope: 틱범위 (1:1틱, 3:3틱, 5:5틱, 10:10틱, 30:30틱)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            
        Returns:
            틱차트 데이터
        """
        trading_logger.info(f"주식틱차트조회 (종목: {stock_code}, 틱범위: {tick_scope})")
        
        data = {
            'stk_cd': stock_code,
            'tic_scope': tick_scope,
            'upd_stkpc_tp': upd_stkpc_tp
        }
        
        result = self._make_request('ka10079', data)
        
        if result:
            # 응답 데이터 구조 확인을 위한 로깅
            trading_logger.info(f"주식틱차트조회 응답 키: {list(result.keys()) if result else 'None'}")
            trading_logger.info(f"주식틱차트조회 성공: {len(result.get('stk_tic_chart_qry', []))}건")
        else:
            trading_logger.error(f"주식틱차트조회 실패: {stock_code}")
        
        return result
    
    def get_stock_minute_chart(self, stock_code: str, tick_scope: str = "1", 
                             upd_stkpc_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        주식분봉차트조회요청 (ka10080)
        
        Args:
            stock_code: 종목코드
            tick_scope: 틱범위 (1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 45:45분, 60:60분)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            
        Returns:
            분봉차트 데이터
        """
        trading_logger.info(f"주식분봉차트조회 (종목: {stock_code}, 틱범위: {tick_scope})")
        
        data = {
            'stk_cd': stock_code,
            'tic_scope': tick_scope,
            'upd_stkpc_tp': upd_stkpc_tp
        }
        
        result = self._make_request('ka10080', data)
        
        if result:
            # 응답 데이터 구조 확인을 위한 로깅
            trading_logger.info(f"주식분봉차트조회 응답 키: {list(result.keys()) if result else 'None'}")
            trading_logger.info(f"주식분봉차트조회 성공: {len(result.get('stk_min_pole_chart_qry', []))}건")
        else:
            trading_logger.error(f"주식분봉차트조회 실패: {stock_code}")
        
        return result
    
    def get_stock_daily_chart(self, stock_code: str, base_dt: str = "", 
                            upd_stkpc_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        주식일봉차트조회요청 (ka10081)
        
        Args:
            stock_code: 종목코드
            base_dt: 기준일자 (YYYYMMDD, 공백시 오늘 날짜) - 키움 API는 base_dt부터 과거 데이터를 가져옴
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            
        Returns:
            일봉차트 데이터
        """
        # base_dt가 비어있으면 오늘 날짜로 설정 (키움 API는 base_dt부터 과거 데이터를 가져옴)
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        trading_logger.info(f"주식일봉차트조회 (종목: {stock_code}, 기준일자: {base_dt})")
        
        data = {
            'stk_cd': stock_code,
            'base_dt': base_dt,
            'upd_stkpc_tp': upd_stkpc_tp
        }
        
        result = self._make_request('ka10081', data)
        
        if result:
            trading_logger.info(f"주식일봉차트조회 성공: {len(result.get('stk_dt_pole_chart_qry', []))}건")
        else:
            trading_logger.error(f"주식일봉차트조회 실패: {stock_code}")
        
        return result
    
    def get_stock_weekly_chart(self, stock_code: str, base_dt: str = "", 
                             upd_stkpc_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        주식주봉차트조회요청 (ka10082)
        
        Args:
            stock_code: 종목코드
            base_dt: 기준일자 (YYYYMMDD, 공백시 오늘 날짜)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            
        Returns:
            주봉차트 데이터
        """
        # base_dt가 비어있으면 오늘 날짜로 설정
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        trading_logger.info(f"주식주봉차트조회 (종목: {stock_code}, 기준일자: {base_dt})")
        
        data = {
            'stk_cd': stock_code,
            'base_dt': base_dt,
            'upd_stkpc_tp': upd_stkpc_tp
        }
        
        result = self._make_request('ka10082', data)
        
        if result:
            # 응답 데이터 구조 확인을 위한 로깅
            trading_logger.info(f"주식주봉차트조회 응답 키: {list(result.keys()) if result else 'None'}")
            trading_logger.info(f"주식주봉차트조회 성공: {len(result.get('stk_stk_pole_chart_qry', []))}건")
        else:
            trading_logger.error(f"주식주봉차트조회 실패: {stock_code}")
        
        return result
    
    def get_stock_monthly_chart(self, stock_code: str, base_dt: str = "", 
                              upd_stkpc_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        주식월봉차트조회요청 (ka10083)
        
        Args:
            stock_code: 종목코드
            base_dt: 기준일자 (YYYYMMDD, 공백시 오늘 날짜)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            
        Returns:
            월봉차트 데이터
        """
        # base_dt가 비어있으면 오늘 날짜로 설정
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        trading_logger.info(f"주식월봉차트조회 (종목: {stock_code}, 기준일자: {base_dt})")
        
        data = {
            'stk_cd': stock_code,
            'base_dt': base_dt,
            'upd_stkpc_tp': upd_stkpc_tp
        }
        
        result = self._make_request('ka10083', data)
        
        if result:
            # 응답 데이터 구조 확인을 위한 로깅
            trading_logger.info(f"주식월봉차트조회 응답 키: {list(result.keys()) if result else 'None'}")
            trading_logger.info(f"주식월봉차트조회 성공: {len(result.get('stk_mth_pole_chart_qry', []))}건")
        else:
            trading_logger.error(f"주식월봉차트조회 실패: {stock_code}")
        
        return result
    
    def get_stock_yearly_chart(self, stock_code: str, base_dt: str = "", 
                             upd_stkpc_tp: str = "0") -> Optional[Dict[str, Any]]:
        """
        주식년봉차트조회요청 (ka10094)
        
        Args:
            stock_code: 종목코드
            base_dt: 기준일자 (YYYYMMDD, 공백시 오늘 날짜)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            
        Returns:
            년봉차트 데이터
        """
        # base_dt가 비어있으면 오늘 날짜로 설정
        if not base_dt:
            from datetime import datetime
            base_dt = datetime.now().strftime('%Y%m%d')
        
        trading_logger.info(f"주식년봉차트조회 (종목: {stock_code}, 기준일자: {base_dt})")
        
        data = {
            'stk_cd': stock_code,
            'base_dt': base_dt,
            'upd_stkpc_tp': upd_stkpc_tp
        }
        
        result = self._make_request('ka10094', data)
        
        if result:
            # 응답 데이터 구조 확인을 위한 로깅
            trading_logger.info(f"주식년봉차트조회 응답 키: {list(result.keys()) if result else 'None'}")
            trading_logger.info(f"주식년봉차트조회 성공: {len(result.get('stk_yr_pole_chart_qry', []))}건")
        else:
            trading_logger.error(f"주식년봉차트조회 실패: {stock_code}")
        
        return result
    
    def get_investor_chart(self, stock_code: str, dt: str, amt_qty_tp: str = "1", 
                         trde_tp: str = "0", unit_tp: str = "1000") -> Optional[Dict[str, Any]]:
        """
        종목별투자자기관별차트요청 (ka10060)
        
        Args:
            stock_code: 종목코드
            dt: 일자 (YYYYMMDD)
            amt_qty_tp: 금액수량구분 (1:금액, 2:수량)
            trde_tp: 매매구분 (0:순매수, 1:매수, 2:매도)
            unit_tp: 단위구분 (1000:천주, 1:단주)
            
        Returns:
            투자자별 차트 데이터
        """
        trading_logger.info(f"종목별투자자기관별차트조회 (종목: {stock_code}, 일자: {dt})")
        
        data = {
            'dt': dt,
            'stk_cd': stock_code,
            'amt_qty_tp': amt_qty_tp,
            'trde_tp': trde_tp,
            'unit_tp': unit_tp
        }
        
        result = self._make_request('ka10060', data)
        
        if result:
            # 응답 데이터 구조 확인을 위한 로깅
            trading_logger.info(f"종목별투자자기관별차트조회 응답 키: {list(result.keys()) if result else 'None'}")
            trading_logger.info(f"종목별투자자기관별차트조회 성공: {len(result.get('stk_invsr_orgn_chart', []))}건")
        else:
            trading_logger.error(f"종목별투자자기관별차트조회 실패: {stock_code}")
        
        return result


# 전역 차트 API 인스턴스들 (서버별)
mock_chart = KiwoomChart('mock')
real_chart = KiwoomChart('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
kiwoom_chart = mock_chart
