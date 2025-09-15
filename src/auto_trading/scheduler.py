"""
자동매매 스케줄러
"""
import threading
import time
from datetime import datetime, timedelta
from src.auto_trading.config_manager import config_manager
from src.auto_trading.engine import auto_trading_engine
from src.utils import web_logger


class AutoTradingScheduler:
    """자동매매 스케줄러 클래스"""
    
    def __init__(self):
        self.is_running = False
        self.scheduler_thread = None
        self.check_interval = 60  # 1분마다 체크
        self.last_check_time = None  # 마지막 체크 시간
        self.is_executing = False  # 현재 자동매매 실행 중인지 확인
    
    def start(self):
        """스케줄러 시작"""
        if self.is_running:
            web_logger.warning("스케줄러가 이미 실행 중입니다.")
            return
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        web_logger.info("📅 자동매매 스케줄러가 시작되었습니다.")
    
    def stop(self):
        """스케줄러 중지"""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        web_logger.info("🛑 자동매매 스케줄러가 중지되었습니다.")
    
    def _scheduler_loop(self):
        """스케줄러 메인 루프"""
        while self.is_running:
            try:
                self._check_and_execute()
                time.sleep(self.check_interval)
            except Exception as e:
                web_logger.error(f"스케줄러 루프 오류: {e}")
                time.sleep(self.check_interval)
    
    def _check_and_execute(self):
        """실행 시간 확인 및 자동매매 실행"""
        try:
            # 설정 로드
            config = config_manager.load_config()
            
            # 자동매매가 비활성화되어 있으면 스킵 (체크 시간도 업데이트하지 않음)
            if not config.get('auto_trading_enabled', False):
                return
            
            # 자동매매가 활성화되어 있을 때만 체크 시간 업데이트
            self.last_check_time = datetime.now()
            
            # 실행 시간 확인
            if not self._is_execution_time(config):
                return
            
            # 오늘 이미 실행했는지 확인
            if config_manager.is_today_executed():
                return
            
            # 현재 실행 중인지 확인 (중복 실행 방지)
            if self.is_executing:
                web_logger.warning("⚠️ 자동매매가 이미 실행 중입니다. 중복 실행을 방지합니다.")
                return
            
            # 자동매매 실행
            self.is_executing = True
            try:
                web_logger.info("⏰ 스케줄된 시간에 자동매매를 실행합니다.")
                result = auto_trading_engine.execute_strategy()
                
                if result['success']:
                    web_logger.info(f"✅ 스케줄된 자동매매 실행 완료: {result['message']}")
                else:
                    web_logger.error(f"❌ 스케줄된 자동매매 실행 실패: {result['message']}")
            finally:
                # 실행 완료 후 플래그 해제
                self.is_executing = False
                
        except Exception as e:
            web_logger.error(f"스케줄러 실행 확인 중 오류: {e}")
            # 예외 발생 시에도 실행 플래그 해제
            self.is_executing = False
    
    def _is_execution_time(self, config):
        """실행 시간인지 확인"""
        try:
            now = datetime.now()
            schedule_time = config.get('schedule_time', '08:30')
            
            # 시간 파싱 (24시간 형식)
            hour, minute = map(int, schedule_time.split(':'))
            
            # 실행 시간 범위 (정확한 시간 ±1분)
            target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            time_range_start = target_time - timedelta(minutes=1)
            time_range_end = target_time + timedelta(minutes=1)
            
            return time_range_start <= now <= time_range_end
            
        except Exception as e:
            web_logger.error(f"실행 시간 확인 중 오류: {e}")
            return False
    
    def get_next_execution_time(self):
        """다음 실행 시간 계산"""
        try:
            config = config_manager.load_config()
            schedule_time = config.get('schedule_time', '08:30')
            
            # 시간 파싱 (24시간 형식)
            hour, minute = map(int, schedule_time.split(':'))
            
            now = datetime.now()
            next_execution = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # 오늘 이미 지났으면 내일로
            if next_execution <= now:
                next_execution += timedelta(days=1)
            
            return next_execution
            
        except Exception as e:
            web_logger.error(f"다음 실행 시간 계산 중 오류: {e}")
            return None
    
    def get_last_check_time(self):
        """마지막 스케줄러 체크 시간 조회"""
        if self.last_check_time:
            return self.last_check_time.strftime('%Y-%m-%d %H:%M:%S')
        return None
    
    def is_currently_executing(self):
        """현재 자동매매가 실행 중인지 확인"""
        return self.is_executing


# 전역 인스턴스
auto_trading_scheduler = AutoTradingScheduler()
