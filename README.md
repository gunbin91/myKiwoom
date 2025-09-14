# 키움 자동매매 웹 대시보드

키움증권 REST API를 활용한 자동매매 시스템의 웹 기반 대시보드입니다. 실시간 계좌 현황, 보유 종목, 주문 내역 등을 한눈에 확인하고 빠른 주문을 수행할 수 있습니다.

## 🚀 주요 기능

### 📊 대시보드
- **계좌 현황**: 예수금, 총 자산, 평가손익, 수익률 실시간 표시
- **보유 종목**: 현재 보유 종목의 상세 정보 및 손익 현황
- **빠른 주문**: 종목코드 입력으로 즉시 매수/매도 주문 가능 (현금 주문만)
- **미체결 주문**: 대기 중인 주문 현황 및 취소 기능
- **매매일지**: 당일 매매 내역 및 손익 현황

### ⚠️ 주문 제한사항
- **현금 주문만 지원**: 신용주문(융자/대주)은 사용하지 않음
- **이유**: 복잡성, 위험성, 비용, 규제 등의 이유로 일반적인 자동매매에서는 현금 주문만 사용

### 🔐 인증 시스템
- **OAuth 2.0**: 키움증권 API 인증 자동화
- **토큰 관리**: 자동 토큰 갱신 및 캐싱
- **보안**: 세션 기반 사용자 인증

### 📈 실시간 데이터
- **웹소켓**: 실시간 시세 및 계좌 정보 업데이트
- **자동 새로고침**: 30초마다 데이터 자동 갱신
- **연결 상태**: 서버 연결 상태 실시간 모니터링

## 🛠️ 기술 스택

### Backend
- **Python 3.8+**: 메인 프로그래밍 언어
- **Flask**: 웹 프레임워크
- **Flask-SocketIO**: 실시간 통신
- **Requests**: HTTP API 클라이언트

### Frontend
- **Bootstrap 5**: UI 프레임워크
- **Chart.js**: 차트 라이브러리
- **Font Awesome**: 아이콘
- **Socket.IO**: 실시간 통신 클라이언트

### API
- **키움증권 REST API**: 모의투자 환경
- **OAuth 2.0**: 인증 시스템

## 📁 프로젝트 구조

```
kiwoomAutoStock/
├── src/                    # 소스 코드
│   ├── api/               # 키움 API 모듈
│   │   ├── auth.py        # OAuth 인증
│   │   ├── account.py     # 계좌 관련 API
│   │   ├── quote.py       # 시세 관련 API
│   │   └── order.py       # 주문 관련 API
│   ├── config/            # 설정 파일
│   │   └── settings.py    # 애플리케이션 설정
│   ├── utils/             # 유틸리티
│   │   └── logger.py      # 로깅 시스템
│   └── web/               # 웹 애플리케이션
│       └── app.py         # Flask 메인 앱
├── templates/             # HTML 템플릿
│   ├── base.html          # 기본 템플릿
│   └── dashboard.html     # 대시보드 페이지
├── static/                # 정적 파일
│   ├── css/               # 스타일시트
│   │   └── style.css      # 메인 스타일
│   └── js/                # JavaScript
│       └── app.js         # 메인 스크립트
├── run/                   # 실행 스크립트
│   ├── start_app.command  # macOS 실행 스크립트
│   ├── start_app.bat      # Windows 실행 스크립트
│   ├── setup_venv.command # macOS 환경 설정
│   └── setup_venv.bat     # Windows 환경 설정
├── logs/                  # 로그 파일
├── cache/                 # 캐시 파일
├── data/                  # 데이터 파일
├── venv/                  # 가상환경
├── requirements.txt       # Python 의존성
└── README.md             # 프로젝트 문서
```

## 🚀 빠른 시작

### 1. 환경 설정

#### macOS
```bash
# 가상환경 설정
./run/setup_venv.command

# 웹 대시보드 시작
./run/start_app.command
```

#### Windows
```cmd
REM 가상환경 설정
run\setup_venv.bat

REM 웹 대시보드 시작
run\start_app.bat
```

### 2. 수동 설정

```bash
# 1. 가상환경 생성
python3 -m venv venv

# 2. 가상환경 활성화
# macOS/Linux
source venv/bin/activate
# Windows
venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 웹 서버 시작
python -m src.web.app
```

### 3. 접속

웹 브라우저에서 `http://127.0.0.1:5000`으로 접속하세요.

## 🔧 설정

### API 설정
`src/config/settings.py`에서 키움증권 API 설정을 확인하세요:

```python
# 키움증권 API 설정 (모의투자)
KIWOOM_APP_KEY = "your_app_key"
KIWOOM_SECRET_KEY = "your_secret_key"
KIWOOM_DOMAIN = "https://mockapi.kiwoom.com"
```

### 웹 서버 설정
```python
WEB_HOST = "127.0.0.1"
WEB_PORT = 5000
WEB_DEBUG = True
```

## 📖 사용법

### 1. 로그인
- 웹 대시보드 접속 후 "로그인" 버튼 클릭
- 키움증권 API 인증 자동 처리

### 2. 대시보드 확인
- **계좌 현황**: 예수금, 총 자산, 평가손익, 수익률
- **보유 종목**: 현재 보유 종목의 상세 정보
- **미체결 주문**: 대기 중인 주문 현황
- **매매일지**: 당일 매매 내역

### 3. 빠른 주문
1. 종목코드 입력 (예: 005930)
2. 매수/매도 선택
3. 수량과 가격 입력
4. "주문하기" 버튼 클릭

### 4. 주문 관리
- **미체결 주문**: 취소 버튼으로 주문 취소 가능
- **체결 내역**: 최근 7일간의 체결 내역 확인

## 🔒 보안

- **OAuth 2.0**: 안전한 API 인증
- **토큰 관리**: 자동 갱신 및 캐싱
- **세션 관리**: 사용자 세션 타임아웃
- **HTTPS**: 프로덕션 환경에서 HTTPS 사용 권장

## 📝 로깅

애플리케이션은 다음 위치에 로그를 저장합니다:
- **콘솔**: 실시간 로그 출력
- **파일**: `logs/kiwoom_auto_trading.log`
- **로그 레벨**: INFO, ERROR, DEBUG

## 🐛 문제 해결

### 일반적인 문제

1. **인증 실패**
   - 키움증권 API 키 확인
   - 네트워크 연결 상태 확인

2. **데이터 조회 실패**
   - API 토큰 만료 확인
   - 키움증권 서버 상태 확인

3. **웹소켓 연결 실패**
   - 방화벽 설정 확인
   - 포트 5000 사용 가능 여부 확인

### 로그 확인
```bash
# 실시간 로그 확인
tail -f logs/kiwoom_auto_trading.log
```

## 🔄 업데이트

### 의존성 업데이트
```bash
pip install --upgrade -r requirements.txt
```

### 코드 업데이트
```bash
git pull origin main
```

## 📞 지원

문제가 발생하거나 기능 요청이 있으시면 이슈를 등록해주세요.

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

## ⚠️ 주의사항

- **모의투자**: 현재 모의투자 환경에서만 동작합니다
- **투자 위험**: 실제 투자 시 손실 가능성이 있습니다
- **API 제한**: 키움증권 API 사용 제한을 준수하세요
- **개인정보**: API 키는 안전하게 보관하세요

---

**키움 자동매매 웹 대시보드**로 더욱 편리하고 효율적인 투자를 시작하세요! 🚀
