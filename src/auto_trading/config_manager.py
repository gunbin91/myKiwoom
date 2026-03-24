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
    """자동매매 설정 관리 클래스 (서버별 분리)"""
    
    def __init__(self, server_type='mock'):
        self.server_type = server_type
        self.config_dir = Path(__file__).parent.parent.parent / "data"
        self.config_file = self.config_dir / f"auto_trading_config_{server_type}.json"
        self.trading_result_file = Path(__file__).parent.parent.parent / "logs" / server_type / "trading_result.log"
        
        # 설정 디렉토리 생성
        self.config_dir.mkdir(exist_ok=True)
        self.trading_result_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 서버별 기본 설정
        if server_type == 'mock':
            self.default_config = {
                "auto_trading_enabled": False,
                "schedule_time": "01:30",  # 모의투자는 24시간 가능
                # 장중 손절 감시(자동매매와 별개)
                # - 평가손익률(%)이 threshold_pct 이하로 하락 시 전량 시장가 매도
                "intraday_stop_loss": {
                    "enabled": False,
                    "threshold_pct": -7.0,
                    "sell_forbidden_enabled": False,
                    "sell_forbidden_windows": []
                },
                "strategy_params": {
                    "reserve_cash": 9000000,  # 매매 제외 예수금
                    "max_hold_period": 15,    # 최대 보유 기간
                    "take_profit_pct": 5.0,   # 익절률
                    "stop_loss_pct": 3.0,     # 손절률
                    "top_n": 5,               # 매수 종목 수
                    "buy_universe_rank": 20,  # 매수 대상 범위
                    "transaction_fee_rate": 0.015,  # 거래 수수료율 (%)

                    # 매도 차단 조건: 당일 등락률(전일대비, %)이 임계값 이상이면 매도하지 않음
                    # - 기본값 29.0: 상한가 근처(+29% 이상) 종목 매도 보류
                    # - 0 이하로 설정 시 비활성화
                    "sell_block_daily_change_pct": 29.0,

                    # 매수 주문 방식
                    # - "market": 시장가(기존 동작)
                    # - "limit_ask1": 매도1호가(최우선 매도호가) 기준 지정가 매수
                    "buy_order_method": "market",

                    # limit_ask1 사용 시, 현재가 대비 과도하게 높은 매도1호가로 매수되는 것을 방지
                    # (예: 1.0이면 현재가 대비 +1% 초과 시 가드 발동)
                    "limit_buy_max_premium_pct": 1.0,

                    # 가드 발동 시 처리
                    # - "skip": 매수 주문을 건너뜀(고가매수 방지 우선)
                    # - "market_fallback": 시장가로 폴백(체결 우선, 고가매수 리스크 존재)
                    "limit_buy_guard_action": "skip"
                }
            }
        else:  # real
            self.default_config = {
                "auto_trading_enabled": False,
                "schedule_time": "08:30",  # 실전투자는 거래시간
                # 장중 손절 감시(자동매매와 별개)
                "intraday_stop_loss": {
                    "enabled": False,
                    "threshold_pct": -7.0,
                    "sell_forbidden_enabled": False,
                    "sell_forbidden_windows": []
                },
                "strategy_params": {
                    "reserve_cash": 10000000,  # 매매 제외 예수금
                    "max_hold_period": 10,     # 최대 보유 기간 (더 보수적)
                    "take_profit_pct": 3.0,    # 익절률 (더 보수적)
                    "stop_loss_pct": 2.0,      # 손절률 (더 보수적)
                    "top_n": 3,                # 매수 종목 수 (더 보수적)
                    "buy_universe_rank": 15,   # 매수 대상 범위 (더 보수적)
                    "transaction_fee_rate": 0.015,  # 거래 수수료율 (%)

                    # 매도 차단 조건: 당일 등락률(전일대비, %)이 임계값 이상이면 매도하지 않음
                    # - 기본값 29.0: 상한가 근처(+29% 이상) 종목 매도 보류
                    # - 0 이하로 설정 시 비활성화
                    "sell_block_daily_change_pct": 29.0,

                    # 매수 주문 방식
                    "buy_order_method": "market",

                    # limit_ask1 사용 시, 현재가 대비 과도하게 높은 매도1호가로 매수되는 것을 방지
                    "limit_buy_max_premium_pct": 1.0,

                    # 가드 발동 시 처리
                    "limit_buy_guard_action": "skip"
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
    
    def is_today_executed(self, exclude_execution_types=None):
        """오늘 이미 실행되었는지 확인

        - exclude_execution_types: 특정 실행유형은 '오늘 실행됨' 판정에서 제외
          (예: 장중손절감시는 자동매매와 별개이므로 제외 가능)
        """
        try:
            if not self.trading_result_file.exists():
                return False

            today_str = datetime.now().strftime('%Y-%m-%d')
            exclude_set = {str(x).strip() for x in (exclude_execution_types or []) if str(x).strip()}

            # 로그는 아래 순서로 기록됨:
            # ⏰ 실행 시간: YYYY-MM-DD HH:MM:SS
            # 🔄 실행 유형: <자동/수동/장중손절감시/...>
            current_is_today = False
            current_type = None
            with open(self.trading_result_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 로그 포맷 기준: "⏰ 실행 시간: 2026-01-05 15:04:02"
                    if line.startswith('⏰ 실행 시간:'):
                        time_str = line.replace('⏰ 실행 시간:', '').strip()
                        # 안전하게 날짜만 비교
                        current_is_today = bool(time_str.startswith(today_str))
                        current_type = None
                        continue

                    # 실행 유형 확인 (현재 레코드가 오늘인 경우에만)
                    if current_is_today and line.startswith('🔄 실행 유형:'):
                        current_type = line.replace('🔄 실행 유형:', '').strip()
                        # 제외 대상이면 '오늘 실행됨'에서 제외하고 다음 레코드 탐색
                        if current_type in exclude_set:
                            current_is_today = False
                            current_type = None
                            continue
                        return True

            # 오늘 레코드가 있었지만 실행유형 라인이 없는(구형 포맷) 경우:
            # - 안전을 위해 '오늘 실행됨'으로 간주 (제외 로직 적용 불가)
            return bool(current_is_today)
        except Exception as e:
            print(f"실행 이력 확인 실패: {e}")
            return False
    
    def log_execution(
        self,
        status,
        buy_count=0,
        sell_count=0,
        message="",
        strategy_params=None,
        buy_candidates=None,
        sell_candidates=None,
        execution_type="자동",
        error_details=None,
        buy_results=None,
        sell_results=None,
        account_info=None,
        # --- v2 확장 필드 (하위호환 유지: optional) ---
        analysis_meta=None,
        excluded_candidates=None,
        excluded_summary=None,
        execution_trace=None,
        analysis_top60=None,
    ):
        """자동매매 실행 결과 상세 기록"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            server_name = "모의투자" if self.server_type == "mock" else "실전투자"

            # 실행 상세 JSON 저장(화면에서 바로 보기 용도)
            try:
                detail_dir = self.trading_result_file.parent / "execution_details"
                detail_dir.mkdir(parents=True, exist_ok=True)
                safe_ts = timestamp.replace(":", "-").replace(" ", "_")
                detail_filename = f"execution_detail_{safe_ts}.json"
                detail_path = detail_dir / detail_filename
                detail_payload = {
                    "schema_version": 2,
                    "timestamp": timestamp,
                    "server_type": self.server_type,
                    "execution_type": execution_type,
                    "status": status,
                    "message": message,
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "strategy_params": strategy_params or {},
                    "buy_results": buy_results or {},
                    "sell_results": sell_results or {},
                    "buy_candidates": buy_candidates or [],
                    "sell_candidates": sell_candidates or [],
                    "analysis_meta": analysis_meta or {},
                    "analysis_top60": analysis_top60 or [],
                    "excluded_summary": excluded_summary or {},
                    "excluded_candidates": excluded_candidates or [],
                    "execution_trace": execution_trace or [],
                }
                with open(detail_path, "w", encoding="utf-8") as f:
                    json.dump(detail_payload, f, ensure_ascii=False, indent=2)
            except Exception as json_err:
                detail_filename = None
                print(f"실행 상세 JSON 저장 실패: {json_err}")
            
            # 기본 정보
            log_entry = f"\n{'='*100}\n"
            log_entry += f"🤖 자동매매 실행 결과 - {server_name} ({self.server_type})\n"
            log_entry += f"⏰ 실행 시간: {timestamp}\n"
            log_entry += f"🔄 실행 유형: {execution_type}\n"
            log_entry += f"📊 실행 상태: {status}\n"
            log_entry += f"📈 매수 시도: {buy_count}건\n"
            log_entry += f"📉 매도 시도: {sell_count}건\n"
            log_entry += f"💬 메시지: {message}\n"
            if detail_filename:
                log_entry += f"🧾 상세파일: {detail_filename}\n"
            
            # 계좌 정보 (실행 전/후 예수금 비교)
            if account_info:
                deposit_info = account_info.get('deposit', {})
                balance_info = account_info.get('balance', {})
                
                log_entry += f"\n💰 계좌 정보:\n"
                total_deposit = int(deposit_info.get('entr', 0))
                reserve_cash = strategy_params.get('reserve_cash', 0) if strategy_params else 0
                available_amount = max(0, total_deposit - reserve_cash)
                
                log_entry += f"  - 총 예수금: {total_deposit:,}원\n"
                log_entry += f"  - 주문가능금액(100%): {int(deposit_info.get('100stk_ord_alow_amt', 0)):,}원\n"
                log_entry += f"  - D+1 추정예수금: {int(deposit_info.get('d1_entra', 0)):,}원\n"
                log_entry += f"  - D+2 추정예수금: {int(deposit_info.get('d2_entra', 0)):,}원\n"
                log_entry += f"  - 사용가능금액: {available_amount:,}원 (총예수금 - 매매제외예수금)\n"
                
                if balance_info and 'output1' in balance_info:
                    holdings = balance_info['output1']
                    log_entry += f"  - 보유 종목 수: {len(holdings)}개\n"
            
            # 전략 파라미터 정보
            if strategy_params:
                log_entry += f"\n⚙️ 전략 파라미터:\n"
                
                # 파라미터 한글명 매핑
                param_names = {
                    'reserve_cash': '매매제외예수금',
                    'transaction_fee_rate': '수수료율',
                    'take_profit_pct': '익절률',
                    'stop_loss_pct': '손절률',
                    'sell_block_daily_change_pct': '당일등락률 매도차단(%)',
                    'max_hold_period': '최대보유기간',
                    'investment_amount': '투자금액',
                    'max_stocks': '최대종목수',
                    'min_price': '최소가격',
                    'max_price': '최대가격',
                    'min_volume': '최소거래량',
                    'confidence_threshold': '신뢰도임계값'
                }
                
                for key, value in strategy_params.items():
                    korean_name = param_names.get(key, key)
                    if isinstance(value, (int, float)):
                        if 'rate' in key.lower() or 'fee' in key.lower() or 'pct' in key.lower():
                            log_entry += f"  - {korean_name}: {value}%\n"
                        elif 'cash' in key.lower() or 'amount' in key.lower():
                            log_entry += f"  - {korean_name}: {value:,}원\n"
                        elif 'period' in key.lower() or 'days' in key.lower():
                            log_entry += f"  - {korean_name}: {value}일\n"
                        elif 'stocks' in key.lower() or 'count' in key.lower():
                            log_entry += f"  - {korean_name}: {value}개\n"
                        else:
                            log_entry += f"  - {korean_name}: {value}\n"
                    else:
                        log_entry += f"  - {korean_name}: {value}\n"
            
            # 매수 실행 결과 상세 정보
            if buy_results:
                log_entry += f"\n📈 매수 실행 결과:\n"
                log_entry += f"  - 총 시도: {buy_results.get('total_attempts', 0)}건\n"
                log_entry += f"  - 성공: {buy_results.get('success_count', 0)}건\n"
                log_entry += f"  - 실패: {buy_results.get('failed_count', 0)}건\n"
                if buy_results.get('skipped_count', 0):
                    log_entry += f"  - 스킵: {buy_results.get('skipped_count', 0)}건\n"
                log_entry += f"  - 총 매수금액: {buy_results.get('total_buy_amount', 0):,}원\n"
                log_entry += f"  - 총 매수수량: {buy_results.get('total_buy_quantity', 0):,}주\n"
                
                if buy_results.get('details'):
                    log_entry += f"\n  📋 매수 상세 내역:\n"
                    for i, detail in enumerate(buy_results['details'], 1):
                        stock_name = detail.get('stock_name', 'N/A')
                        stock_code = detail.get('stock_code', 'N/A')
                        quantity = detail.get('quantity', 0)
                        price = detail.get('price', 0)
                        amount = detail.get('amount', 0)
                        status = detail.get('status', 'N/A')
                        error_msg = detail.get('error_message', '')
                        reason = detail.get('reason', 'AI 분석 추천')
                        
                        log_entry += f"    {i}. {stock_name}({stock_code})\n"
                        log_entry += f"       - 수량: {quantity:,}주\n"
                        log_entry += f"       - 가격: {price:,}원\n"
                        log_entry += f"       - 금액: {amount:,}원\n"
                        log_entry += f"       - 상태: {status}\n"
                        log_entry += f"       - 매수사유: {reason}\n"
                        if error_msg:
                            if str(status).strip() == "스킵":
                                log_entry += f"       - 스킵사유: {error_msg}\n"
                            else:
                                log_entry += f"       - 실패사유: {error_msg}\n"
            
            # 매도 실행 결과 상세 정보
            if sell_results:
                log_entry += f"\n📉 매도 실행 결과:\n"
                log_entry += f"  - 총 시도: {sell_results.get('total_attempts', 0)}건\n"
                log_entry += f"  - 성공: {sell_results.get('success_count', 0)}건\n"
                log_entry += f"  - 실패: {sell_results.get('failed_count', 0)}건\n"
                log_entry += f"  - 총 매도금액: {sell_results.get('total_sell_amount', 0):,}원\n"
                log_entry += f"  - 총 매도수량: {sell_results.get('total_sell_quantity', 0):,}주\n"
                
                if sell_results.get('details'):
                    log_entry += f"\n  📋 매도 상세 내역:\n"
                    for i, detail in enumerate(sell_results['details'], 1):
                        stock_name = detail.get('stock_name', 'N/A')
                        stock_code = detail.get('stock_code', 'N/A')
                        quantity = detail.get('quantity', 0)
                        price = detail.get('price', 0)
                        amount = detail.get('amount', 0)
                        status = detail.get('status', 'N/A')
                        error_msg = detail.get('error_message', '')
                        reason = detail.get('reason', 'N/A')
                        
                        log_entry += f"    {i}. {stock_name}({stock_code})\n"
                        log_entry += f"       - 수량: {quantity:,}주\n"
                        log_entry += f"       - 가격: {price:,}원\n"
                        log_entry += f"       - 금액: {amount:,}원\n"
                        log_entry += f"       - 상태: {status}\n"
                        log_entry += f"       - 매도사유: {reason}\n"
                        if error_msg:
                            log_entry += f"       - 실패사유: {error_msg}\n"
            
            # 매수 대상 종목 정보 (실행 전 계획)
            if buy_candidates:
                log_entry += f"\n📋 매수 대상 종목 계획 ({len(buy_candidates)}개):\n"
                for i, candidate in enumerate(buy_candidates, 1):
                    stock_code = candidate.get('종목코드', 'N/A')
                    stock_name = candidate.get('종목명', 'N/A')
                    quantity = candidate.get('수량', 'N/A')
                    price = candidate.get('가격', 'N/A')
                    reason = candidate.get('매수사유', 'N/A')
                    log_entry += f"  {i}. {stock_name}({stock_code}) - 수량:{quantity}, 가격:{price}원, 사유:{reason}\n"
            
            # 매도 대상 종목 정보 (실행 전 계획)
            if sell_candidates:
                log_entry += f"\n📋 매도 대상 종목 계획 ({len(sell_candidates)}개):\n"
                for i, candidate in enumerate(sell_candidates, 1):
                    stock_code = candidate.get('종목코드', 'N/A')
                    stock_name = candidate.get('종목명', 'N/A')
                    quantity = candidate.get('수량', 'N/A')
                    price = candidate.get('가격', 'N/A')
                    reason = candidate.get('매도사유', 'N/A')
                    log_entry += f"  {i}. {stock_name}({stock_code}) - 수량:{quantity}, 가격:{price}원, 사유:{reason}\n"
            
            # 에러 상세 정보
            if error_details:
                log_entry += f"\n❌ 에러 상세 정보:\n"
                if isinstance(error_details, dict):
                    for key, value in error_details.items():
                        log_entry += f"  - {key}: {value}\n"
                else:
                    log_entry += f"  {error_details}\n"
            
            log_entry += f"{'='*100}\n"
            
            # 날짜별 로테이션을 위한 로그 파일 관리
            self._write_with_rotation(log_entry)
        except Exception as e:
            print(f"실행 이력 기록 실패: {e}")
    
    def _write_with_rotation(self, log_entry):
        """날짜별 로테이션을 적용한 로그 파일 쓰기"""
        try:
            from datetime import datetime
            import os
            import glob
            import platform
            
            # 현재 날짜
            today = datetime.now().strftime('%Y-%m-%d')
            
            # 오늘 날짜의 로그 파일 경로
            today_log_file = self.trading_result_file.parent / f"trading_result_{today}.log"

            # Windows에서는 심볼릭 링크 생성이 관리자 권한을 요구(WinError 1314)할 수 있으므로,
            # 링크 기반 로테이션을 사용하지 않고, 날짜별 파일 + trading_result.log 둘 다에 기록한다.
            is_windows = (os.name == 'nt') or (platform.system().lower() == 'windows')

            if is_windows:
                # 날짜별 파일에 기록
                with open(today_log_file, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
                # trading_result.log(하위 호환)에도 같이 기록
                with open(self.trading_result_file, 'a', encoding='utf-8') as f:
                    f.write(log_entry)

                # 오래된 로그 파일 정리만 수행
                self._cleanup_old_logs()
                return
            
            # 기존 trading_result.log가 있고 오늘 날짜가 아니면 백업
            if self.trading_result_file.exists():
                # 기존 파일의 수정 시간 확인
                file_mtime = datetime.fromtimestamp(os.path.getmtime(self.trading_result_file))
                file_date = file_mtime.strftime('%Y-%m-%d')
                
                # 오늘 날짜가 아니면 날짜별 파일로 이동
                if file_date != today:
                    backup_file = self.trading_result_file.parent / f"trading_result_{file_date}.log"
                    if not backup_file.exists():
                        os.rename(self.trading_result_file, backup_file)
                    else:
                        # 이미 같은 날짜 파일이 있으면 기존 파일에 추가
                        with open(backup_file, 'a', encoding='utf-8') as f:
                            with open(self.trading_result_file, 'r', encoding='utf-8') as old_f:
                                f.write(old_f.read())
                        os.remove(self.trading_result_file)
            
            # 오늘 날짜의 로그 파일에 쓰기
            with open(today_log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
            
            # 심볼릭 링크 또는 현재 파일 업데이트 (하위 호환성)
            if self.trading_result_file.exists() and not os.path.islink(self.trading_result_file):
                # 기존 파일이 심볼릭 링크가 아니면 삭제하고 심볼릭 링크 생성
                os.remove(self.trading_result_file)
                os.symlink(today_log_file.name, self.trading_result_file)
            elif not self.trading_result_file.exists():
                # 파일이 없으면 심볼릭 링크 생성
                os.symlink(today_log_file.name, self.trading_result_file)
            
            # 30일 이상 된 로그 파일 정리
            self._cleanup_old_logs()
            
        except Exception as e:
            # 폴백: 기존 방식으로 쓰기
            with open(self.trading_result_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
            print(f"로그 파일 로테이션 실패, 기본 방식으로 기록: {e}")
    
    def _cleanup_old_logs(self):
        """30일 이상 된 로그 파일 정리"""
        try:
            from datetime import datetime, timedelta
            import os
            import glob
            
            # 30일 전 날짜
            cutoff_date = datetime.now() - timedelta(days=30)
            
            # trading_result_*.log 패턴의 파일들 찾기
            log_pattern = str(self.trading_result_file.parent / "trading_result_*.log")
            log_files = glob.glob(log_pattern)
            
            for log_file in log_files:
                try:
                    # 파일명에서 날짜 추출
                    filename = os.path.basename(log_file)
                    if filename.startswith('trading_result_') and filename.endswith('.log'):
                        date_str = filename.replace('trading_result_', '').replace('.log', '')
                        file_date = datetime.strptime(date_str, '%Y-%m-%d')
                        
                        # 30일 이상 된 파일 삭제
                        if file_date < cutoff_date:
                            os.remove(log_file)
                            print(f"오래된 로그 파일 삭제: {log_file}")
                except Exception as e:
                    print(f"로그 파일 정리 중 오류 ({log_file}): {e}")
                    
        except Exception as e:
            print(f"로그 파일 정리 실패: {e}")
    
    def get_execution_history(self, days=7):
        """실행 이력 조회 (간단한 요약 정보만)"""
        try:
            if not self.trading_result_file.exists():
                return []
            
            history = []
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with open(self.trading_result_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 구분자로 분리하여 각 실행 결과 파싱
            sections = content.split('='*80)
            
            for section in sections:
                if not section.strip():
                    continue
                    
                try:
                    lines = section.strip().split('\n')
                    if len(lines) < 5:
                        continue
                    
                    # 기본 정보 추출
                    execution_time = None
                    status = None
                    buy_count = 0
                    sell_count = 0
                    message = ""
                    execution_type = "자동"
                    details_file = None
                    total_deposit = 0
                    available_amount = 0
                    holdings_count = 0
                    buy_success_count = 0
                    buy_failed_count = 0
                    sell_success_count = 0
                    sell_failed_count = 0
                    total_buy_amount = 0
                    total_sell_amount = 0
                    
                    # 현재 섹션 추적
                    current_section = ""
                    
                    for line in lines:
                        # 섹션 추적
                        if '📈 매수 실행 결과:' in line:
                            current_section = "buy"
                        elif '📉 매도 실행 결과:' in line:
                            current_section = "sell"
                        elif '💰 계좌 정보:' in line:
                            current_section = "account"
                        elif '⚙️ 전략 파라미터:' in line:
                            current_section = "strategy"
                        elif '📋 매수 상세 내역:' in line:
                            current_section = "buy_detail"
                        elif '📋 매도 상세 내역:' in line:
                            current_section = "sell_detail"
                        elif '📋 매수 대상 종목 계획:' in line:
                            current_section = "buy_plan"
                        elif '📋 매도 대상 종목 계획:' in line:
                            current_section = "sell_plan"
                        
                        if '⏰ 실행 시간:' in line:
                            time_str = line.replace('⏰ 실행 시간:', '').strip()
                            execution_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                        elif '📊 실행 상태:' in line:
                            status = line.replace('📊 실행 상태:', '').strip()
                        elif '📈 매수 시도:' in line:
                            buy_str = line.replace('📈 매수 시도:', '').replace('건', '').strip()
                            buy_count = int(buy_str)
                        elif '📉 매도 시도:' in line:
                            sell_str = line.replace('📉 매도 시도:', '').replace('건', '').strip()
                            sell_count = int(sell_str)
                        elif '💬 메시지:' in line:
                            message = line.replace('💬 메시지:', '').strip()
                        elif '🧾 상세파일:' in line:
                            details_file = line.replace('🧾 상세파일:', '').strip()
                        elif '🔄 실행 유형:' in line:
                            execution_type = line.replace('🔄 실행 유형:', '').strip()
                        elif '- 총 예수금:' in line and current_section == "account":
                            deposit_str = line.replace('- 총 예수금:', '').replace('원', '').replace(',', '').strip()
                            total_deposit = int(deposit_str) if deposit_str.isdigit() else 0
                        elif '- 주문가능금액:' in line and current_section == "account":
                            amount_str = line.replace('- 주문가능금액:', '').replace('원', '').replace(',', '').strip()
                            # 괄호 안의 설명 제거
                            if '(' in amount_str:
                                amount_str = amount_str.split('(')[0].strip()
                            available_amount = int(amount_str) if amount_str.isdigit() else 0
                        elif '보유 종목 수:' in line:
                            holdings_str = line.replace('보유 종목 수:', '').replace('개', '').strip()
                            holdings_count = int(holdings_str) if holdings_str.isdigit() else 0
                        elif '- 성공:' in line and current_section == "buy":
                            success_str = line.replace('- 성공:', '').replace('건', '').strip()
                            buy_success_count = int(success_str) if success_str.isdigit() else 0
                        elif '- 실패:' in line and current_section == "buy":
                            failed_str = line.replace('- 실패:', '').replace('건', '').strip()
                            buy_failed_count = int(failed_str) if failed_str.isdigit() else 0
                        elif '- 성공:' in line and current_section == "sell":
                            success_str = line.replace('- 성공:', '').replace('건', '').strip()
                            sell_success_count = int(success_str) if success_str.isdigit() else 0
                        elif '- 실패:' in line and current_section == "sell":
                            failed_str = line.replace('- 실패:', '').replace('건', '').strip()
                            sell_failed_count = int(failed_str) if failed_str.isdigit() else 0
                        elif '- 총 매수금액:' in line and current_section == "buy":
                            amount_str = line.replace('- 총 매수금액:', '').replace('원', '').replace(',', '').strip()
                            total_buy_amount = int(amount_str) if amount_str.isdigit() else 0
                        elif '- 총 매도금액:' in line and current_section == "sell":
                            amount_str = line.replace('- 총 매도금액:', '').replace('원', '').replace(',', '').strip()
                            total_sell_amount = int(amount_str) if amount_str.isdigit() else 0
                    
                    if execution_time and execution_time >= cutoff_date:
                        history.append({
                            'execution_time': execution_time.strftime('%Y-%m-%d %H:%M:%S'),
                            'status': status,
                            'buy_count': buy_count,
                            'sell_count': sell_count,
                            'message': message,
                            'execution_type': execution_type,
                            'details_file': details_file,
                            'total_deposit': total_deposit,
                            'available_amount': available_amount,
                            'holdings_count': holdings_count,
                            'buy_success_count': buy_success_count,
                            'buy_failed_count': buy_failed_count,
                            'sell_success_count': sell_success_count,
                            'sell_failed_count': sell_failed_count,
                            'total_buy_amount': total_buy_amount,
                            'total_sell_amount': total_sell_amount
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


# 전역 인스턴스들 (서버별)
mock_config_manager = AutoTradingConfigManager('mock')
real_config_manager = AutoTradingConfigManager('real')

# 기존 호환성을 위한 별칭 (기본값: 모의투자)
config_manager = mock_config_manager
