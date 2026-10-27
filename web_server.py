"""
웹사이트 서버 (FastAPI) - 접속할 때마다 최신 브리핑 페이지를 보여줍니다.

실행:
    py -m uvicorn web_server:app --host 0.0.0.0 --port 8000
접속:
    http://localhost:8000            기본 지역(.env)
    http://localhost:8000/busan.html  다른 지역 (regions.py의 slug)
    같은 와이파이의 휴대폰에서는 http://<PC IP>:8000

※ 첫 접속 때 전국 지역 예보를 한꺼번에 받아오느라 몇 초 걸리고, 이후에는 캐시를 사용합니다.
※ 매일 아침 한 번만 갱신되면 충분하다면 서버 없이 GitHub Pages(publish_site.yml)를 쓰세요.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Tuple

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from weather_fetcher import WeatherAPIError, get_base_datetime
from web_page import HOME_URL, Report, collect_reports, region_summaries, render_error_html, render_html

app = FastAPI(title="등하교 날씨 브리핑 웹사이트")

_cache_lock = threading.Lock()
_cache: dict = {"key": None, "data": None}


def get_today_data() -> Tuple[Report, Dict[str, Report], List[dict]]:
    """(기본 지역, slug별 지역 리포트, 지역 요약 목록)
    발표일·발표시각이 같으면 기상청 API를 다시 부르지 않고 캐시를 사용합니다."""
    key = get_base_datetime()
    with _cache_lock:
        if _cache["key"] == key and _cache["data"] is not None:
            return _cache["data"]
        home, reports = collect_reports(max_workers=8)
        data = (home, {r.slug: r for r in reports}, region_summaries(reports))
        _cache["key"] = key
        _cache["data"] = data
        return data


@app.get("/", response_class=HTMLResponse)
@app.get("/" + HOME_URL, response_class=HTMLResponse)
def index() -> HTMLResponse:
    try:
        home, _, summaries = get_today_data()
    except WeatherAPIError as e:
        return HTMLResponse(render_error_html(str(e)), status_code=503)
    return HTMLResponse(render_html(home, summaries, home.name))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/{slug}.html", response_class=HTMLResponse)
def region_page(slug: str) -> HTMLResponse:
    try:
        home, reports, summaries = get_today_data()
    except WeatherAPIError as e:
        return HTMLResponse(render_error_html(str(e)), status_code=503)
    report = reports.get(slug)
    if report is None:
        return HTMLResponse(render_error_html(f"'{slug}' 지역을 찾을 수 없어요."), status_code=404)
    return HTMLResponse(render_html(report, summaries, home.name))
