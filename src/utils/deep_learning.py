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
except ImportError as e:
    print(f"Warning: kiwoomDeepLearning 모듈을 불러올 수 없습니다: {e}")
    print(f"경로 확인: {DEEP_LEARNING_PATH}")
    
    # 더미 함수들 정의 (개발 중 오류 방지)
    def calculate_final_score(df):
        return df
    
    def predict_with_ml_model(df):
        return df
    
    def fetch_stock_list():
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
    
    def get_stock_analysis(self, analysis_date=None):
        """
        종목 분석 실행
        
        Args:
            analysis_date: 분석 기준일 (None이면 오늘)
            
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
            
            # 2. 실시간 분석 실행 (kiwoomDeepLearning 메인 로직 사용)
            log_info("📈 실시간 주가 데이터 수집 및 분석 중...")
            
            # 캐시에서 최신 분석 결과 확인
            cache = get_cache()
            cache_params = {'analysis_date': analysis_date}
            cached_result = cache.get('analysis_result', cache_params)
            if cached_result is not None and not cached_result.empty:
                log_info("📋 캐시에서 최신 분석 결과를 가져옵니다.")
                result_df = cached_result
            else:
                log_info("🔄 새로운 분석을 실행합니다...")
                
                # 3. 팩터 점수 계산
                log_info("🎯 팩터 점수 계산 중...")
                scored_df = calculate_factor_scores(stock_list_df)
                
                # 4. ML 예측
                log_info("🤖 머신러닝 예측 중...")
                ml_df = predict_with_ml_model(scored_df)
                
                # 5. 최종 점수 계산
                log_info("📊 최종 점수 계산 중...")
                result_df = calculate_final_score(ml_df)
                
                # 결과를 캐시에 저장
                if cache:
                    cache.set('analysis_result', cache_params, result_df)
            
            log_info("✅ 종목 분석이 완료되었습니다.")
            
            return {
                'success': True,
                'data': {
                    'analysis_date': analysis_date,
                    'total_stocks': len(result_df),
                    'top_stocks': result_df.head(20).to_dict('records'),
                    'analysis_result': result_df.to_dict('records')
                }
            }
            
        except Exception as e:
            log_error(f"종목 분석 중 오류 발생: {e}")
            return {
                'success': False,
                'message': f'종목 분석 중 오류가 발생했습니다: {str(e)}'
            }
    
    
    def get_top_stocks(self, analysis_result, top_n=5, buy_universe_rank=20):
        """
        매수 대상 종목 선정
        
        Args:
            analysis_result: 분석 결과
            top_n: 매수할 종목 수
            buy_universe_rank: 매수 대상 범위
            
        Returns:
            list: 매수 대상 종목 리스트
        """
        if not analysis_result.get('success'):
            return []
        
        try:
            result_df = pd.DataFrame(analysis_result['data']['analysis_result'])
            
            # 매수 대상 범위 내에서 상위 N개 선택
            buy_candidates = result_df[result_df['최종순위'] <= buy_universe_rank]
            top_stocks = buy_candidates.head(top_n)
            
            return top_stocks.to_dict('records')
            
        except Exception as e:
            log_error(f"매수 대상 선정 중 오류 발생: {e}")
            return []


# 전역 인스턴스
deep_learning_analyzer = DeepLearningAnalyzer()
