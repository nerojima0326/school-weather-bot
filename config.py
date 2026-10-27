"""
프로젝트 전역 설정 모듈.

.env 파일(로컬) 또는 환경변수(GitHub Actions Secrets/Variables)에서 값을 읽어옵니다.
값이 비어 있으면 아래 기본값이 사용됩니다.
"""
import os

from dotenv import load_dotenv

# 프로젝트 폴더의 .env 파일을 읽어 환경변수로 등록합니다. (.env가 없으면 그냥 넘어감)
load_dotenv()


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)
    if value == "":
        return default
    return value.lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    value = _env_str(name)
    if value == "":
        return default
    try:
        return int(value)
    except ValueError:
        print(f"[config] {name}='{value}' 는 숫자가 아니라서 기본값 {default}을(를) 사용합니다.")
        return default


# ── 기상청 단기예보 API ────────────────────────────────────────────
# 공공데이터포털에서 발급받은 인증키 (디코딩 키 권장, 인코딩 키를 넣어도 자동 변환됨)
KMA_SERVICE_KEY = _env_str("KMA_SERVICE_KEY")

# True이면 API 키가 있어도 가짜 데이터(Mock Data)로 실행합니다.
# (API 키가 비어 있으면 TEST_MODE와 관계없이 자동으로 Mock Data를 사용합니다.)
TEST_MODE = _env_bool("TEST_MODE", False)

# Mock Data 시나리오: "rainy"(오후 비 + 큰 일교차) / "clear"(맑고 일교차 작음)
MOCK_SCENARIO = _env_str("MOCK_SCENARIO", "rainy").lower()

# 기상청 격자 좌표 (기본값: 서울 중구 60, 127)
# 내 지역 좌표 확인: python weather_fetcher.py --grid <위도> <경도>
NX = _env_int("NX", 60)
NY = _env_int("NY", 127)
LOCATION_NAME = _env_str("LOCATION_NAME", "서울")

# ── 메신저 ────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = _env_str("DISCORD_WEBHOOK_URL")

# ── 로컬 스케줄러 ─────────────────────────────────────────────────
# 로컬 PC의 시계 기준 실행 시각 (PC 시간대가 한국 시간이어야 함)
BRIEFING_TIME = _env_str("BRIEFING_TIME", "07:30")
