# -*- coding: utf-8 -*-
"""
kiwoomDeepLearning 모듈 연동 유틸리티
"""
import sys
import os
import io
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import joblib

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'

# kiwoomDeepLearning 프로젝트 경로 설정
# 프로젝트 루트에서 kiwoomDeepLearning 찾기 (동일 레벨 디렉토리)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
DEEP_LEARNING_PATH = os.path.join(PROJECT_ROOT, 'kiwoomDeepLearning')
DEEP_LEARNING_PATH = os.path.abspath(DEEP_LEARNING_PATH)

# Windows에서 posix 모듈 문제 해결을 위한 환경 변수 설정
if os.name == 'nt':  # Windows
    os.environ['PYTHONPATH'] = os.environ.get('PYTHONPATH', '') + os.pathsep + DEEP_LEARNING_PATH

print(f"프로젝트 루트: {PROJECT_ROOT}")
print(f"kiwoomDeepLearning 경로: {DEEP_LEARNING_PATH}")

if os.path.exists(DEEP_LEARNING_PATH):
    sys.path.append(DEEP_LEARNING_PATH)
    print(f"✅ kiwoomDeepLearning 경로 추가됨: {DEEP_LEARNING_PATH}")
    
    # kiwoomDeepLearning의 가상환경 site-packages 경로 추가
    venv_site_packages = os.path.join(DEEP_LEARNING_PATH, 'venv', 'lib', 'python3.12', 'site-packages')
    if os.path.exists(venv_site_packages):
        sys.path.insert(0, venv_site_packages)
        print(f"✅ kiwoomDeepLearning 가상환경 경로 추가됨: {venv_site_packages}")
    else:
        print(f"⚠️ kiwoomDeepLearning 가상환경 경로를 찾을 수 없습니다: {venv_site_packages}")
else:
    print(f"❌ kiwoomDeepLearning 경로를 찾을 수 없습니다: {DEEP_LEARNING_PATH}")

try:
    # kiwoomDeepLearning 모듈들 임포트
    from ensemble import calculate_final_score
    from ml_model import predict_with_ml_model
    from data_fetcher import fetch_stock_list
    from scoring import calculate_factor_scores
    from smart_cache import get_cache
    from logger import log_info, log_warning, log_error
    print("✅ kiwoomDeepLearning 모듈 import 성공")
except ImportError as e:
    print(f"Warning: kiwoomDeepLearning 모듈을 불러올 수 없습니다: {e}")
    print(f"경로 확인: {DEEP_LEARNING_PATH}")
    print(f"현재 sys.path: {sys.path[:3]}...")  # 처음 3개만 출력
    
    # 더미 함수들 정의 (개발 중 오류 방지)
    def calculate_final_score(df):
        return df
    
    def predict_with_ml_model(df):
        return df
    
    def fetch_stock_list():
        print("⚠️ 더미 fetch_stock_list 함수 사용 중 - 빈 DataFrame 반환")
        return pd.DataFrame()
    
    def calculate_factor_scores(df):
        return df
    
    def get_cache():
        return None
    
    def log_info(msg):
        print(f"INFO: {msg}")
    
    def log_warning(msg):
        print(f"WARNING: {msg}")
    
    def log_error(msg):
        print(f"ERROR: {msg}")


