@echo off
chcp 65001 >nul

REM 키움 자동매매 환경 설정 및 웹 대시보드 시작 스크립트 (Windows)

echo ==========================================
echo 키움 자동매매 환경 설정 및 웹 대시보드 시작
echo ==========================================

REM 프로젝트 루트 디렉토리로 이동
cd /d "%~dp0\.."

REM Python 버전 확인
echo Python 버전 확인 중...
python --version

REM 가상환경이 없으면 생성
if not exist venv (
    echo 가상환경 생성 중...
    python -m venv venv
) else (
    echo 기존 가상환경 사용
)

REM 가상환경 활성화
echo 가상환경 활성화 중...
call venv\Scripts\activate.bat

REM pip 업그레이드
echo pip 업그레이드 중...
python -m pip install --upgrade pip

REM 의존성 설치
echo 의존성 설치 중...
pip install -r requirements.txt

REM 자동매매에 필요한 추가 패키지 설치
echo 자동매매 추가 패키지 설치 중...
pip install joblib pandas numpy scikit-learn pyarrow fastparquet

REM ==========================================================
REM pandas_ta posix module import fix for Windows
REM ==========================================================
echo "Fixing pandas_ta posix import issue..."
SET "VENV_SITE_PACKAGES=%CD%\venv\Lib\site-packages"
SET "ALLIGATOR_FILE=%VENV_SITE_PACKAGES%\pandas_ta\overlap\alligator.py"
IF EXIST "%ALLIGATOR_FILE%" (
    powershell -Command "(Get-Content \"%ALLIGATOR_FILE%\") | Where-Object {$_ -notmatch \"from posix import pread\"} | Set-Content \"%ALLIGATOR_FILE%\""
    IF %ERRORLEVEL% NEQ 0 (
        echo "Failed to fix pandas_ta posix import issue."
    ) ELSE (
        echo "pandas_ta posix import issue fixed."
    )
) ELSE (
    echo "alligator.py not found at %ALLIGATOR_FILE%. Skipping fix."
)
REM ==========================================================

REM 필요한 디렉토리 생성
echo 필요한 디렉토리 생성 중...
if not exist logs mkdir logs
if not exist cache mkdir cache
if not exist data mkdir data

REM 환경 변수 설정
set PYTHONPATH=%PYTHONPATH%;%CD%\src

echo ==========================================
echo 설정 완료! 웹 서버를 시작합니다...
echo ==========================================
echo 브라우저에서 http://127.0.0.1:5001 으로 접속하세요.
echo 자동매매 페이지: http://127.0.0.1:5001/auto-trading
echo.
echo 서버를 중지하려면 Ctrl+C를 누르세요.
echo ==========================================

REM 웹 서버 시작
python -m src.web.app

pause

