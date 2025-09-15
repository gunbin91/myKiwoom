# -*- coding: utf-8 -*-
"""
자동매매 설정 관리 모듈
"""
import sys
import os
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

# 환경 변수 설정
os.environ['PYTHONIOENCODING'] = 'utf-8'


class AutoTradingConfigManager:
    """자동매매 설정 관리 클래스"""
    
    def __init__(self):
        self.config_dir = Path(__file__).parent.parent.parent / "data"
        self.config_file = self.config_dir / "auto_trading_config.json"
        self.execution_log_file = self.config_dir / "auto_trading_execution.log"
        
        # 설정 디렉토리 생성
        self.config_dir.mkdir(exist_ok=True)
        
        # 기본 설정
        self.default_config = {
            "auto_trading_enabled": False,
            "schedule_time": "08:30",
            "strategy_params": {
                "reserve_cash": 1000000,  # 매매 제외 예수금
                "max_hold_period": 15,    # 최대 보유 기간
                "take_profit_pct": 5.0,   # 익절률
                "stop_loss_pct": 3.0,     # 손절률
                "top_n": 5,               # 매수 종목 수
                "buy_universe_rank": 20,  # 매수 대상 범위
                "transaction_fee_rate": 0.015  # 거래 수수료율 (%)
            }
        }
    
    def load_config(self):
        """설정 파일 로드"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 기본값과 병합 (새로운 설정 추가 시)
                    return self._merge_config(self.default_config, config)
            else:
                # 기본 설정으로 파일 생성
                self.save_config(self.default_config)
                return self.default_config.copy()
        except Exception as e:
            print(f"설정 로드 실패: {e}")
            return self.default_config.copy()
    
    def save_config(self, config):
        """설정 파일 저장"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"설정 저장 실패: {e}")
            return False
    
    def _merge_config(self, default, user):
        """기본 설정과 사용자 설정 병합"""
        merged = default.copy()
        for key, value in user.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._merge_config(merged[key], value)
            else:
                merged[key] = value
        return merged
    
    def is_today_executed(self):
        """오늘 이미 실행되었는지 확인"""
        try:
            if not self.execution_log_file.exists():
                return False
            
            today = datetime.now().strftime('%Y-%m-%d')
            with open(self.execution_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith(today):
                        return True
            return False
        except Exception as e:
            print(f"실행 이력 확인 실패: {e}")
            return False
    
    def log_execution(self, status, buy_count=0, sell_count=0, message=""):
        """실행 이력 기록"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"{timestamp} | {status} | 매수:{buy_count} | 매도:{sell_count} | {message}\n"
            
            with open(self.execution_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"실행 이력 기록 실패: {e}")
    
    def get_execution_history(self, days=7):
        """실행 이력 조회"""
        try:
            if not self.execution_log_file.exists():
                return []
            
            history = []
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with open(self.execution_log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        parts = line.split(' | ')
                        if len(parts) >= 4:
                            timestamp_str = parts[0]
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            
                            if timestamp >= cutoff_date:
                                status = parts[1]
                                buy_info = parts[2].split(':')[1] if ':' in parts[2] else '0'
                                sell_info = parts[3].split(':')[1] if ':' in parts[3] else '0'
                                message = parts[4] if len(parts) > 4 else ''
                                
                                history.append({
                                    'execution_time': timestamp_str,
                                    'status': status,
                                    'buy_count': int(buy_info),
                                    'sell_count': int(sell_info),
                                    'message': message
                                })
                    except Exception as e:
                        print(f"이력 파싱 오류: {e}")
                        continue
            
            return sorted(history, key=lambda x: x['execution_time'], reverse=True)
        except Exception as e:
            print(f"실행 이력 조회 실패: {e}")
            return []
    
    def get_last_execution_time(self):
        """마지막 실행 시간 조회"""
        try:
            history = self.get_execution_history(days=30)
            if history:
                return history[0]['execution_time']
            return None
        except Exception as e:
            print(f"마지막 실행 시간 조회 실패: {e}")
            return None


# 전역 인스턴스
config_manager = AutoTradingConfigManager()
