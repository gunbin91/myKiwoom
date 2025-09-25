/**
 * 키움 자동매매 대시보드 메인 JavaScript
 */

// 전역 변수
let socket = null;
let isAuthenticated = false;
let refreshInterval = null;
let currentServerInfo = null;

// DOM 로드 완료 시 초기화
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    setActiveNavigation();
});

/**
 * 애플리케이션 초기화
 */
function initializeApp() {
    console.log('키움 자동매매 대시보드 초기화 중...');
    
    // 서버 상태 확인
    checkServerStatus();
    
    // 인증 상태 확인
    checkAuthStatus();
    
    // 웹소켓 연결
    connectWebSocket();
    
    // 이벤트 리스너 등록
    setupEventListeners();
    
    // 자동 새로고침 설정
    setupAutoRefresh();
    
    console.log('애플리케이션 초기화 완료');
}

/**
 * 네비게이션 활성 상태 설정
 */
function setActiveNavigation() {
    const currentPath = window.location.pathname;
    const navItems = document.querySelectorAll('.navbar-nav .nav-link');
    
    // 모든 네비게이션 아이템에서 active 클래스 제거
    navItems.forEach(item => {
        item.classList.remove('active');
    });
    
    // 현재 경로에 맞는 네비게이션 아이템 활성화
    switch (currentPath) {
        case '/':
            document.getElementById('nav-dashboard')?.classList.add('active');
            break;
        case '/portfolio':
            document.getElementById('nav-portfolio')?.classList.add('active');
            break;
        case '/orders':
            document.getElementById('nav-orders')?.classList.add('active');
            break;
        case '/trading-diary':
            document.getElementById('nav-trading')?.classList.add('active');
            break;
        case '/auto-trading':
            document.getElementById('nav-auto-trading')?.classList.add('active');
            break;
    }
}

/**
 * 서버 상태 확인
 */
async function checkServerStatus() {
    try {
        const response = await fetch('/api/server/status');
        const data = await response.json();
        
        if (data.success) {
            currentServerInfo = data.server_info;
            updateServerInfo();
        }
    } catch (error) {
        console.error('서버 상태 확인 실패:', error);
    }
}

/**
 * 서버 정보 업데이트
 */
function updateServerInfo() {
    const serverNameElement = document.getElementById('server-name');
    const serverInfoElement = document.getElementById('server-info');
    
    if (currentServerInfo && serverNameElement) {
        serverNameElement.textContent = currentServerInfo.server_name;
        
        // 서버별 색상 적용
        if (currentServerInfo.server_type === 'mock') {
            serverInfoElement.style.color = '#4CAF50';
        } else {
            serverInfoElement.style.color = '#F44336';
        }
    }
}

/**
 * 인증 상태 확인
 */
async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/status');
        const data = await response.json();
        
        isAuthenticated = data.authenticated;
        updateAuthUI(data.authenticated);
        
        if (data.authenticated) {
            console.log('인증됨 - 데이터 로드 시작');
            // 인증된 경우 대시보드 데이터 로드
            if (typeof refreshDashboard === 'function') {
                refreshDashboard();
            }
        } else {
            console.log('인증 필요');
        }
    } catch (error) {
        console.error('인증 상태 확인 실패:', error);
        showAlert('인증 상태 확인에 실패했습니다.', 'danger');
    }
}

/**
 * 인증 UI 업데이트
 */
function updateAuthUI(authenticated) {
    const authBtn = document.getElementById('auth-btn');
    const connectionStatus = document.getElementById('connection-status');
    
    if (authenticated) {
        authBtn.innerHTML = '<i class="fas fa-sign-out-alt me-1"></i>로그아웃';
        authBtn.onclick = logout;
        connectionStatus.innerHTML = '<i class="fas fa-circle text-success me-1"></i>연결됨';
    } else {
        authBtn.innerHTML = '<i class="fas fa-sign-in-alt me-1"></i>로그인';
        authBtn.onclick = login;
        connectionStatus.innerHTML = '<i class="fas fa-circle text-danger me-1"></i>연결 끊김';
    }
}

