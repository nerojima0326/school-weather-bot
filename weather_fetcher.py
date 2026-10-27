"""
기상청 단기예보 조회서비스(getVilageFcst) 연동 모듈.

- 매일 05시 발표(base_time=0500) 자료를 받아 오늘 08:00~22:00 예보만 추려냅니다.
- API 키가 비어 있거나 TEST_MODE=True이면 실제 API와 동일한 구조의 Mock Data를 사용합니다.

단독 실행 예시:
    python weather_fetcher.py                      # 오늘 08~22시 예보 표 출력
    python weather_fetcher.py --grid 37.5665 126.9780   # 위도/경도 → 격자(nx, ny) 변환
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import requests

import config

KST = timezone(timedelta(hours=9), "KST")

API_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_TIME = "0500"
FALLBACK_BASE_TIME = "2300"  # 05시 자료가 올라오기 전(05:15 이전) 실행 시 전날 23시 자료 사용
TARGET_CATEGORIES = ("TMP", "POP", "PCP", "SKY", "PTY")
START_HOUR = 8   # 등교
END_HOUR = 22    # 하교

# 실제 API가 돌려주는 카테고리 순서 (Mock Data를 실제와 똑같이 만들기 위해 사용)
ALL_CATEGORIES = ("TMP", "UUU", "VVV", "VEC", "WSD", "SKY", "PTY", "POP", "WAV", "PCP", "REH", "SNO")

SKY_TEXT = {1: "맑음", 3: "구름많음", 4: "흐림"}
PTY_TEXT = {0: "없음", 1: "비", 2: "비/눈", 3: "눈", 4: "소나기"}


class WeatherAPIError(Exception):
    """기상청 API 호출 또는 응답 처리 중 발생한 오류."""


@dataclass
class HourlyForecast:
    fcst_time: str  # "0800"
    hour: int       # 8
    tmp: float      # 1시간 기온(℃)
    pop: int        # 강수확률(%)
    pcp: str        # 1시간 강수량 ("강수없음", "1mm 미만", "2.0mm" ...)
    sky: int        # 1 맑음, 3 구름많음, 4 흐림
    pty: int        # 0 없음, 1 비, 2 비/눈, 3 눈, 4 소나기


@dataclass
class ForecastResult:
    target_date: str   # 예보 대상 날짜 (오늘, YYYYMMDD)
    base_date: str     # 발표 날짜
    base_time: str     # 발표 시각
    nx: int
    ny: int
    is_mock: bool
    hourly: List[HourlyForecast] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# 날짜/시간 유틸
# ──────────────────────────────────────────────────────────────────
def now_kst() -> datetime:
    """GitHub Actions 서버(UTC)에서도 항상 한국 시간을 기준으로 동작하도록 KST 현재 시각을 반환."""
    return datetime.now(KST)


def get_base_datetime(now: Optional[datetime] = None) -> Tuple[str, str, str]:
    """(base_date, base_time, target_date)를 반환합니다.

    05시 발표 자료는 보통 05:10 전후에 API에 등록되므로, 그 이전에 실행하면
    오늘 08~22시 예보가 포함된 '전날 23시 발표' 자료를 대신 사용합니다.
    """
    now = now or now_kst()
    target_date = now.strftime("%Y%m%d")
    if (now.hour, now.minute) < (5, 15):
        yesterday = now - timedelta(days=1)
        return yesterday.strftime("%Y%m%d"), FALLBACK_BASE_TIME, target_date
    return target_date, BASE_TIME, target_date


# ──────────────────────────────────────────────────────────────────
# 위경도 → 기상청 격자 좌표 변환 (기상청 공식 LCC DFS 변환식)
# ──────────────────────────────────────────────────────────────────
def latlon_to_grid(lat: float, lon: float) -> Tuple[int, int]:
    RE = 6371.00877   # 지구 반경(km)
    GRID = 5.0        # 격자 간격(km)
    SLAT1 = 30.0      # 투영 위도1
    SLAT2 = 60.0      # 투영 위도2
    OLON = 126.0      # 기준점 경도
    OLAT = 38.0       # 기준점 위도
    XO = 43           # 기준점 X좌표
    YO = 136          # 기준점 Y좌표

    degrad = math.pi / 180.0
    re_ = RE / GRID
    slat1 = SLAT1 * degrad
    slat2 = SLAT2 * degrad
    olon = OLON * degrad
    olat = OLAT * degrad

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re_ * sf / math.pow(ro, sn)

    ra = math.tan(math.pi * 0.25 + lat * degrad * 0.5)
    ra = re_ * sf / math.pow(ra, sn)
    theta = lon * degrad - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    x = math.floor(ra * math.sin(theta) + XO + 0.5)
    y = math.floor(ro - ra * math.cos(theta) + YO + 0.5)
    return int(x), int(y)


# ──────────────────────────────────────────────────────────────────
# 실제 API 호출
# ──────────────────────────────────────────────────────────────────
def _normalize_service_key(key: str) -> str:
    """인코딩 키(%2B, %3D 등 포함)를 넣어도 동작하도록 디코딩 키로 변환합니다.
    requests가 파라미터를 다시 인코딩하므로 디코딩 키를 넘겨야 이중 인코딩이 되지 않습니다."""
    return unquote(key) if "%" in key else key


def _extract_xml_error(text: str) -> str:
    """인증키 오류 등은 dataType=JSON이어도 XML로 응답하므로 오류 메시지를 뽑아냅니다."""
    for tag in ("returnAuthMsg", "errMsg", "resultMsg"):
        match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
        if match:
            return match.group(1).strip()
    return text.strip()[:200]


def fetch_from_api(base_date: str, base_time: str, nx: int, ny: int, retries: int = 3) -> dict:
    """기상청 단기예보 API를 호출해 JSON 응답(dict)을 그대로 반환합니다."""
    params = {
        "serviceKey": _normalize_service_key(config.KMA_SERVICE_KEY),
        "pageNo": 1,
        "numOfRows": 1000,  # 05시 발표 자료는 약 800~900개 → 한 번에 모두 받기
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=15)
            if resp.status_code in (401, 403):
                raise WeatherAPIError(
                    f"인증 실패(HTTP {resp.status_code}). API 키가 올바른지, 활용신청이 승인되었는지 확인하세요."
                )
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                message = _extract_xml_error(resp.text)
                hint = ""
                if "SERVICE_KEY_IS_NOT_REGISTERED" in message:
                    hint = " (발급 직후라면 키가 활성화될 때까지 1~2시간 기다려 보세요.)"
                raise WeatherAPIError(f"API 오류 응답: {message}{hint}")
        except WeatherAPIError:
            raise  # 인증/키 오류는 재시도해도 소용없으므로 즉시 중단
        except requests.RequestException as e:
            last_error = e
            print(f"[weather_fetcher] API 호출 실패 ({attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(2 * attempt)

    raise WeatherAPIError(f"기상청 API에 연결하지 못했습니다: {last_error}")


# ──────────────────────────────────────────────────────────────────
# Mock Data (실제 API 응답과 동일한 구조)
# ──────────────────────────────────────────────────────────────────
_MOCK_SCENARIOS: Dict[str, Dict[str, Dict[int, object]]] = {
    # 오후 16~18시 비 + 일교차 10℃ → 우산 필수 & 겉옷 경고가 모두 뜨는 시나리오
    "rainy": {
        "TMP": {0: 9, 1: 9, 2: 8, 3: 8, 4: 8, 5: 8, 6: 11, 7: 12, 8: 13, 9: 14, 10: 16, 11: 18,
                12: 19, 13: 20, 14: 21, 15: 21, 16: 19, 17: 17, 18: 16, 19: 15, 20: 13, 21: 12,
                22: 11, 23: 10},
        "POP": {14: 30, 15: 50, 16: 70, 17: 70, 18: 60, 19: 40, 20: 30},
        "PTY": {16: 1, 17: 1, 18: 1},
        "PCP": {16: "1mm 미만", 17: "2.0mm", 18: "1.0mm"},
        "SKY": {14: 4, 15: 4, 16: 4, 17: 4, 18: 4, 19: 4, 20: 4},
    },
    # 맑고 일교차가 작은 시나리오 → 우산 X, 겉옷 경고 X
    "clear": {
        "TMP": {0: 17, 1: 17, 2: 16, 3: 16, 4: 16, 5: 16, 6: 18, 7: 18, 8: 19, 9: 20, 10: 22,
                11: 23, 12: 24, 13: 25, 14: 25, 15: 25, 16: 24, 17: 23, 18: 22, 19: 21, 20: 21,
                21: 20, 22: 20, 23: 19},
        "POP": {12: 10, 13: 10, 14: 20, 15: 20, 16: 10},
        "PTY": {},
        "PCP": {},
        "SKY": {12: 3, 13: 3, 14: 3, 15: 3, 16: 3},
    },
}


def _mock_value(scenario: Dict[str, Dict[int, object]], category: str, hour: int) -> str:
    if category == "TMP":
        return str(scenario["TMP"][hour])
    if category == "POP":
        return str(scenario["POP"].get(hour, 10 if 6 <= hour <= 20 else 0))
    if category == "PTY":
        return str(scenario["PTY"].get(hour, 0))
    if category == "PCP":
        return str(scenario["PCP"].get(hour, "강수없음"))
    if category == "SKY":
        return str(scenario["SKY"].get(hour, 1 if hour < 12 else 3))
    if category == "SNO":
        return "적설없음"
    if category == "REH":
        return str(85 if int(scenario["PTY"].get(hour, 0)) else 55)
    if category == "WSD":
        return "2.3"
    if category == "VEC":
        return "270"
    if category == "UUU":
        return "2.1"
    if category == "VVV":
        return "-0.8"
    if category == "WAV":
        return "0"
    return "0"


def _mock_scenario_for(nx: int, ny: int, scenario_name: str) -> Dict[str, Dict[int, object]]:
    """기본 지역은 MOCK_SCENARIO를 그대로 쓰고, 다른 지역은 격자 좌표로 날씨를 조금씩 바꿔
    지역별 비교 화면이 테스트 모드에서도 자연스럽게 보이게 합니다."""
    if (nx, ny) == (config.NX, config.NY):
        return _MOCK_SCENARIOS.get(scenario_name, _MOCK_SCENARIOS["rainy"])

    seed = nx * 31 + ny * 17
    base = _MOCK_SCENARIOS["rainy" if seed % 3 == 0 else "clear"]
    scale = 0.6 + (seed % 9) * 0.1      # 일교차 크기 0.6~1.4배
    offset = (seed % 11) - 5            # 기온 -5 ~ +5℃
    temps = base["TMP"]
    mean = sum(temps.values()) / len(temps)
    varied = {h: round(mean + (t - mean) * scale + offset) for h, t in temps.items()}
    return {**base, "TMP": varied}


def build_mock_response(base_date: str, base_time: str, target_date: str, nx: int, ny: int,
                        scenario_name: str = "rainy") -> dict:
    """실제 getVilageFcst JSON 응답과 똑같은 구조의 가짜 데이터를 만듭니다.
    (오늘 06시~23시 + 내일 00시~23시, 실제처럼 TMN/TMX 항목도 포함)"""
    scenario = _mock_scenario_for(nx, ny, scenario_name)
    today = datetime.strptime(target_date, "%Y%m%d")
    tomorrow = (today + timedelta(days=1)).strftime("%Y%m%d")

    items = []
    slots = [(target_date, h) for h in range(6, 24)] + [(tomorrow, h) for h in range(0, 24)]
    for fcst_date, hour in slots:
        fcst_time = f"{hour:02d}00"
        for category in ALL_CATEGORIES:
            items.append({
                "baseDate": base_date,
                "baseTime": base_time,
                "category": category,
                "fcstDate": fcst_date,
                "fcstTime": fcst_time,
                "fcstValue": _mock_value(scenario, category, hour),
                "nx": nx,
                "ny": ny,
            })
        # 실제 API처럼 06시에 일 최저기온(TMN), 15시에 일 최고기온(TMX) 추가
        if hour == 6:
            items.append({"baseDate": base_date, "baseTime": base_time, "category": "TMN",
                          "fcstDate": fcst_date, "fcstTime": fcst_time,
                          "fcstValue": f"{min(scenario['TMP'].values()):.1f}", "nx": nx, "ny": ny})
        if hour == 15:
            items.append({"baseDate": base_date, "baseTime": base_time, "category": "TMX",
                          "fcstDate": fcst_date, "fcstTime": fcst_time,
                          "fcstValue": f"{max(scenario['TMP'].values()):.1f}", "nx": nx, "ny": ny})

    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL_SERVICE"},
            "body": {
                "dataType": "JSON",
                "items": {"item": items},
                "pageNo": 1,
                "numOfRows": 1000,
                "totalCount": len(items),
            },
        }
    }


# ──────────────────────────────────────────────────────────────────
# 응답 파싱
# ──────────────────────────────────────────────────────────────────
def extract_items(response: dict) -> List[dict]:
    """API 응답에서 결과 코드를 확인하고 item 리스트를 꺼냅니다."""
    try:
        header = response["response"]["header"]
    except (KeyError, TypeError):
        raise WeatherAPIError(f"예상하지 못한 응답 형식입니다: {str(response)[:200]}")

    code = header.get("resultCode")
    if code != "00":
        msg = header.get("resultMsg", "")
        if code == "03":
            msg += " (아직 해당 발표 시각 자료가 등록되지 않았습니다. 05:15 이후 다시 시도하세요.)"
        raise WeatherAPIError(f"기상청 API 오류 [{code}] {msg}")

    try:
        items = response["response"]["body"]["items"]["item"]
    except (KeyError, TypeError):
        raise WeatherAPIError("응답에 예보 데이터(items)가 없습니다.")
    return items


def parse_hourly(items: List[dict], target_date: str,
                 start_hour: int = START_HOUR, end_hour: int = END_HOUR) -> List[HourlyForecast]:
    """target_date의 start_hour~end_hour(포함) 시간대에서 TMP/POP/PCP/SKY/PTY만 모아 시간순으로 정리."""
    table: Dict[str, Dict[str, str]] = {}
    for item in items:
        if item.get("fcstDate") != target_date:
            continue
        category = item.get("category")
        if category not in TARGET_CATEGORIES:
            continue
        fcst_time = str(item.get("fcstTime", ""))
        if len(fcst_time) != 4 or not fcst_time.endswith("00"):
            continue
        hour = int(fcst_time[:2])
        if not start_hour <= hour <= end_hour:
            continue
        table.setdefault(fcst_time, {})[category] = str(item.get("fcstValue"))

    forecasts: List[HourlyForecast] = []
    for fcst_time in sorted(table):
        values = table[fcst_time]
        missing = [c for c in TARGET_CATEGORIES if c not in values]
        if missing:
            print(f"[weather_fetcher] {fcst_time} 예보에 {missing} 항목이 없어 건너뜁니다.")
            continue
        try:
            forecasts.append(HourlyForecast(
                fcst_time=fcst_time,
                hour=int(fcst_time[:2]),
                tmp=float(values["TMP"]),
                pop=int(float(values["POP"])),
                pcp=values["PCP"],
                sky=int(float(values["SKY"])),
                pty=int(float(values["PTY"])),
            ))
        except ValueError as e:
            print(f"[weather_fetcher] {fcst_time} 예보 값을 해석하지 못해 건너뜁니다: {e}")

    if not forecasts:
        raise WeatherAPIError(f"{target_date} {start_hour:02d}~{end_hour:02d}시 예보 데이터가 없습니다.")
    return forecasts


# ──────────────────────────────────────────────────────────────────
# 외부에서 사용하는 메인 함수
# ──────────────────────────────────────────────────────────────────
def use_mock_data() -> bool:
    return config.TEST_MODE or not config.KMA_SERVICE_KEY


def get_hourly_forecast(now: Optional[datetime] = None,
                        nx: Optional[int] = None, ny: Optional[int] = None) -> ForecastResult:
    """오늘 08:00~22:00 시간대별 예보를 가져옵니다. (TEST_MODE/키 없음 → Mock Data)
    nx, ny를 생략하면 .env의 기본 지역(NX, NY)을 사용합니다."""
    base_date, base_time, target_date = get_base_datetime(now)
    nx = config.NX if nx is None else nx
    ny = config.NY if ny is None else ny
    is_mock = use_mock_data()

    if is_mock:
        reason = "TEST_MODE=True" if config.TEST_MODE else "API 키 미설정"
        print(f"[weather_fetcher] {reason} → 가짜 데이터(Mock, 시나리오: {config.MOCK_SCENARIO})를 사용합니다.")
        response = build_mock_response(base_date, base_time, target_date, nx, ny, config.MOCK_SCENARIO)
    else:
        print(f"[weather_fetcher] 기상청 API 호출: base={base_date} {base_time}, 격자=({nx}, {ny})")
        response = fetch_from_api(base_date, base_time, nx, ny)

    items = extract_items(response)
    hourly = parse_hourly(items, target_date)
    return ForecastResult(target_date=target_date, base_date=base_date, base_time=base_time,
                          nx=nx, ny=ny, is_mock=is_mock, hourly=hourly)


def _print_table(result: ForecastResult) -> None:
    label = "Mock" if result.is_mock else "기상청 API"
    print(f"\n[{label}] 대상일 {result.target_date} / 발표 {result.base_date} {result.base_time} "
          f"/ 격자 ({result.nx}, {result.ny})")
    print(f"{'시각':>5} | {'기온':>6} | {'강수확률':>6} | {'강수형태':<5} | {'하늘':<5} | 강수량")
    print("-" * 60)
    for h in result.hourly:
        print(f"{h.fcst_time:>5} | {h.tmp:>5.0f}℃ | {h.pop:>6}% | {PTY_TEXT.get(h.pty, h.pty):<5} | "
              f"{SKY_TEXT.get(h.sky, h.sky):<5} | {h.pcp}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="기상청 단기예보 조회 테스트")
    parser.add_argument("--grid", nargs=2, type=float, metavar=("LAT", "LON"),
                        help="위도/경도를 기상청 격자 좌표(nx, ny)로 변환")
    args = parser.parse_args()

    if args.grid:
        gx, gy = latlon_to_grid(args.grid[0], args.grid[1])
        print(f"위도 {args.grid[0]}, 경도 {args.grid[1]} → NX={gx}, NY={gy}")
        print(".env 파일에 위 값을 NX, NY로 넣어 주세요.")
    else:
        try:
            _print_table(get_hourly_forecast())
        except WeatherAPIError as err:
            print(f"❌ {err}")
            sys.exit(1)
