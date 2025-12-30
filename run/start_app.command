#!/bin/bash

# 키움 자동매매 환경 설정 및 웹 대시보드 시작 스크립트 (macOS)

echo "=========================================="
echo "키움 자동매매 환경 설정 및 웹 대시보드 시작"
echo "=========================================="

# 프로젝트 루트 디렉토리로 이동
cd "$(dirname "$0")/.."

# Python 버전 확인
echo "Python 버전 확인 중..."
python3 --version

# 가상환경이 없으면 생성
if [ ! -d "venv" ]; then
    echo "가상환경 생성 중..."
    python3.12 -m venv venv
else
    echo "기존 가상환경 사용"
fi

# 가상환경 활성화
echo "가상환경 활성화 중..."
source venv/bin/activate

# pip 업그레이드
echo "pip 업그레이드 중..."
pip install --upgrade pip

# 의존성 설치
echo "의존성 설치 중..."
pip install -r requirements.txt

# 자동매매에 필요한 추가 패키지 설치
echo "자동매매 추가 패키지 설치 중..."
pip install joblib pandas numpy scikit-learn

# 필요한 디렉토리 생성
echo "필요한 디렉토리 생성 중..."
mkdir -p logs
mkdir -p cache
mkdir -p data

# 환경 변수 설정
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

echo "=========================================="
echo "설정 완료! 웹 서버를 시작합니다..."
echo "=========================================="
echo "브라우저에서 http://127.0.0.1:7000 으로 접속하세요."
echo "(7000이 사용중이면 7000~7999 중 사용 가능한 포트로 자동 변경됩니다. 콘솔 로그를 확인하세요.)"
echo "자동매매 페이지: http://127.0.0.1:7000/auto-trading"
echo ""
echo "서버를 중지하려면 Ctrl+C를 누르세요."
echo "=========================================="

# 웹 서버 시작
python -m src.web.app

