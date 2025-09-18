"""
자동매매 스케줄러 (멀티프로세싱 지원)
"""
import multiprocessing
import threading
import time
import signal
import sys
import os
from datetime import datetime, timedelta
from src.auto_trading.config_manager import AutoTradingConfigManager
from src.auto_trading.engine import AutoTradingEngine
from src.utils import get_current_auto_trading_logger
from src.config.server_config import get_current_server_config


class AutoTradingScheduler:
    """자동매매 스케줄러 클래스 (멀티프로세싱 지원)"""
    
    def __init__(self, server_type='mock'):
        self.server_type = server_type
        self.is_running = False
        self.scheduler_process = None
        self.check_interval = 60  # 1분마다 체크
        self.last_check_time = None  # 마지막 체크 시간
        self.is_executing = False  # 현재 자동매매 실행 중인지 확인
        
        # 로거는 멀티프로세싱 프로세스 내부에서 생성 (직렬화 문제 방지)
        self.auto_trading_logger = None
        
        # 서버별 설정 로드
        self.server_config = get_current_server_config()
        # 서버별 config_manager 인스턴스 생성
        self.config_manager = AutoTradingConfigManager(server_type)
        # 서버별 engine 인스턴스 생성
        self.engine = AutoTradingEngine(server_type)
    
    def start(self):
        """스케줄러 시작 (별도 프로세스)"""
        if self.is_running and self.scheduler_process and self.scheduler_process.is_alive():
            print(f"스케줄러가 이미 실행 중입니다. (서버: {self.server_type})")
            return
        
        # 기존 프로세스가 있다면 정리
        if self.scheduler_process and self.scheduler_process.is_alive():
            print(f"기존 스케줄러 프로세스를 정리합니다. (서버: {self.server_type})")
            self.scheduler_process.terminate()
            self.scheduler_process.join(timeout=2)
            if self.scheduler_process.is_alive():
                self.scheduler_process.kill()
        
        self.is_running = True
        self.scheduler_process = multiprocessing.Process(
            target=self._scheduler_loop,
            name=f"AutoTradingScheduler-{self.server_type}",
            daemon=True
        )
        self.scheduler_process.start()
        print(f"📅 자동매매 스케줄러가 시작되었습니다. (서버: {self.server_type})")
    
    def stop(self):
        """스케줄러 중지"""
        self.is_running = False
        if self.scheduler_process and self.scheduler_process.is_alive():
            self.scheduler_process.terminate()
            self.scheduler_process.join(timeout=5)
            if self.scheduler_process.is_alive():
                self.scheduler_process.kill()
        print(f"🛑 자동매매 스케줄러가 중지되었습니다. (서버: {self.server_type})")
    
    def _scheduler_loop(self):
        """스케줄러 메인 루프 (별도 프로세스에서 실행)"""
        # 프로세스별 설정 초기화
        from src.config.server_config import set_server_type
        set_server_type(self.server_type)
        
        # 프로세스 내부에서 로거 생성 (직렬화 문제 방지)
        # 서버 타입을 명시적으로 지정하여 올바른 로그 파일에 기록
        from src.utils import get_server_logger
        self.auto_trading_logger = get_server_logger(server_type=self.server_type, log_type="auto_trading").bind(server=self.server_type)
        
        # 시그널 핸들러 설정
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        self.auto_trading_logger.info(f"스케줄러 프로세스 시작 (PID: {os.getpid()}, 서버: {self.server_type})")
        
        while self.is_running:
            try:
                self._check_and_execute()
                time.sleep(self.check_interval)
            except Exception as e:
                self.auto_trading_logger.error(f"스케줄러 루프 오류: {e}")
                time.sleep(self.check_interval)
        
        self.auto_trading_logger.info(f"스케줄러 프로세스 종료 (PID: {os.getpid()})")
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러"""
        if self.auto_trading_logger:
            self.auto_trading_logger.info(f"시그널 수신: {signum}, 스케줄러 종료 중...")
        else:
            print(f"시그널 수신: {signum}, 스케줄러 종료 중...")
        self.is_running = False
    
    def _check_and_execute(self):
        """실행 시간 확인 및 자동매매 실행"""
        try:
            # 설정 로드
            config = self.config_manager.load_config()
            
            # 자동매매가 비활성화되어 있으면 스킵 (체크 시간도 업데이트하지 않음)
            if not config.get('auto_trading_enabled', False):
                return
            
            # 자동매매가 활성화되어 있을 때만 체크 시간 업데이트
            self.last_check_time = datetime.now()
            
            # 실행 시간 확인
            if not self._is_execution_time(config):
                return
            
            # 오늘 이미 실행했는지 확인
            if self.config_manager.is_today_executed():
                return
            
            # 현재 실행 중인지 확인 (중복 실행 방지)
            if self.is_executing:
                self.auto_trading_logger.warning("⚠️ 자동매매가 이미 실행 중입니다. 중복 실행을 방지합니다.")
                return
            
            # 자동매매 실행
            self.is_executing = True
            try:
                self.auto_trading_logger.info(f"⏰ 스케줄된 시간에 자동매매를 실행합니다. (서버: {self.server_type})")
                result = self.engine.execute_strategy()
                
                if result['success']:
                    self.auto_trading_logger.info(f"✅ 스케줄된 자동매매 실행 완료 (서버: {self.server_type}): {result['message']}")
                else:
                    self.auto_trading_logger.error(f"❌ 스케줄된 자동매매 실행 실패 (서버: {self.server_type}): {result['message']}")
            finally:
                # 실행 완료 후 플래그 해제
                self.is_executing = False
                
        except Exception as e:
            self.auto_trading_logger.error(f"스케줄러 실행 확인 중 오류: {e}")
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
            self.auto_trading_logger.error(f"실행 시간 확인 중 오류: {e}")
            return False
    
    def get_next_execution_time(self):
        """다음 실행 시간 계산"""
        try:
            config = self.config_manager.load_config()
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
            self.auto_trading_logger.error(f"다음 실행 시간 계산 중 오류: {e}")
            return None
    
    def get_last_check_time(self):
        """마지막 스케줄러 체크 시간 조회"""
        if self.last_check_time:
            return self.last_check_time.strftime('%Y-%m-%d %H:%M:%S')
        return None
    
    def is_currently_executing(self):
        """현재 자동매매가 실행 중인지 확인"""
        return self.is_executing


# 전역 인스턴스들 (모의투자/실전투자 동시 실행)
mock_scheduler = AutoTradingScheduler('mock')
real_scheduler = AutoTradingScheduler('real')

# 기존 호환성을 위한 별칭
auto_trading_scheduler = mock_scheduler