class DeepLearningAnalyzer:
    """kiwoomDeepLearning을 활용한 종목 분석 클래스"""
    
    def __init__(self):
        self.model_path = os.path.join(DEEP_LEARNING_PATH, 'data', 'stock_prediction_model_rf_upgraded.joblib')
        self.weights_path = os.path.join(DEEP_LEARNING_PATH, 'data', 'optimal_weights.json')
        self.cache = get_cache()
        
        print(f"모델 파일 경로: {self.model_path}")
        print(f"가중치 파일 경로: {self.weights_path}")
        print(f"모델 파일 존재: {os.path.exists(self.model_path)}")
        print(f"가중치 파일 존재: {os.path.exists(self.weights_path)}")
        
    def is_available(self):
        """kiwoomDeepLearning 모듈이 사용 가능한지 확인"""
        return os.path.exists(self.model_path) and os.path.exists(self.weights_path)
    
    def get_stock_analysis(self, analysis_date=None, force_realtime=False):
        """
        종목 분석 실행
        
        Args:
            analysis_date: 분석 기준일 (None이면 오늘)
            force_realtime: 실시간 분석 강제 실행 여부
            
        Returns:
            dict: 분석 결과
        """
        if not self.is_available():
            error_message = 'kiwoomDeepLearning 모듈이 사용 불가능합니다. 모델 파일을 확인해주세요.'
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ {error_message}")
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 📁 모델 파일 경로: {self.model_path}")
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 📁 가중치 파일 경로: {self.weights_path}")
            return {
                'success': False,
                'message': error_message
            }
        
        try:
            log_info("🔍 종목 분석을 시작합니다...")
            
            # 분석 기준일 설정 (오늘자부터 제일 가까운 거래일)
            if analysis_date is None:
                analysis_date = datetime.now().strftime('%Y-%m-%d')
            
            log_info(f"📅 분석 기준일: {analysis_date}")
            
            # 🔥 핵심 수정: 오늘 날짜이거나 실시간 강제 실행 시 캐시 무시
            today = datetime.now().strftime('%Y-%m-%d')
            is_today_analysis = analysis_date == today
            
            if force_realtime or is_today_analysis:
                log_info("🔄 실시간 분석을 실행합니다 (캐시 무시)")
                return self._run_realtime_analysis(analysis_date)
            
            # 과거 날짜 분석 시에만 캐시 확인
            log_info("📋 캐시된 분석 결과를 확인합니다...")
            cache_result = self._check_cache_analysis(analysis_date)
            if cache_result['success']:
                return cache_result
            
            # 캐시가 없으면 실시간 분석 실행
            log_info("🔄 캐시된 결과가 없어 실시간 분석을 실행합니다...")
            return self._run_realtime_analysis(analysis_date)
            
        except Exception as e:
            log_error(f"종목 분석 중 오류 발생: {e}")
            return {
                'success': False,
                'message': f'종목 분석 중 오류가 발생했습니다: {str(e)}'
            }
    
    def _check_cache_analysis(self, analysis_date):
        """캐시된 분석 결과 확인"""
        try:
            # JSON 파일 경로 확인
            cache_file_path = os.path.join(DEEP_LEARNING_PATH, 'cache', 'analysis_result.json')
            
            if not os.path.exists(cache_file_path):
                return {'success': False, 'message': '캐시 파일이 없습니다.'}
            
            # 파일 생성 시간 확인
            file_mtime = os.path.getmtime(cache_file_path)
            file_date = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d')
            
            if file_date != analysis_date:
                log_info(f"📅 캐시 파일 날짜({file_date})와 요청 날짜({analysis_date})가 다릅니다.")
                return {'success': False, 'message': '캐시 파일 날짜 불일치'}
            
            # JSON 파일 로드
            import json
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            
            if not cached_data:
                return {'success': False, 'message': '캐시 파일이 비어있습니다.'}
            
            log_info(f"✅ 캐시에서 분석 결과를 로드했습니다. ({len(cached_data)}개 종목)")
            
            return {
                'success': True,
                'data': {
                    'analysis_date': analysis_date,
                    'total_stocks': len(cached_data),
                    'top_stocks': cached_data[:20],  # 상위 20개
                    'analysis_result': cached_data
                }
            }
            
        except Exception as e:
            log_error(f"캐시 분석 결과 확인 중 오류: {e}")
            return {'success': False, 'message': f'캐시 확인 중 오류: {str(e)}'}
    
    def _run_realtime_analysis(self, analysis_date):
        """실시간 분석 실행"""
        try:
            # 1. 종목 목록 가져오기
            log_info("📊 종목 목록을 가져오는 중...")
            try:
                stock_list_df = fetch_stock_list()
                log_info(f"종목 목록 조회 결과: {len(stock_list_df) if not stock_list_df.empty else 0}개 종목")
                if stock_list_df.empty:
                    return {
                        'success': False,
                        'message': '종목 목록을 가져올 수 없습니다.'
                    }
            except Exception as e:
                log_error(f"종목 목록 조회 중 오류: {e}")
                return {
                    'success': False,
                    'message': f'종목 목록 조회 중 오류가 발생했습니다: {str(e)}'
                }
            
            log_info(f"✅ {len(stock_list_df)}개 종목 목록 수신 완료")
            
            # 2. kiwoomDeepLearning의 메인 분석 로직 호출
            log_info("📈 kiwoomDeepLearning 메인 분석 로직 실행 중...")
            try:
                # kiwoomDeepLearning의 fetch_all_data 함수 import
                from data_fetcher import fetch_all_data
                
                # analysis_date를 datetime 객체로 변환
                if isinstance(analysis_date, str):
                    analysis_date_obj = datetime.strptime(analysis_date, '%Y-%m-%d')
                else:
                    analysis_date_obj = analysis_date
                
                # 전체 데이터 수집 (재무, 주가, 기술적 지표, 거시경제 데이터 포함)
                feature_df, actual_analysis_date = fetch_all_data(stock_list_df, analysis_date_obj)
                
                if feature_df.empty:
                    return {
                        'success': False,
                        'message': '데이터 수집에 실패했습니다.'
                    }
                
                log_info(f"✅ 전체 데이터 수집 완료: {len(feature_df)}개 종목")
                
                # 3. 팩터 점수 계산
                log_info("🎯 팩터 점수 계산 중...")
                scored_df = calculate_factor_scores(feature_df)
                
                # 4. ML 예측
                log_info("🤖 머신러닝 예측 중...")
                ml_df = predict_with_ml_model(scored_df)
                
                # 5. 최종 점수 계산
                log_info("📊 최종 점수 계산 중...")
                try:
                    result_df = calculate_final_score(ml_df)
                except Exception as e:
                    log_warning(f"앙상블 점수 계산 중 오류 발생 (계속 진행): {e}")
                    # 오류가 발생해도 기본 점수로 진행
                    result_df = ml_df.copy()
                    if 'final_score' not in result_df.columns:
                        result_df['final_score'] = 50.0  # 기본 점수
                    if '최종순위' not in result_df.columns:
                        result_df['최종순위'] = range(1, len(result_df) + 1)
                
                # 6. 종목명과 현재가 정보 추가 (누락된 경우)
                log_info("📋 종목명과 현재가 정보를 추가합니다...")
                if '종목명' not in result_df.columns or result_df['종목명'].isna().all():
                    # stock_list_df에서 종목명 정보 병합
                    result_df = pd.merge(result_df, stock_list_df[['종목코드', '종목명']], on='종목코드', how='left')
                    log_info("✅ 종목명 정보를 병합했습니다.")
                
                if '현재가' not in result_df.columns or result_df['현재가'].isna().all():
                    # feature_df에서 현재가 정보 병합
                    if '현재가' in feature_df.columns:
                        price_info = feature_df[['종목코드', '현재가']].drop_duplicates()
                        result_df = pd.merge(result_df, price_info, on='종목코드', how='left')
                        log_info("✅ 현재가 정보를 병합했습니다.")
                    else:
                        log_warning("⚠️ feature_df에 현재가 정보가 없습니다.")
                
                log_info("✅ 실시간 종목 분석이 완료되었습니다.")
                
                return {
                    'success': True,
                    'data': {
                        'analysis_date': actual_analysis_date.strftime('%Y-%m-%d') if actual_analysis_date else analysis_date.strftime('%Y-%m-%d'),
                        'total_stocks': len(result_df),
                        'top_stocks': result_df.head(20).to_dict('records'),
                        'analysis_result': result_df.to_dict('records')
                    }
                }
                
            except ImportError as e:
                log_error(f"kiwoomDeepLearning 모듈 import 실패: {e}")
                return {
                    'success': False,
                    'message': f'kiwoomDeepLearning 모듈을 불러올 수 없습니다: {str(e)}'
                }
            except Exception as e:
                log_error(f"분석 실행 중 오류: {e}")
                return {
                    'success': False,
                    'message': f'분석 실행 중 오류가 발생했습니다: {str(e)}'
                }
            
        except Exception as e:
            log_error(f"실시간 분석 중 오류 발생: {e}")
            return {
                'success': False,
                'message': f'실시간 분석 중 오류가 발생했습니다: {str(e)}'
            }
    
    
    def get_top_stocks(self, analysis_result, top_n=5, buy_universe_rank=20, include_sell_candidates=None):
        """
        매수 대상 종목 선정 (보유 종목 제외, 매도 예정 종목은 상위 매수고려대상에 추가)
        
        Args:
            analysis_result: 분석 결과
            top_n: 매수할 종목 수
            buy_universe_rank: 매수 대상 범위
            include_sell_candidates: 매도 예정 종목 코드 리스트 (팝업에서 상위 매수고려대상에 추가)
            
        Returns:
            list: 매수 대상 종목 리스트
        """
        if not analysis_result.get('success'):
            return []
        
        try:
            result_df = pd.DataFrame(analysis_result['data']['analysis_result'])
            
            # 제외할 종목 목록 준비 (보유 종목만 제외)
            exclude_stocks = set()
            
            # 1. 보유 종목 조회 (실패해도 계속 진행)
            try:
                held_stocks = self._get_held_stocks()
                if held_stocks:
                    exclude_stocks.update(held_stocks)
                    log_info(f"📋 보유 종목 {len(held_stocks)}개를 매수 대상에서 제외합니다.")
                else:
                    log_info("📋 보유 종목이 없거나 조회에 실패했습니다.")
            except Exception as e:
                log_warning(f"보유 종목 조회 중 오류 발생 (계속 진행): {e}")
            
            # 2. 매도 후 보유종목 계산 (팝업에서 사용)
            final_exclude_stocks = exclude_stocks.copy() if exclude_stocks else set()
            
            if include_sell_candidates:
                # 매도 예정 종목을 보유종목에서 제거 (매도 후 보유종목)
                for stock_code in include_sell_candidates:
                    # A 프리픽스 제거
                    clean_stock_code = stock_code.replace('A', '') if stock_code.startswith('A') else stock_code
                    if clean_stock_code in final_exclude_stocks:
                        final_exclude_stocks.remove(clean_stock_code)
                        log_info(f"📉 매도 예정 종목 {clean_stock_code}를 보유종목에서 제거 (매도 후 보유종목 계산)")
            
            # 3. 매도 후 보유종목을 DataFrame에서 필터링
            if final_exclude_stocks:
                result_df = result_df[~result_df['종목코드'].isin(final_exclude_stocks)]
                log_info(f"✅ 매도 후 보유 종목 {len(final_exclude_stocks)}개 제외 후 {len(result_df)}개 종목이 남았습니다.")
            else:
                log_info("📋 제외할 보유 종목이 없습니다.")
            
            # 매수 대상 범위 내에서 상위 N개 선택
            buy_candidates = result_df[result_df['최종순위'] <= buy_universe_rank]
            top_stocks = buy_candidates.head(top_n)
            
            return top_stocks.to_dict('records')
            
        except Exception as e:
            log_error(f"매수 대상 선정 중 오류 발생: {e}")
            return []
    
    def _get_held_stocks(self):
        """보유 종목 조회"""
        try:
            from src.api.account import KiwoomAccount
            from src.utils.server_manager import get_current_server
            
            # 현재 서버 타입에 맞는 API 인스턴스 사용
            server_type = get_current_server()
            kiwoom_account = KiwoomAccount(server_type)
            
            # 인증 상태 확인
            from src.api.auth import KiwoomAuth
            auth = KiwoomAuth(server_type)
            if not auth.is_token_valid():
                log_warning(f"키움 API 인증이 필요합니다. (서버: {server_type})")
                return []
            
            # 보유 종목 정보 조회
            balance_result = kiwoom_account.get_account_balance_detail()
            
            if not balance_result:
                log_warning("보유 종목 정보 조회 결과가 None입니다.")
                return []
            elif not balance_result.get('success'):
                error_msg = balance_result.get('message', '알 수 없는 오류')
                error_code = balance_result.get('error_code', 'UNKNOWN')
                full_response = balance_result.get('full_response', {})
                log_warning(f"보유 종목 정보 조회 실패: [{error_code}] {error_msg}")
                log_warning(f"전체 API 응답: {full_response}")
                return []
            
            # 보유 수량이 있는 종목만 필터링
            held_stocks = []
            if balance_result.get('acnt_evlt_remn_indv_tot'):
                for stock in balance_result['acnt_evlt_remn_indv_tot']:
                    stock_code = stock.get('stk_cd')
                    stock_name = stock.get('stk_nm')
                    qty = int(stock.get('rmnd_qty', 0))
                    
                    if qty > 0:  # 보유 수량이 있는 경우
                        # 종목코드에서 A 접두사 제거 (6자리 숫자만 사용)
                        clean_stock_code = stock_code.replace('A', '') if stock_code.startswith('A') else stock_code
                        held_stocks.append(clean_stock_code)
                        log_info(f"📋 보유 종목: {stock_name}({stock_code} → {clean_stock_code}) - {qty}주")
            
            log_info(f"📋 총 보유 종목 수: {len(held_stocks)}개")
            return held_stocks
            
        except Exception as e:
            log_error(f"보유 종목 조회 중 오류: {e}")
            return []


# 전역 인스턴스
deep_learning_analyzer = DeepLearningAnalyzer()