/**
 * 로그인
 */
async function login() {
    try {
        showLoading(true);
        console.log('로그인 시도 시작');
        
        // 로그인 진행 모달 표시
        showLoginProgressModal();
        
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            isAuthenticated = true;
            updateAuthUI(true);
            
            // 로그인 성공 메시지
            updateLoginProgress('✅ 로그인 성공! 매수 체결내역 수집이 완료되었습니다.', 'success');
            
            // 2초 후 모달 닫기
            setTimeout(() => {
                hideLoginProgressModal();
                showAlert('✅ 로그인 성공!', 'success');
                
                // 로그인 성공 후 데이터 새로고침
                if (typeof refreshDashboard === 'function') {
                    refreshDashboard();
                }
            }, 2000);
        } else {
            hideLoginProgressModal();
            showAlert(data.message, 'danger');
        }
    } catch (error) {
        console.error('로그인 실패:', error);
        hideLoginProgressModal();
        showAlert('로그인 중 오류가 발생했습니다.', 'danger');
    } finally {
        showLoading(false);
    }
}

/**
 * 로그인 진행 모달 표시
 */
function showLoginProgressModal() {
    // 기존 모달이 있으면 제거
    const existingModal = document.getElementById('loginProgressModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // 모달 HTML 생성
    const modalHTML = `
        <div class="modal fade" id="loginProgressModal" tabindex="-1" aria-labelledby="loginProgressModalLabel" aria-hidden="true" data-bs-backdrop="static" data-bs-keyboard="false">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header bg-primary text-white">
                        <h5 class="modal-title" id="loginProgressModalLabel">
                            <i class="fas fa-sign-in-alt me-2"></i>로그인 진행 중
                        </h5>
                    </div>
                    <div class="modal-body text-center">
                        <div class="mb-3">
                            <div class="spinner-border text-primary" role="status">
                                <span class="visually-hidden">로딩 중...</span>
                            </div>
                        </div>
                        <h6 id="loginProgressMessage">🔐 로그인 중...</h6>
                        <p class="text-muted mb-3">매수 체결내역을 수집하고 있습니다.</p>
                        <div class="progress mb-3" style="height: 8px;">
                            <div class="progress-bar progress-bar-striped progress-bar-animated bg-primary" 
                                 role="progressbar" style="width: 0%" id="loginProgressBar"></div>
                        </div>
                        <small class="text-muted" id="loginProgressDetail">토큰 발급 중...</small>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // 모달을 body에 추가
    document.body.insertAdjacentHTML('beforeend', modalHTML);
    
    // 모달 표시
    const modal = new bootstrap.Modal(document.getElementById('loginProgressModal'));
    modal.show();
    
    // 진행률 애니메이션 시작
    startLoginProgressAnimation();
}

/**
 * 로그인 진행률 애니메이션
 */
function startLoginProgressAnimation() {
    const progressBar = document.getElementById('loginProgressBar');
    const progressDetail = document.getElementById('loginProgressDetail');
    
    let progress = 0;
    const steps = [
        { progress: 15, message: '토큰 발급 중...' },
        { progress: 25, message: '보유종목 조회 중...' },
        { progress: 35, message: '체결내역 수집 시작...' },
        { progress: 50, message: '최근 30일 데이터 수집 중...' },
        { progress: 70, message: '매수 주문 필터링 중...' },
        { progress: 85, message: '데이터 저장 중...' },
        { progress: 95, message: '완료 처리 중...' }
    ];
    
    let currentStep = 0;
    
    const interval = setInterval(() => {
        if (currentStep < steps.length) {
            const step = steps[currentStep];
            progress = step.progress;
            progressBar.style.width = progress + '%';
            progressDetail.textContent = step.message;
            currentStep++;
        } else {
            // 95%에서 멈춤 (실제 완료까지 대기)
            clearInterval(interval);
        }
    }, 3000); // 3초마다 단계 진행 (더 여유있게)
}

/**
 * 로그인 진행 메시지 업데이트
 */
function updateLoginProgress(message, type = 'info') {
    const progressMessage = document.getElementById('loginProgressMessage');
    const progressBar = document.getElementById('loginProgressBar');
    
    if (progressMessage) {
        progressMessage.textContent = message;
        
        // 타입에 따른 색상 변경
        if (type === 'success') {
            progressMessage.className = 'text-success';
            progressBar.className = 'progress-bar bg-success';
            progressBar.style.width = '100%';
        } else if (type === 'danger') {
            progressMessage.className = 'text-danger';
            progressBar.className = 'progress-bar bg-danger';
        }
    }
}

/**
 * 로그인 진행 모달 숨기기
 */
function hideLoginProgressModal() {
    const modal = document.getElementById('loginProgressModal');
    if (modal) {
        const bootstrapModal = bootstrap.Modal.getInstance(modal);
        if (bootstrapModal) {
            bootstrapModal.hide();
        }
        // 모달이 완전히 숨겨진 후 DOM에서 제거
        modal.addEventListener('hidden.bs.modal', function() {
            modal.remove();
        }, { once: true });
    }
}

/**
 * 로그아웃
 */
async function logout() {
    try {
        if (!confirm('정말로 로그아웃하시겠습니까?')) {
            return;
        }
        
        showLoading(true);
        
        const response = await fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            // 로컬 상태 즉시 업데이트
            isAuthenticated = false;
            updateAuthUI(false);
            
            // 대시보드 데이터 초기화
            if (typeof clearDashboard === 'function') {
                clearDashboard();
            }
            
            showAlert(data.message, 'info');
            
            // 로그아웃 후 인증 상태 재확인 (페이지 새로고침 대신)
            setTimeout(async () => {
                try {
                    await checkAuthStatus();
                } catch (error) {
                    console.error('로그아웃 후 인증 상태 확인 실패:', error);
                }
            }, 500);
        } else {
            showAlert(data.message, 'danger');
        }
    } catch (error) {
        console.error('로그아웃 실패:', error);
        showAlert('로그아웃 중 오류가 발생했습니다.', 'danger');
    } finally {
        showLoading(false);
    }
}

/**
 * 웹소켓 연결
 */
function connectWebSocket() {
    try {
        socket = io();
        
        socket.on('connect', function() {
            console.log('웹소켓 연결됨');
            updateConnectionStatus(true);
        });
        
        socket.on('disconnect', function() {
            console.log('웹소켓 연결 끊김');
            updateConnectionStatus(false);
        });
        
        socket.on('status', function(data) {
            console.log('서버 상태:', data);
        });
        
        socket.on('update', function(data) {
            console.log('실시간 업데이트:', data);
            // 실시간 데이터 처리
            handleRealTimeUpdate(data);
        });
        
        socket.on('subscribed', function(data) {
            console.log('구독됨:', data);
            showAlert(`${data.stock_code} 종목 구독됨`, 'info');
        });
        
    } catch (error) {
        console.error('웹소켓 연결 실패:', error);
    }
}

/**
 * 연결 상태 업데이트
 */
function updateConnectionStatus(connected) {
    const connectionStatus = document.getElementById('connection-status');
    
    if (connected) {
        connectionStatus.innerHTML = '<i class="fas fa-circle text-success me-1"></i>연결됨';
    } else {
        connectionStatus.innerHTML = '<i class="fas fa-circle text-danger me-1"></i>연결 끊김';
    }
}

/**
 * 실시간 업데이트 처리
 */
function handleRealTimeUpdate(data) {
    // 실시간 데이터가 있을 때 처리
    if (data.data && Object.keys(data.data).length > 0) {
        // 실시간 데이터로 UI 업데이트
        updateRealTimeData(data.data);
    }
}

/**
 * 실시간 데이터로 UI 업데이트
 */
function updateRealTimeData(data) {
    // 실시간 데이터 업데이트 로직
    // 예: 주가, 호가, 잔고 등
}

/**
 * 이벤트 리스너 설정
 */
function setupEventListeners() {
    // 네비게이션 클릭 이벤트 (기본 링크 동작 허용)
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', function(e) {
            const target = this.getAttribute('href');
            // 외부 링크나 특별한 처리가 필요한 경우만 preventDefault 사용
            if (target && target.startsWith('#')) {
                e.preventDefault();
                navigateToPage(target);
            }
            // 일반적인 페이지 링크는 기본 동작 허용
        });
    });
    
    // 종목코드 입력 시 자동완성
    const stockCodeInput = document.getElementById('stock-code');
    if (stockCodeInput) {
        stockCodeInput.addEventListener('input', function() {
            const value = this.value;
            if (value.length >= 6) {
                // 종목 정보 조회
                searchStockInfo(value);
            }
        });
    }
    
    // 서버 선택 버튼 이벤트
    const serverSelectBtn = document.getElementById('server-select-btn');
    if (serverSelectBtn) {
        serverSelectBtn.addEventListener('click', function() {
            selectServer();
        });
    }
}

/**
 * 서버 선택 (로그아웃 후 서버 선택 페이지로 이동)
 */
function selectServer() {
    if (!confirm('서버를 다시 선택하시겠습니까?\n\n현재 로그인 상태가 해제되고 서버 선택 페이지로 이동합니다.')) {
        return;
    }
    
    console.log('서버 선택 버튼 클릭 - 서버 선택 페이지로 이동');
    // 로딩 표시
    showLoading(true);
    
    // 로그아웃 요청 (백그라운드에서 처리)
    fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    }).catch(error => {
        console.error('로그아웃 요청 실패:', error);
    });
    
    // 즉시 서버 선택 페이지로 이동
    setTimeout(() => {
        window.location.href = '/server-selection';
    }, 500); // 0.5초 후 이동 (로딩 표시를 위해)
}

/**
 * 페이지 네비게이션
 */
function navigateToPage(page) {
    // 페이지별 처리 로직
    console.log('페이지 이동:', page);
}

/**
 * 자동 새로고침 설정
 */
function setupAutoRefresh() {
    // 60초마다 자동 새로고침 (API 요청 제한 고려)
    refreshInterval = setInterval(() => {
        if (isAuthenticated && typeof refreshDashboard === 'function') {
            refreshDashboard();
        }
    }, 60000);
}

/**
 * 대시보드 데이터 초기화
 */
function clearDashboard() {
    console.log('대시보드 데이터 초기화');
    
    // 대시보드 관련 DOM 요소들을 초기화
    const elementsToClear = [
        '#connection-status',
        '#account-info',
        '#portfolio-summary',
        '#recent-orders',
        '#trading-diary'
    ];
    
    elementsToClear.forEach(selector => {
        const element = document.querySelector(selector);
        if (element) {
            element.innerHTML = '<div class="text-muted">데이터를 불러오는 중...</div>';
        }
    });
}

/**
 * 종목 정보 검색
 */
async function searchStockInfo(stockCode) {
    try {
        const response = await fetch(`/api/quote/stock/${stockCode}`);
        const data = await response.json();
        
        if (data.success) {
            // 종목 정보 표시
            displayStockInfo(data.data);
        }
    } catch (error) {
        console.error('종목 정보 검색 실패:', error);
    }
}

/**
 * 종목 정보 표시
 */
function displayStockInfo(stockInfo) {
    // 종목 정보를 UI에 표시하는 로직
    console.log('종목 정보:', stockInfo);
}

/**
 * 알림 표시
 */
function showAlert(message, type = 'info', duration = 5000) {
    const alertContainer = document.getElementById('alert-container');
    
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    
    // 줄바꿈을 <br>로 변환하고 이모지 지원
    const formattedMessage = message
        .replace(/\n/g, '<br>')
        .replace(/✅/g, '<i class="fas fa-check-circle text-success me-1"></i>')
        .replace(/❌/g, '<i class="fas fa-times-circle text-danger me-1"></i>')
        .replace(/⚠️/g, '<i class="fas fa-exclamation-triangle text-warning me-1"></i>')
        .replace(/ℹ️/g, '<i class="fas fa-info-circle text-info me-1"></i>');
    
    alertDiv.innerHTML = `
        <div class="d-flex align-items-start">
            <div class="flex-grow-1">
                ${formattedMessage}
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;
    
    alertContainer.appendChild(alertDiv);
    
    // 자동 제거
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.remove();
        }
    }, duration);
}

