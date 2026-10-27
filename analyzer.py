"""
날씨 분석 및 행동 지침(Action Item) 판별 모듈.

08:00~22:00 시간대 예보를 바탕으로
  1) 우산 지참 여부
  2) 낮 최고 기온 기준 추천 옷차림
  3) 일교차(밤 하교 시간 기온 급락) 겉옷 경고
를 판정해 Briefing 객체로 돌려줍니다.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from weather_fetcher import PTY_TEXT, SKY_TEXT, ForecastResult, HourlyForecast

# ── 판정 기준값 ────────────────────────────────────────────────────
UMBRELLA_POP_THRESHOLD = 60      # 강수확률 60% 이상이면 우산
TEMP_RANGE_THRESHOLD = 8         # (최고 - 최저) 8℃ 이상이면 일교차 경고
COMMUTE_DROP_THRESHOLD = 6       # (08시 - 22시) 6℃ 이상 떨어지면 일교차 경고
MORNING_HOUR = 8                 # 등교
NIGHT_HOUR = 22                  # 하교

# 낮 최고 기온 기준 옷차림 (기준 온도 이상이면 해당 옷차림)
OUTFIT_TABLE = [
    (28, "민소매, 반팔, 반바지"),
    (23, "반팔, 얇은 셔츠, 면바지"),
    (20, "긴팔티, 가디건, 후드티, 면바지"),
    (17, "얇은 니트, 맨투맨, 가디건, 청바지"),
    (12, "자켓, 가디건, 야상, 기모 후드티"),
    (9, "트렌치코트, 야상, 점퍼, 기모 바지"),
    (5, "코트, 가죽자켓, 히트텍, 니트"),
    (float("-inf"), "패딩, 두꺼운 코트, 목도리, 기모 제품"),
]

TEMP_GAP_WARNING = (
    "⚠️ 밤 하교 시간(22시)에 기온이 급락합니다! "
    "입고 벗기 편한 겉옷(바람막이/가디건/집업)을 꼭 챙기세요."
)

SKY_EMOJI = {1: "☀️", 3: "⛅", 4: "☁️"}
WEEKDAYS = "월화수목금토일"


@dataclass
class RainPeriod:
    start_hour: int
    end_hour: int
    max_pop: int
    kinds: List[str]  # ["비"], ["소나기"], [] (강수확률만 높은 경우) ...

    @property
    def label(self) -> str:
        return format_hour_range(self.start_hour, self.end_hour)

    @property
    def kind_text(self) -> str:
        return "·".join(self.kinds) if self.kinds else "비"


@dataclass
class Briefing:
    target_date: str
    location: str
    base_date: str
    base_time: str
    is_mock: bool

    # 우산
    need_umbrella: bool
    umbrella_message: str
    max_pop: int
    rain_periods: List[RainPeriod] = field(default_factory=list)

    # 기온 / 옷차림
    min_temp: float = 0.0
    max_temp: float = 0.0
    morning_temp: float = 0.0   # 08시 기온
    night_temp: float = 0.0     # 22시 기온
    outfit: str = ""
    outfit_message: str = ""

    # 일교차
    big_temp_gap: bool = False
    temp_gap_message: str = ""

    # 하늘
    sky_text: str = ""
    sky_emoji: str = ""

    @property
    def date_label(self) -> str:
        d = datetime.strptime(self.target_date, "%Y%m%d")
        return f"{d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})"

    @property
    def base_label(self) -> str:
        d = datetime.strptime(self.base_date, "%Y%m%d")
        return f"{d.month}월 {d.day}일 {int(self.base_time[:2])}시 발표"

    @property
    def title(self) -> str:
        prefix = "[테스트] " if self.is_mock else ""
        return f"{prefix}{self.sky_emoji} {self.date_label} {self.location} 등하교 날씨 브리핑"

    def summary_lines(self) -> List[str]:
        """메신저 카드에 들어갈 3줄 핵심 요약."""
        return [self.umbrella_message, self.outfit_message, self.temp_gap_message]

    def to_text(self) -> str:
        """카카오톡/콘솔용 일반 텍스트 메시지."""
        lines = [
            self.title,
            "━━━━━━━━━━━━━━",
            *self.summary_lines(),
            "━━━━━━━━━━━━━━",
            f"🏫 등교(08시) {fmt_temp(self.morning_temp)} → 🌙 하교(22시) {fmt_temp(self.night_temp)}",
            f"🌡️ 최저 {fmt_temp(self.min_temp)} / 최고 {fmt_temp(self.max_temp)}",
            f"{self.sky_emoji} 하늘 {self.sky_text} · 최대 강수확률 {self.max_pop}%",
            f"📡 기상청 단기예보 {self.base_label} 기준",
        ]
        if self.is_mock:
            lines.append("⚠️ 테스트 모드: 실제 날씨가 아닌 가짜 데이터입니다.")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# 포맷 유틸
# ──────────────────────────────────────────────────────────────────
def fmt_temp(value: float) -> str:
    return f"{value:g}℃"


def format_hour(hour: int) -> str:
    """8 → '오전 8시', 16 → '오후 16시' (요청하신 표기 방식)"""
    return f"{'오전' if hour < 12 else '오후'} {hour}시"


def format_hour_range(start: int, end: int) -> str:
    if start == end:
        return format_hour(start)
    same_half = (start < 12) == (end < 12)
    end_text = f"{end}시" if same_half else format_hour(end)
    return f"{format_hour(start)}~{end_text}"


# ──────────────────────────────────────────────────────────────────
# 1) 우산 판별
# ──────────────────────────────────────────────────────────────────
def is_rain_hour(h: HourlyForecast) -> bool:
    return h.pop >= UMBRELLA_POP_THRESHOLD or h.pty != 0


def find_rain_periods(hourly: List[HourlyForecast]) -> List[RainPeriod]:
    """비/눈 예보 시간대를 연속 구간으로 묶습니다. (예: 16, 17, 18시 → 16시~18시 한 구간)"""
    periods: List[RainPeriod] = []
    current: Optional[List[HourlyForecast]] = None

    for h in hourly:
        if is_rain_hour(h):
            if current and h.hour == current[-1].hour + 1:
                current.append(h)
            else:
                if current:
                    periods.append(_to_period(current))
                current = [h]
        elif current:
            periods.append(_to_period(current))
            current = None
    if current:
        periods.append(_to_period(current))
    return periods


def _to_period(hours: List[HourlyForecast]) -> RainPeriod:
    kinds: List[str] = []
    for h in hours:
        name = PTY_TEXT.get(h.pty)
        if h.pty != 0 and name and name not in kinds:
            kinds.append(name)
    return RainPeriod(
        start_hour=hours[0].hour,
        end_hour=hours[-1].hour,
        max_pop=max(h.pop for h in hours),
        kinds=kinds,
    )


def build_umbrella_message(periods: List[RainPeriod], max_pop: int) -> str:
    if not periods:
        return f"🌂 우산은 필요 없어요! (최대 강수확률 {max_pop}%)"
    parts = [f"{p.label} {p.kind_text} 예보(최대 {p.max_pop}%)" for p in periods]
    return f"☔ {', '.join(parts)}, 우산 꼭 챙기세요! ☔"


# ──────────────────────────────────────────────────────────────────
# 2) 옷차림
# ──────────────────────────────────────────────────────────────────
def recommend_outfit(max_temp: float) -> str:
    for threshold, outfit in OUTFIT_TABLE:
        if max_temp >= threshold:
            return outfit
    return OUTFIT_TABLE[-1][1]


# ──────────────────────────────────────────────────────────────────
# 3) 일교차
# ──────────────────────────────────────────────────────────────────
def _temp_at(hourly: List[HourlyForecast], hour: int, fallback: HourlyForecast) -> float:
    for h in hourly:
        if h.hour == hour:
            return h.tmp
    return fallback.tmp


def check_temp_gap(min_temp: float, max_temp: float, morning: float, night: float) -> bool:
    return (max_temp - min_temp >= TEMP_RANGE_THRESHOLD) or (morning - night >= COMMUTE_DROP_THRESHOLD)


# ──────────────────────────────────────────────────────────────────
# 메인 분석 함수
# ──────────────────────────────────────────────────────────────────
def analyze(forecast: ForecastResult, location: str = "서울") -> Briefing:
    hourly = forecast.hourly
    if not hourly:
        raise ValueError("분석할 예보 데이터가 없습니다.")

    # 우산
    periods = find_rain_periods(hourly)
    max_pop = max(h.pop for h in hourly)
    need_umbrella = bool(periods)

    # 기온
    temps = [h.tmp for h in hourly]
    min_temp, max_temp = min(temps), max(temps)
    morning_temp = _temp_at(hourly, MORNING_HOUR, hourly[0])
    night_temp = _temp_at(hourly, NIGHT_HOUR, hourly[-1])
    outfit = recommend_outfit(max_temp)

    # 일교차
    big_gap = check_temp_gap(min_temp, max_temp, morning_temp, night_temp)
    if big_gap:
        gap_message = TEMP_GAP_WARNING
    else:
        gap_message = (f"🌡️ 일교차 {fmt_temp(max_temp - min_temp)}로 크지 않아요. "
                       f"(등교 {fmt_temp(morning_temp)} → 하교 {fmt_temp(night_temp)})")

    # 하늘 상태: 08~22시 중 가장 많이 나온 값
    sky_code = Counter(h.sky for h in hourly).most_common(1)[0][0]

    return Briefing(
        target_date=forecast.target_date,
        location=location,
        base_date=forecast.base_date,
        base_time=forecast.base_time,
        is_mock=forecast.is_mock,
        need_umbrella=need_umbrella,
        umbrella_message=build_umbrella_message(periods, max_pop),
        max_pop=max_pop,
        rain_periods=periods,
        min_temp=min_temp,
        max_temp=max_temp,
        morning_temp=morning_temp,
        night_temp=night_temp,
        outfit=outfit,
        outfit_message=f"👕 오늘 옷차림(최고 {fmt_temp(max_temp)}): {outfit}",
        big_temp_gap=big_gap,
        temp_gap_message=gap_message,
        sky_text=SKY_TEXT.get(sky_code, "알 수 없음"),
        sky_emoji=SKY_EMOJI.get(sky_code, "🌤️"),
    )


if __name__ == "__main__":
    import sys

    import config
    from weather_fetcher import get_hourly_forecast

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(analyze(get_hourly_forecast(), config.LOCATION_NAME).to_text())
