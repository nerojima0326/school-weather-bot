"""
카카오톡 오픈빌더(Kakao i OpenBuilder) 스킬 서버 예시 (FastAPI).

사용자가 카카오톡 채널에서 "날씨", "부산 날씨", "제주도 날씨 어때?" 등을 입력하면
오픈빌더가 이 서버의 POST /kakao/briefing 으로 요청을 보내고,
서버는 말 속의 지역 이름을 찾아 그 지역 브리핑을 스킬 응답 JSON으로 돌려줍니다.
(지역 이름이 없으면 .env의 기본 지역)

실행:
    py -m uvicorn kakao_server:app --host 0.0.0.0 --port 8000

※ 오픈빌더 스킬은 5초 안에 응답해야 합니다.
  - 서버가 켜질 때와 매일 새 예보가 나올 때 전국 지역 예보를 미리 받아 둡니다(캐시).
  - 캐시에 없는 지역은 바로 조회하되, 4초 안에 못 받으면 "잠시 후 다시" 안내를 보내고
    조회는 계속 진행해서 다음 질문 때는 바로 답합니다.
※ 스킬 서버는 '사용자가 말을 걸 때' 응답하는 방식입니다. 매일 아침 먼저 보내는 푸시는
  Discord Webhook(main.py)으로 처리하세요.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

import config
from analyzer import Briefing, analyze
from notifier import build_kakao_error_response, build_kakao_skill_response, build_kakao_text_response
from regions import REGIONS, find_region
from weather_fetcher import WeatherAPIError, get_base_datetime, get_hourly_forecast

RESPONSE_TIMEOUT = 4.0  # 카카오 5초 제한보다 여유 있게

# 시·도 이름만 말했을 때 대표 도시 (도청 소재지 또는 가장 가까운 목록 도시)
PROVINCE_ALIASES = {
    "경기": "suwon", "강원": "chuncheon",
    "충북": "cheongju", "충청북도": "cheongju", "충남": "hongseong", "충청남도": "hongseong",
    "전북": "jeonju", "전라북도": "jeonju", "전남": "mokpo", "전라남도": "mokpo",
    "경북": "andong", "경상북도": "andong", "경남": "changwon", "경상남도": "changwon",
    "울릉": "ulleung",  # '울릉 날씨'처럼 '도' 없이 말해도 울릉도로
}
# 답장 아래에 보여줄 지역 바로가기 버튼
QUICK_REGIONS = ["서울", "부산", "대구", "광주", "대전", "강릉", "제주"]


@dataclass(frozen=True)
class Target:
    key: str    # 캐시 키 (지역 slug 또는 "home")
    name: str   # 브리핑에 표시할 이름
    nx: int
    ny: int


HOME = Target("home", config.LOCATION_NAME, config.NX, config.NY)

_executor = ThreadPoolExecutor(max_workers=4)           # 미리 받아 두기(warm-up)용
_urgent_executor = ThreadPoolExecutor(max_workers=2)    # 사용자가 지금 물어본 지역용 (줄 서지 않음)
_lock = threading.Lock()
_cache: Dict[Tuple[tuple, str], Briefing] = {}
_inflight: Dict[Tuple[tuple, str], Future] = {}
_warm_key: Optional[tuple] = None


# ──────────────────────────────────────────────────────────────────
# 발화 → 지역
# ──────────────────────────────────────────────────────────────────
def _target_for_region(slug: str) -> Target:
    region = find_region(slug)
    if region is None:
        return HOME
    # 기본 지역과 같은 격자면 캐시를 함께 쓰도록 HOME으로 처리
    if region.grid == (HOME.nx, HOME.ny):
        return HOME
    nx, ny = region.grid
    return Target(region.slug, region.name, nx, ny)


def match_target(utterance: str) -> Optional[Target]:
    """발화에서 지역 이름을 찾습니다. 긴 이름부터 비교해 '서귀포'가 '제주'보다 먼저 잡힙니다."""
    text = re.sub(r"\s+", "", utterance)
    for region in sorted(REGIONS, key=lambda r: -len(r.name)):
        if region.name in text:
            return _target_for_region(region.slug)
    for alias, slug in PROVINCE_ALIASES.items():
        if alias in text:
            return _target_for_region(slug)
    return None


def mentioned_place(utterance: str) -> str:
    """'포천 날씨'처럼 '날씨' 앞에 지역 같은 말이 있는지 확인합니다. (목록에 없는 지역 안내용)"""
    if "날씨" not in utterance:
        return ""
    prefix = re.sub(r"(오늘|내일|지금|현재|우리|동네|지역|\s)", "", utterance.split("날씨")[0])
    return re.sub(r"(쪽|의|은|는)$", "", prefix)  # '포천의', '포천쪽' → '포천'


def wants_region_list(utterance: str) -> bool:
    text = re.sub(r"\s+", "", utterance)
    return "지역" in text and any(w in text for w in ("목록", "어디", "리스트", "뭐"))


# ──────────────────────────────────────────────────────────────────
# 예보 캐시
# ──────────────────────────────────────────────────────────────────
def _load(target: Target, base_key: tuple) -> Briefing:
    try:
        forecast = get_hourly_forecast(nx=target.nx, ny=target.ny)
        briefing = analyze(forecast, target.name)
        with _lock:
            _cache[(base_key, target.key)] = briefing
        return briefing
    finally:
        with _lock:
            _inflight.pop((base_key, target.key), None)


def _request(target: Target, urgent: bool = False) -> Future:
    """캐시에 있으면 완료된 Future를, 없으면 조회 중인(또는 새로 시작한) Future를 돌려줍니다.
    urgent=True이면 warm-up 대기열에서 아직 시작 안 한 조회를 빼서 바로 실행합니다."""
    base_key = get_base_datetime()
    cache_key = (base_key, target.key)
    with _lock:
        if cache_key in _cache:
            done: Future = Future()
            done.set_result(_cache[cache_key])
            return done
        future = _inflight.get(cache_key)
        if future is not None and urgent and future.cancel():
            future = None  # 대기 중이던 조회를 취소했으니 아래에서 우선 실행
        if future is None:
            pool = _urgent_executor if urgent else _executor
            future = pool.submit(_load, target, base_key)
            _inflight[cache_key] = future
        return future


def _warm_up() -> None:
    """새 발표 자료가 나오면 전국 지역 예보를 미리 받아 둡니다. (이전 날짜 캐시는 정리)"""
    global _warm_key
    base_key = get_base_datetime()
    with _lock:
        if _warm_key == base_key:
            return
        _warm_key = base_key
        for key in [k for k in _cache if k[0] != base_key]:
            del _cache[key]
    targets = {HOME} | {_target_for_region(r.slug) for r in REGIONS}
    for target in targets:
        _request(target)


def get_briefing(target: Target) -> Briefing:
    _warm_up()
    return _request(target, urgent=True).result(timeout=RESPONSE_TIMEOUT)


# ──────────────────────────────────────────────────────────────────
# FastAPI
# ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_: FastAPI):
    _executor.submit(_warm_up)  # 서버가 켜지자마자 백그라운드로 캐시 채우기
    yield
    _executor.shutdown(wait=False, cancel_futures=True)
    _urgent_executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="등하교 날씨 브리핑 카카오 스킬 서버", lifespan=lifespan)


def _quick_replies(current: Target) -> List[str]:
    return [f"{name} 날씨" for name in QUICK_REGIONS if name != current.name]


@app.post("/kakao/briefing")
def kakao_briefing(payload: Optional[dict] = Body(default=None)) -> JSONResponse:
    utterance = ""
    if isinstance(payload, dict):
        utterance = str((payload.get("userRequest") or {}).get("utterance") or "")

    if wants_region_list(utterance):
        names = ", ".join(r.name for r in REGIONS)
        text = f"📍 지금 알려 드릴 수 있는 지역 ({len(REGIONS)}곳)\n{names}\n\n'부산 날씨'처럼 물어봐 주세요!"
        return JSONResponse(build_kakao_text_response(text, _quick_replies(HOME)))

    target = match_target(utterance)
    prefix = ""
    if target is None:
        target = HOME
        place = mentioned_place(utterance)
        if place:
            prefix = (f"🔎 '{place[:10]}'은(는) 아직 지원하지 않는 지역이라 "
                      f"{HOME.name} 날씨를 알려 드릴게요. ('지역 목록'이라고 보내면 전체 지역을 볼 수 있어요)")

    try:
        briefing = get_briefing(target)
    except FutureTimeout:
        return JSONResponse(build_kakao_text_response(
            f"⏳ {target.name} 예보를 불러오는 중이에요. 잠시 후 다시 물어봐 주세요!",
            [f"{target.name} 날씨"]))
    except WeatherAPIError as e:
        return JSONResponse(build_kakao_error_response(str(e), _quick_replies(target)))
    except Exception as e:  # 오픈빌더에는 항상 규격에 맞는 응답을 돌려줘야 함
        print(f"[kakao_server] 예상치 못한 오류: {e}")
        return JSONResponse(build_kakao_error_response("잠시 후 다시 시도해 주세요."))

    return JSONResponse(build_kakao_skill_response(briefing, prefix, _quick_replies(target)))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