/**
 * 로딩 표시
 */
function showLoading(show) {
    const spinner = document.getElementById('loading-spinner');
    if (spinner) {
        if (show) {
            spinner.classList.remove('d-none');
        } else {
            spinner.classList.add('d-none');
        }
    }
}

/**
 * 로딩 숨기기
 */
function hideLoading() {
    showLoading(false);
}

/**
 * 숫자 포맷팅
 */
function formatNumber(num) {
    if (num === null || num === undefined || num === '') {
        return '0';
    }
    
    const number = parseFloat(num);
    if (isNaN(number)) {
        return '0';
    }
    
    return number.toLocaleString('ko-KR');
}

/**
 * 금액 포맷팅
 */
function formatCurrency(amount) {
    return formatNumber(amount) + '원';
}

/**
 * 퍼센트 포맷팅
 */
function formatPercentage(rate) {
    if (rate === null || rate === undefined || rate === '') {
        return '0.00%';
    }
    
    const number = parseFloat(rate);
    if (isNaN(number)) {
        return '0.00%';
    }
    
    return number.toFixed(2) + '%';
}

/**
 * 날짜 포맷팅
 */
function formatDate(dateString) {
    if (!dateString) return '-';
    
    try {
        const date = new Date(dateString);
        return date.toLocaleDateString('ko-KR');
    } catch (error) {
        return dateString;
    }
}

