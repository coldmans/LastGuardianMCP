# 🛡️ LastGuardian (막차지킴이)

**"오늘 집에 갈 수 있을까?"** 에 대한 답을 주는 MCP 서버

심야 시간대 대중교통 막차 정보를 실시간으로 분석하여, 지하철/버스 막차 시간과 추천 출발 시간을 알려줍니다.

## 주요 기능

- **🚇 지하철 포함 막차**: 지하철이 포함된 경로의 마지막 출발 시간
- **🚌 아무거나 막차**: 심야버스 포함, 가능한 모든 대중교통의 마지막 출발 시간
- **⭐ 추천 출발 시간**: 소요시간이 급증하기 전 최적의 출발 시간
- **🎫 실시간 경로 안내**: 어떤 노선을 타야 하는지 상세 정보 제공

## 작동 원리

### 이분 탐색 기반 막차 시간 추정

Google Routes API는 "막차 시간"을 직접 제공하지 않습니다. 대신, **이분 탐색(Binary Search)** 알고리즘을 활용하여 막차 시간을 약 ±5분 정확도로 추정합니다.

```
탐색 범위: 20:30 ~ 02:00 (익일)
탐색 횟수: 6회 (2^6 = 64분할 → 약 5분 정확도)
```

### 막차 끊김 판단 기준

단순히 "경로가 없음"이 아닌, 실질적으로 이용 불가능한 경로를 판별합니다:

| 조건 | 임계값 | 의미 |
|------|--------|------|
| 총 소요시간 | > 210분 | 첫차 대기 중으로 판단 |
| 출발 대기시간 | > 80분 | 너무 오래 기다려야 함 |

### 추천 출발 시간 산출

30분 간격으로 소요시간을 체크하여, 기준 소요시간의 **1.5배를 초과**하기 직전 시간을 추천합니다.

## 기술 스택

- **Python 3.11+**
- **FastMCP** - MCP 서버 프레임워크
- **Google Routes API** - 대중교통 경로 검색
- **Claude Desktop** - MCP 클라이언트

## 설치 방법

### 옵션 A: Railway 클라우드 배포 (추천)

#### 1. Railway 프로젝트 생성
1. [Railway](https://railway.app/)에 가입
2. "New Project" → "Deploy from GitHub repo" 선택
3. 이 저장소 연결

#### 2. 환경 변수 설정
Railway 대시보드에서 **Environment Variables** 추가:
```
GOOGLE_API_KEY=your_google_api_key_here
```

#### 3. 자동 배포 완료!
- Railway가 자동으로 빌드 & 배포
- 공개 URL 생성됨 (예: `https://lastguardian-production-xxxx.up.railway.app`)
- 이 URL을 PlayMCP에 등록하면 끝!

### 옵션 B: 로컬 실행 (Claude Desktop)

#### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

#### 2. 환경 변수 설정

`.env` 파일 생성:

```env
GOOGLE_API_KEY=your_google_api_key_here
```

> Google Cloud Console에서 Routes API를 활성화하고 API 키를 발급받으세요.

#### 3. Claude Desktop 설정

`claude_desktop_config.json`에 추가:

```json
{
  "mcpServers": {
    "LastGuardian": {
      "command": "fastmcp",
      "args": ["run", "/path/to/last-guardian.py"]
    }
  }
}
```

## 사용 예시

Claude에게 다음과 같이 요청하세요:

```
"인천대입구역에서 강남역까지 막차 알려줘"
"홍대입구역에서 수원역 막차 시간"
```

### 응답 예시

```
🛡️ [막차지킴이 LastGuardian]

📍 경로: 인천대입구역 → 강남역
📏 거리: 45.2km

🎫 현재 추천 경로:
🚇 인천 1호선: 인천대입구 → 부평역
🚇 1호선: 부평 → 신도림
🚇 2호선: 신도림 → 강남

⏰ 막차 정보 (±5분):
🚇 지하철 포함: **23:15** (95분 소요, 45분 남음)
🚌 아무거나: **00:30** (140분 소요, 120분 남음)
⭐ 추천 출발: **22:30** (90분 소요, 90분 남음)

⏰ 아직 여유 있음
지하철까지 **45분** 남았지만, 미루다 후회합니다.
```

## API 비용

Google Routes API 요금:
- **월 $200 무료 크레딧** 제공
- 1회 막차 조회 시 약 **8회 API 호출** (현재경로 1회 + 이분탐색 6회 + 경로정보 1회)
- 일반적인 개인 사용에는 무료 범위 내에서 충분

## 프로젝트 구조

```
LastGuardianMCP/
├── last-guardian.py    # MCP 서버 메인 코드
├── .env                # API 키 (gitignore)
└── README.md
```

## 라이선스

MIT License

---

*집에 가는 길, 막차지킴이가 지켜드립니다* 🏠