/**
 * 시간 포맷팅
 */
function formatTime(timeString) {
    if (!timeString) return '-';
    
    try {
        const time = new Date(timeString);
        return time.toLocaleTimeString('ko-KR');
    } catch (error) {
        return timeString;
    }
}

/**
 * API 요청 공통 함수
 */
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // 인증 실패 시 자동 로그아웃 처리
        if (data.success === false && data.authenticated === false) {
            console.log('인증 실패 감지, 자동 로그아웃 처리');
            isAuthenticated = false;
            updateAuthUI(false);
            showAlert('세션이 만료되었습니다. 다시 로그인해주세요.', 'warning');
        }
        
        return data;
    } catch (error) {
        console.error('API 요청 실패:', error);
        throw error;
    }
}

/**
 * 에러 처리
 */
function handleError(error, context = '') {
    console.error(`${context} 오류:`, error);
    
    let message = '알 수 없는 오류가 발생했습니다.';
    
    if (error.message) {
        message = error.message;
    } else if (typeof error === 'string') {
        message = error;
    }
    
    showAlert(message, 'danger');
}

/**
 * 페이지 언로드 시 정리
 */
window.addEventListener('beforeunload', function() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    
    if (socket) {
        socket.disconnect();
    }
});

// 전역 함수로 내보내기
window.showAlert = showAlert;
window.showLoading = showLoading;
window.formatNumber = formatNumber;
window.formatCurrency = formatCurrency;
window.formatPercentage = formatPercentage;
window.formatDate = formatDate;
window.formatTime = formatTime;
window.apiRequest = apiRequest;
window.handleError = handleError;
