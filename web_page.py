"""
웹사이트용 브리핑 페이지(HTML) 생성 모듈 — 학생의 하루(등교 → 수업 → 귀가)에 맞춘 화면.

일반 날씨 앱처럼 '시간별 날씨'를 나열하지 않고,
  · 나는 몇 시에 집에 가는지(정규 하교 / 방과후 / 학원 / 야자)를 고르면
  · 등굣길과 귀갓길의 기온·체감·입을 옷,
  · 교복 코디, 가방에 챙길 것, 오늘 내 하루 일정별 날씨
를 그 시간대(08시 ~ 귀가)에 맞춰 다시 계산해 보여 줍니다. (판정 기준은 analyzer.py와 같음)

    py web_page.py        # site/index.html + 지역별 페이지 생성 → 더블클릭해서 브라우저로 열기

GitHub Actions(publish_site.yml)가 매일 아침 이 파일들을 만들어 GitHub Pages에 올립니다.
"""
from __future__ import annotations

import html
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import List, Optional, Tuple

import config
from analyzer import (COMMUTE_DROP_THRESHOLD, SKY_EMOJI, TEMP_RANGE_THRESHOLD, UMBRELLA_POP_THRESHOLD,
                      Briefing, analyze, is_rain_hour)
from regions import REGIONS, Region, find_region_by_grid, region_group
from weather_fetcher import (ForecastResult, HourlyForecast, WeatherAPIError,
                             get_hourly_forecast, now_kst)

OUTPUT_DIR = Path(__file__).resolve().parent / "site"
HOME_URL = "index.html"

PTY_EMOJI = {1: "🌧️", 2: "🌨️", 3: "❄️", 4: "🌦️"}


# ──────────────────────────────────────────────────────────────────
# 스타일
# ──────────────────────────────────────────────────────────────────
# 다크 모드 색상 (자동 모드의 미디어 쿼리와 '다크' 선택 시 두 곳에서 같이 씀)
DARK_TOKENS = """
  color-scheme: dark;
  --bg: #12151c;
  --card: #1c2230;
  --ink: #edf0f6;
  --ink-2: #aab2c3;
  --ink-3: #7c869b;
  --line: #2a3142;
  --shadow: 0 1px 2px rgba(0, 0, 0, .3), 0 8px 24px rgba(0, 0, 0, .25);
  --chart-line: #ff9a52;
  --rain-band: #1f2d48;
  --rain-ink: #8db4ff;
  --done: #5fd38d;
  --done-bg: #173225;
  --warn: #ffa06b;
  --warn-bg: #3a2416;
  --chip: #252c3b;
  --night-bg: #232b45;

  --hero-sunny-a: #5c3c1b; --hero-sunny-b: #6a3328;
  --hero-partly-a: #22334f; --hero-partly-b: #4a3a24;
  --hero-cloudy-a: #2a303e; --hero-cloudy-b: #363e51;
  --hero-rain-a: #1f2f58; --hero-rain-b: #352a60;
  --hero-ink: #f3f5fb;
  --hero-pill: rgba(0, 0, 0, .25);
  --hero-sel-ink: #1c2230;
"""

PAGE_CSS = """
:root {
  color-scheme: light;
  --bg: #f6f4f1;
  --card: #ffffff;
  --ink: #232836;
  --ink-2: #5b6478;
  --ink-3: #8a92a5;
  --line: #ece8e3;
  --shadow: 0 1px 2px rgba(35, 40, 54, .04), 0 8px 24px rgba(35, 40, 54, .06);
  --chart-line: #e8590c;
  --rain-band: #eaf2ff;
  --rain-ink: #2f6fde;
  --done: #16a34a;
  --done-bg: #e8f8ee;
  --warn: #c2410c;
  --warn-bg: #fff1e6;
  --chip: #f3f1ee;
  --night-bg: #eceefb;

  --hero-sunny-a: #ffe1b0; --hero-sunny-b: #ffc4a6;
  --hero-partly-a: #dcebff; --hero-partly-b: #ffe6c9;
  --hero-cloudy-a: #e6e9f1; --hero-cloudy-b: #cfd6e6;
  --hero-rain-a: #d5e4ff; --hero-rain-b: #ddd4ff;
  --hero-ink: #232836;
  --hero-pill: rgba(255, 255, 255, .6);
  --hero-sel-ink: #ffffff;
}
/* 다크 모드: '자동'이면 기기 설정을 따르고, 사용자가 고르면 그 테마로 고정 */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { %DARK_TOKENS% }
}
:root[data-theme="dark"] { %DARK_TOKENS% }

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
  line-height: 1.5;
  word-break: keep-all;
  overflow-wrap: anywhere;
  -webkit-font-smoothing: antialiased;
  transition: background-color .25s, color .25s;
}
main, .layout, .content {
  display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px;
}
main { max-width: 640px; margin: 0 auto; padding: 20px 16px 48px; }

/* ── 상단 바: 앱 이름(또는 돌아가기) + 테마 선택 ── */
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 40px; }
.brand { display: inline-flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 800; letter-spacing: -0.02em; }
.brand .h-icon { width: 30px; height: 30px; font-size: 16px; --ha: #ffe3b8; --hb: #ffc27d; }
.home-link { font-size: 14px; font-weight: 700; color: var(--ink-2); text-decoration: none; padding: 2px 4px; }
.home-link:hover { color: var(--ink); }
.theme-switch {
  flex: none; display: inline-flex; gap: 2px; padding: 3px; border-radius: 999px;
  background: var(--card); box-shadow: var(--shadow);
}
.theme-switch button {
  font: inherit; font-size: 13px; font-weight: 700; border: 0; cursor: pointer;
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; color: var(--ink-3); padding: 6px 11px; border-radius: 999px;
  transition: background .2s, color .2s;
}
.theme-switch button:hover { color: var(--ink); }
.theme-switch button[aria-pressed="true"] { background: var(--ink); color: var(--card); }
.theme-switch button:focus-visible { outline: 2px solid var(--rain-ink); outline-offset: 1px; }

/* ── 히어로 ── */
.hero {
  position: relative; overflow: hidden;
  border-radius: 28px; padding: 22px 22px 20px;
  color: var(--hero-ink);
  background: linear-gradient(135deg, var(--a), var(--b));
  transition: background .3s;
}
.hero.sunny  { --a: var(--hero-sunny-a);  --b: var(--hero-sunny-b); }
.hero.partly { --a: var(--hero-partly-a); --b: var(--hero-partly-b); }
.hero.cloudy { --a: var(--hero-cloudy-a); --b: var(--hero-cloudy-b); }
.hero.rain   { --a: var(--hero-rain-a);   --b: var(--hero-rain-b); }
.hero-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
.greeting { margin: 0; font-size: 15px; font-weight: 600; opacity: .85; }
.loc-chip {
  flex: none; display: inline-flex; align-items: center; gap: 4px;
  background: var(--hero-pill); color: inherit; text-decoration: none;
  border-radius: 999px; padding: 6px 12px; font-size: 14px; font-weight: 700;
}
.loc-chip:hover { filter: brightness(1.04); }
.hero-main { display: flex; align-items: center; gap: 12px; }
.hero-text { flex: 1; min-width: 0; }
.hero-date { margin: 0; font-size: 14px; opacity: .75; }
.hero h1 { margin: 2px 0 4px; font-size: 26px; line-height: 1.3; letter-spacing: -0.03em; }
.hero-sub { margin: 0; font-size: 15px; opacity: .85; font-variant-numeric: tabular-nums; }
.hero-emoji { font-size: 72px; line-height: 1; flex: none; animation: float 4s ease-in-out infinite; }

/* 귀가 시간 선택 */
.schedule { margin-top: 18px; }
.schedule-label { display: block; font-size: 13px; font-weight: 700; opacity: .8; margin-bottom: 8px; }
.schedule-options { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.schedule-options button {
  font: inherit; border: 0; cursor: pointer; border-radius: 16px; padding: 8px 4px 7px;
  background: var(--hero-pill); color: inherit;
  display: flex; flex-direction: column; align-items: center;
  font-size: 17px; font-weight: 800; line-height: 1.25; font-variant-numeric: tabular-nums;
  transition: transform .15s, background .2s, color .2s;
  -webkit-tap-highlight-color: transparent;
}
.schedule-options button small { font-size: 11px; font-weight: 600; opacity: .75; }
.schedule-options button[aria-pressed="true"] { background: var(--hero-ink); color: var(--hero-sel-ink); }
.schedule-options button:active { transform: scale(.95); }
.schedule-options button:focus-visible { outline: 2px solid var(--hero-ink); outline-offset: 2px; }

.notice { border-radius: 16px; padding: 12px 16px; font-size: 14px; font-weight: 600; background: var(--warn-bg); color: var(--warn); margin: 0; }

/* ── 카드 공통 ── */
.card { background: var(--card); border-radius: 24px; padding: 20px; box-shadow: var(--shadow); }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 14px; }
.card h2 { margin: 0; font-size: 18px; letter-spacing: -0.02em; display: flex; align-items: center; gap: 10px; }
.card .meta { font-size: 13px; color: var(--ink-3); white-space: nowrap; }
/* 작은 앱 아이콘 모양 */
.h-icon {
  flex: none; width: 34px; height: 34px; border-radius: 28%;
  display: grid; place-items: center; font-size: 18px;
  background: linear-gradient(160deg, var(--ha), var(--hb));
  box-shadow: 0 2px 6px rgba(20, 24, 36, .12), inset 0 1px 0 rgba(255, 255, 255, .5);
}
.h-icon.walk  { --ha: #ffe3b8; --hb: #ffc27d; }
.h-icon.bag   { --ha: #ffd9cc; --hb: #ffb3a1; }
.h-icon.shirt { --ha: #cdf3dc; --hb: #9fe3bb; }
.h-icon.temp  { --ha: #ffe3b8; --hb: #ffc27d; }
.h-icon.time  { --ha: #d6e6ff; --hb: #a9c8ff; }
.h-icon.pin   { --ha: #ebdeff; --hb: #c9b3ff; }
.sq {
  flex: none; width: 48px; height: 48px; border-radius: 28%;
  display: grid; place-items: center; font-size: 26px; background: var(--chip);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .4);
}

/* ── 등굣길 · 귀갓길 ── */
.commute { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 8px; }
.leg { border-radius: 20px; padding: 14px; background: var(--chip); display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.leg.night { background: var(--night-bg); }
.leg-head { font-size: 13px; font-weight: 700; color: var(--ink-2); }
.leg-temp { font-size: 42px; font-weight: 900; letter-spacing: -0.04em; line-height: 1.1; font-variant-numeric: tabular-nums; }
.leg-mood { font-size: 15px; font-weight: 800; }
.leg-tip { font-size: 13px; color: var(--ink-2); }
.leg-rain {
  margin-top: 6px; align-self: flex-start; font-size: 12px; font-weight: 800;
  color: var(--rain-ink); background: var(--rain-band); border-radius: 999px; padding: 2px 8px;
}
.leg-arrow { align-self: center; display: flex; flex-direction: column; align-items: center; font-size: 18px; color: var(--ink-3); }
.leg-arrow small { font-size: 12px; font-weight: 800; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.commute-note {
  margin: 12px 0 0; font-size: 14px; font-weight: 700; border-radius: 14px; padding: 10px 14px;
  color: var(--warn); background: var(--warn-bg);
}

/* ── 가방 체크리스트 ── */
.checklist { display: grid; gap: 10px; }
.check-item {
  display: flex; align-items: center; gap: 14px; cursor: pointer;
  padding: 14px; border-radius: 18px; border: 1.5px solid var(--line);
  transition: background .2s, border-color .2s;
  -webkit-tap-highlight-color: transparent;
}
.check-item:hover { border-color: var(--ink-3); }
.check-item input { position: absolute; opacity: 0; pointer-events: none; }
.check-item .body { flex: 1; min-width: 0; }
.check-item .title { display: block; font-weight: 700; font-size: 16px; }
.check-item .desc { display: block; font-size: 14px; color: var(--ink-2); }
.check-item .box {
  flex: none; width: 30px; height: 30px; border-radius: 50%;
  border: 2px solid var(--ink-3); display: grid; place-items: center;
  color: transparent; font-size: 16px; font-weight: 800;
  transition: all .2s;
}
.check-item input:focus-visible ~ .box { outline: 3px solid var(--rain-ink); outline-offset: 2px; }
.check-item:has(input:checked) { background: var(--done-bg); border-color: transparent; }
.check-item:has(input:checked) .title { text-decoration: line-through; color: var(--ink-2); }
.check-item input:checked ~ .box { background: var(--done); border-color: var(--done); color: #fff; animation: pop .3s ease; }
.progress { font-size: 13px; font-weight: 700; color: var(--ink-3); white-space: nowrap; }
.progress.all-done { color: var(--done); }
.empty { display: flex; align-items: center; gap: 14px; padding: 16px; border-radius: 18px; background: var(--done-bg); }
.empty .sq { background: var(--card); }
.empty strong { display: block; font-size: 16px; }
.empty span { font-size: 14px; color: var(--ink-2); }

/* ── 교복 코디 ── */
.outfit-row { display: flex; align-items: center; gap: 14px; padding: 14px; border-radius: 18px; background: var(--chip); }
.outfit-row + .outfit-row { margin-top: 8px; }
.outfit-row.extra { background: var(--warn-bg); }
.outfit-row strong { display: block; font-size: 17px; letter-spacing: -0.02em; }
.outfit-row .desc { font-size: 14px; color: var(--ink-2); }
.outfit-row .sq { background: var(--card); }
.sub-title { margin: 16px 0 8px; font-size: 13px; font-weight: 700; color: var(--ink-3); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--chip); border-radius: 999px; padding: 7px 13px;
  font-size: 14px; font-weight: 600;
}
.chip .e { font-size: 17px; }
.fine { margin: 12px 0 0; font-size: 12px; color: var(--ink-3); }

/* ── 오늘 내 하루 (일정 타임라인) ── */
.day { list-style: none; margin: 0; padding: 0; display: grid; }
.step { display: grid; grid-template-columns: 46px 44px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 10px 0; }
.step + .step { border-top: 1px dashed var(--line); }
.step-time { font-size: 14px; font-weight: 800; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.step .sq { width: 44px; height: 44px; font-size: 22px; }
.step.home .sq { background: var(--night-bg); }
.step-label { font-weight: 800; font-size: 15px; }
.step-label .tag {
  display: inline-block; margin-left: 6px; padding: 1px 7px; border-radius: 999px;
  font-size: 11px; font-weight: 800; color: #fff; background: var(--chart-line); vertical-align: 2px;
}
.step-mood { display: block; font-size: 13px; color: var(--ink-2); font-weight: 500; }
.step-temp { text-align: right; font-size: 21px; font-weight: 900; font-variant-numeric: tabular-nums; line-height: 1.2; }
.step-temp small { display: block; font-size: 12px; font-weight: 700; color: var(--ink-3); }
.step.rain .step-temp small { color: var(--rain-ink); }

/* ── 기온 그래프 ── */
.chart-wrap { position: relative; }
#temp-chart { width: 100%; height: 190px; display: block; touch-action: pan-y; }
#temp-chart .band { fill: var(--rain-band); }
#temp-chart .base { stroke: var(--line); stroke-width: 1; }
#temp-chart .area { fill: url(#area-grad); }
#temp-chart .grad-a { stop-color: var(--chart-line); stop-opacity: .22; }
#temp-chart .grad-b { stop-color: var(--chart-line); stop-opacity: 0; }
#temp-chart .line { fill: none; stroke: var(--chart-line); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
#temp-chart .dot { fill: var(--chart-line); stroke: var(--card); stroke-width: 2; }
#temp-chart .lbl { fill: var(--ink); font-size: 12px; font-weight: 700; }
#temp-chart .axis { fill: var(--ink-3); font-size: 11px; }
#temp-chart .cross { stroke: var(--ink-3); stroke-width: 1; stroke-dasharray: 3 3; }
.tooltip {
  position: absolute; top: 0; pointer-events: none;
  background: var(--ink); color: var(--card);
  border-radius: 12px; padding: 6px 10px; font-size: 13px; font-weight: 600;
  white-space: nowrap; transform: translateX(-50%); opacity: 0; transition: opacity .12s;
}
.tooltip.show { opacity: 1; }
.chart-note { margin: 8px 0 0; font-size: 13px; color: var(--ink-3); display: flex; align-items: center; gap: 6px; }
.chart-note i { width: 12px; height: 12px; border-radius: 3px; background: var(--rain-band); display: inline-block; }

/* ── 지역별 일교차 ── */
.search { position: relative; display: block; margin-bottom: 10px; }
.search::before { content: "🔍"; position: absolute; left: 14px; top: 50%; transform: translateY(-50%); font-size: 15px; }
.search input {
  width: 100%; border: 1.5px solid transparent; border-radius: 16px; background: var(--chip);
  color: var(--ink); font: inherit; font-size: 16px; padding: 12px 14px 12px 42px; outline: none;
  transition: border-color .15s, background .15s;
}
.search input::placeholder { color: var(--ink-3); }
.search input:focus { border-color: var(--chart-line); background: var(--card); }
.top3 { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 0 0 12px; font-size: 13px; font-weight: 700; color: var(--ink-2); }
.top3 span { margin-right: 2px; }
.top3 a { text-decoration: none; color: var(--warn); background: var(--warn-bg); border-radius: 999px; padding: 4px 10px; font-variant-numeric: tabular-nums; }
.groups { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
.group-chip {
  font: inherit; font-size: 14px; font-weight: 700; cursor: pointer;
  border: 1.5px solid var(--line); background: transparent; color: var(--ink-2);
  padding: 7px 12px; border-radius: 999px; transition: background .15s, color .15s;
}
.group-chip small { font-size: 12px; color: var(--ink-3); margin-left: 4px; font-variant-numeric: tabular-nums; }
.group-chip:hover { border-color: var(--ink-3); }
.group-chip[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: var(--card); }
.group-chip[aria-pressed="true"] small { color: inherit; opacity: .7; }
.list-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
#region-count { font-size: 13px; font-weight: 700; color: var(--ink-3); white-space: nowrap; }
.sort { display: flex; gap: 2px; }
.sort button {
  font: inherit; font-size: 12px; font-weight: 700; border: 0; cursor: pointer;
  background: transparent; color: var(--ink-3); padding: 5px 10px; border-radius: 999px;
}
.sort button[aria-pressed="true"] { background: var(--chip); color: var(--ink); }
.no-result { text-align: center; color: var(--ink-3); font-size: 14px; padding: 16px 0; margin: 0; }
/* 앱 아이콘 그리드 (휴대폰 홈 화면처럼) */
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(66px, 1fr)); gap: 18px 6px; padding-top: 4px; }
.app { display: flex; flex-direction: column; align-items: center; gap: 2px; color: inherit; text-decoration: none; min-width: 0; -webkit-tap-highlight-color: transparent; }
.app-icon {
  position: relative; width: 62px; aspect-ratio: 1; border-radius: 28%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  color: #fff; margin-bottom: 6px;
  background: linear-gradient(160deg, var(--ia), var(--ib));
  box-shadow: 0 4px 12px rgba(20, 24, 36, .16), inset 0 1px 0 rgba(255, 255, 255, .35);
  transition: transform .15s cubic-bezier(.2, .8, .2, 1);
}
.app-icon.big  { --ia: #ea580c; --ib: #c2410c; }
.app-icon.mid  { --ia: #1f9d74; --ib: #12805f; }
.app-icon.calm { --ia: #3d7ff5; --ib: #2a5fd0; }
.app-icon .cap { font-size: 9.5px; font-weight: 800; letter-spacing: .02em; opacity: .9; }
.app-icon .num { font-size: 22px; font-weight: 900; line-height: 1.05; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.app-icon .badge {
  position: absolute; top: -6px; right: -6px; width: 24px; height: 24px; border-radius: 50%;
  display: grid; place-items: center; font-size: 13px;
  background: var(--card); box-shadow: 0 2px 6px rgba(20, 24, 36, .25);
}
.app:hover .app-icon { transform: translateY(-3px) scale(1.04); }
.app:active .app-icon { transform: scale(.92); }
.app:focus-visible { outline: none; }
.app:focus-visible .app-icon { outline: 3px solid var(--rain-ink); outline-offset: 3px; }
.app.current .app-icon { outline: 3px solid var(--chart-line); outline-offset: 3px; }
.app-name { font-size: 13px; font-weight: 700; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.app-sub { font-size: 11px; color: var(--ink-3); font-variant-numeric: tabular-nums; white-space: nowrap; }
.app.current .app-sub { color: var(--chart-line); font-weight: 800; }
.icon-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 18px 0 0; font-size: 12px; color: var(--ink-2); }
.icon-legend span { display: inline-flex; align-items: center; gap: 6px; }
.icon-legend i { width: 12px; height: 12px; border-radius: 4px; display: inline-block; }

footer { text-align: center; color: var(--ink-3); font-size: 13px; padding-top: 8px; }
footer p { margin: 2px 0; }

/* ── 움직임 ── */
.rise { animation: rise .5s cubic-bezier(.2, .8, .2, 1) both; }
.rise:nth-child(2) { animation-delay: .05s; }
.rise:nth-child(3) { animation-delay: .1s; }
.rise:nth-child(4) { animation-delay: .15s; }
.rise:nth-child(5) { animation-delay: .2s; }
.rise:nth-child(6) { animation-delay: .25s; }
@keyframes rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes pop { 0% { transform: scale(.6); } 70% { transform: scale(1.15); } 100% { transform: scale(1); } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}

@media (max-width: 420px) {
  .theme-switch .label { display: none; }   /* 좁은 화면에선 아이콘만 */
  .theme-switch button { padding: 6px 10px; font-size: 15px; }
  .hero h1 { font-size: 23px; }
  .hero-emoji { font-size: 60px; }
  .leg { padding: 12px; }
  .leg-temp { font-size: 36px; }
}

/* ── 태블릿: 카드 2열 ── */
@media (min-width: 760px) {
  main { max-width: 1040px; padding: 28px 24px 56px; gap: 18px; }
  .layout, .content { gap: 18px; }
  .content { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .content > .hero, .content > .notice, .content > .wide { grid-column: 1 / -1; }
  .hero { padding: 28px 32px 26px; }
  .hero h1 { font-size: 32px; }
  .hero-emoji { font-size: 96px; }
  .schedule-options { max-width: 520px; }
  .card { padding: 24px; }
  #temp-chart { height: 230px; }
  .leg { padding: 18px 20px; }
  .leg-temp { font-size: 52px; }
  /* 일정은 가로 흐름으로 */
  .day { grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 8px; }
  .step {
    grid-template-columns: 1fr; justify-items: center; text-align: center; gap: 4px;
    padding: 14px 6px; border-radius: 18px; background: var(--chip);
  }
  .step + .step { border-top: 0; }
  .step .sq { background: var(--card); }
  .step.home .sq { background: var(--night-bg); }
  .step-temp { text-align: center; }
  .step-label .tag { display: block; margin: 2px auto 0; width: fit-content; }
}

/* ── 데스크톱: 왼쪽 브리핑 + 오른쪽 지역 사이드바 ── */
@media (min-width: 1180px) {
  main { max-width: 1320px; }
  .layout { grid-template-columns: minmax(0, 1fr) 380px; align-items: start; }
}
""".replace("%DARK_TOKENS%", DARK_TOKENS)


# ──────────────────────────────────────────────────────────────────
# 동작 — 귀가 시간에 맞춰 학생용 카드들을 계산·표시
# ──────────────────────────────────────────────────────────────────
PAGE_JS = r"""
(function () {
  var data = JSON.parse(document.getElementById('weather-data').textContent);
  var R = data.rules;  // analyzer.py와 같은 판정 기준 (강수확률, 일교차, 등하교 기온 차)

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function deg(t) { return (Math.round(t * 10) / 10) + '°'; }
  function store(key, value) {
    try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) { /* 저장 불가 환경 */ }
  }
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  // ── 테마: 자동(기기 설정) / 라이트 / 다크 ──
  var themeBtns = Array.prototype.slice.call(document.querySelectorAll('[data-theme-choice]'));
  function applyTheme(choice) {
    if (choice === 'light' || choice === 'dark') document.documentElement.setAttribute('data-theme', choice);
    else document.documentElement.removeAttribute('data-theme');
    themeBtns.forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-theme-choice') === choice ? 'true' : 'false');
    });
  }
  applyTheme(load('weather-theme') || 'auto');
  themeBtns.forEach(function (b) {
    b.addEventListener('click', function () {
      var choice = b.getAttribute('data-theme-choice');
      store('weather-theme', choice === 'auto' ? null : choice);
      applyTheme(choice);
    });
  });

  // ── 한국 시간 / 인사말 (학생 하루에 맞춰) ──
  var now = new Date();
  var kst = new Date(now.getTime() + (now.getTimezoneOffset() + 540) * 60000);
  var hour = kst.getHours();
  var isToday = ('' + kst.getFullYear() + pad(kst.getMonth() + 1) + pad(kst.getDate())) === data.date;
  document.getElementById('greeting').textContent =
      hour < 5 ? '아직 새벽이에요, 조금 더 자요 😴'
    : hour < 8 ? '좋은 아침! 늦지 않게 출발해요 🏃'
    : hour < 12 ? '오전 수업 화이팅 ✏️'
    : hour < 13 ? '맛있는 점심 먹어요 🍱'
    : hour < 16 ? '오후 수업도 힘내요 💪'
    : hour < 22 ? '오늘 하루도 수고 많았어요 🌙'
    : '집에 잘 도착했나요? 푹 쉬어요 🛌';
  if (!isToday) document.getElementById('stale').hidden = false;

  // ── 학생 맞춤 기준표 ──
  var SKY_EMOJI = { 1: '☀️', 3: '⛅', 4: '☁️' };
  var SKY_TEXT = { 1: '맑음', 3: '구름많음', 4: '흐림' };
  var PTY_EMOJI = { 1: '🌧️', 2: '🌨️', 3: '❄️', 4: '🌦️' };
  var PTY_TEXT = { 1: '비', 2: '비/눈', 3: '눈', 4: '소나기' };
  var SCHEDULES = { 16: '하교 · 귀가', 18: '방과후 끝 · 귀가', 21: '학원 끝 · 귀가', 22: '야자 끝 · 귀가' };
  var EVENTS = [
    { h: 8, icon: '🏫', label: '등교' },
    { h: 12, icon: '🍱', label: '점심시간' },
    { h: 16, icon: '🔔', label: '정규 수업 끝' },
    { h: 18, icon: '📚', label: '학원·자습 이동' }
  ];
  // 낮 최고 기온 기준 교복 (학교마다 규정이 다르니 참고용)
  var UNIFORMS = [
    [28, '👕', '하복 반팔', '시원한 하복에, 땀 식힐 손풍기도 챙기면 좋아요'],
    [23, '👕', '하복', '반팔 하복이면 충분해요'],
    [20, '🧶', '하복 + 얇은 가디건', '아침엔 가디건 입고, 낮엔 벗어서 가방에'],
    [17, '👔', '춘추복 (셔츠 + 조끼·가디건)', '긴팔 셔츠에 조끼나 가디건을 겹쳐 입어요'],
    [12, '🧥', '동복 재킷', '셔츠 위에 니트조끼, 그 위에 교복 재킷'],
    [9, '🧥', '동복 + 니트', '교복 재킷 안에 니트, 위에 얇은 패딩'],
    [5, '🧥', '동복 + 패딩', '교복 위에 패딩이나 코트를 꼭 입어요'],
    [-Infinity, '🧣', '동복 + 롱패딩', '롱패딩에 목도리·장갑까지 단단히']
  ];
  // 사복(학원·주말)일 때 — analyzer.py OUTFIT_TABLE과 같음
  var OUTFITS = [
    [28, '민소매, 반팔, 반바지'], [23, '반팔, 얇은 셔츠, 면바지'], [20, '긴팔티, 가디건, 후드티, 면바지'],
    [17, '얇은 니트, 맨투맨, 가디건, 청바지'], [12, '자켓, 가디건, 야상, 기모 후드티'],
    [9, '트렌치코트, 야상, 점퍼, 기모 바지'], [5, '코트, 가죽자켓, 히트텍, 니트'],
    [-Infinity, '패딩, 두꺼운 코트, 목도리, 기모 제품']
  ];
  var OUTFIT_EMOJI = {
    '민소매': '🎽', '반팔': '👕', '반바지': '🩳', '얇은 셔츠': '👔', '면바지': '👖', '긴팔티': '👕',
    '가디건': '🧶', '후드티': '🧥', '얇은 니트': '🧶', '맨투맨': '👕', '청바지': '👖', '자켓': '🧥',
    '야상': '🧥', '기모 후드티': '🧥', '트렌치코트': '🧥', '점퍼': '🧥', '기모 바지': '👖', '코트': '🧥',
    '가죽자켓': '🧥', '히트텍': '🔥', '니트': '🧶', '패딩': '🧥', '두꺼운 코트': '🧥', '목도리': '🧣', '기모 제품': '🧤'
  };
  function pick(table, t) { for (var i = 0; i < table.length; i++) if (t >= table[i][0]) return table[i]; return table[table.length - 1]; }
  function mood(t) {
    return t >= 28 ? ['🥵', '더워요'] : t >= 23 ? ['😎', '따뜻해요'] : t >= 17 ? ['🙂', '선선해요']
         : t >= 12 ? ['🍃', '쌀쌀해요'] : t >= 5 ? ['🥶', '추워요'] : ['🧊', '꽁꽁 추워요'];
  }
  function wearTip(t) {
    return t >= 23 ? '반팔로 충분해요' : t >= 17 ? '얇은 겉옷 하나면 OK' : t >= 12 ? '재킷이나 가디건 걸치기'
         : t >= 5 ? '패딩·코트 꼭 입기' : '롱패딩·목도리 필수';
  }
  function weatherEmoji(p) {
    if (PTY_EMOJI[p.pty]) return PTY_EMOJI[p.pty];
    if (p.h >= 19 && p.sky === 1) return '🌙';   // 저녁 이후 맑은 하늘은 해 대신 달
    return SKY_EMOJI[p.sky] || '🌤️';
  }

  // ── 귀가 시간까지의 날씨 분석 (analyzer.py와 같은 규칙) ──
  function plan(end) {
    var hrs = data.hourly.filter(function (p) { return p.h >= 8 && p.h <= end; });
    var temps = hrs.map(function (p) { return p.t; });
    var min = Math.min.apply(null, temps), max = Math.max.apply(null, temps);
    var start = hrs[0], last = hrs[hrs.length - 1];
    var periods = [];
    hrs.forEach(function (p) {
      if (!p.rain) return;
      var cur = periods[periods.length - 1];
      if (cur && cur.end === p.h - 1) { cur.end = p.h; cur.pop = Math.max(cur.pop, p.pop); if (p.pty) cur.kinds[PTY_TEXT[p.pty]] = 1; }
      else { var k = {}; if (p.pty) k[PTY_TEXT[p.pty]] = 1; periods.push({ start: p.h, end: p.h, pop: p.pop, kinds: k }); }
    });
    var skyCount = {};
    hrs.forEach(function (p) { skyCount[p.sky] = (skyCount[p.sky] || 0) + 1; });
    var sky = Object.keys(skyCount).sort(function (a, b) { return skyCount[b] - skyCount[a]; })[0];
    return {
      end: end, hrs: hrs, min: min, max: max, start: start, last: last, periods: periods,
      rain: periods.length > 0,
      maxPop: Math.max.apply(null, hrs.map(function (p) { return p.pop; })),
      bigGap: (max - min >= R.gap) || (start.t - last.t >= R.drop),
      sky: +sky
    };
  }
  function periodText(p) {
    var kinds = Object.keys(p.kinds).join('·') || '비';
    return (p.start === p.end ? p.start + '시' : p.start + '~' + p.end + '시') + ' ' + kinds;
  }

  // ── 히어로 ──
  var heroEl = document.getElementById('hero');
  function renderHero(P) {
    var v = P.rain && P.bigGap ? '우산이랑 겉옷, 둘 다 챙겨요!'
      : P.rain ? '오늘은 우산 챙겨서 등교해요 ☔'
      : P.bigGap ? '귀갓길엔 쌀쌀해요, 겉옷 챙겨요'
      : P.last.t <= 5 ? '귀갓길 꽁꽁! 따뜻하게 입어요'
      : P.start.t <= 5 ? '등굣길 꽁꽁! 따뜻하게 입고 나가요'
      : Math.min(P.start.t, P.last.t) < 12 ? '등하굣길이 쌀쌀해요, 겉옷 입고 나가요'
      : P.max >= 28 ? '더운 날이에요, 물 꼭 챙겨요'
      : '가볍게 등교해도 좋은 날이에요';
    document.getElementById('verdict').textContent = v;
    document.getElementById('verdict-sub').textContent =
      (SKY_TEXT[P.sky] || '') + ' · 등교 ' + deg(P.start.t) + ' → 귀가 ' + deg(P.last.t) + ' · 낮 최고 ' + deg(P.max);
    document.getElementById('window-label').textContent = '등교 8시 ~ 귀가 ' + P.end + '시';
    var theme = P.rain ? 'rain' : ({ 1: 'sunny', 3: 'partly', 4: 'cloudy' }[P.sky] || 'partly');
    heroEl.className = heroEl.className.replace(/\b(sunny|partly|cloudy|rain)\b/, theme);
    var rainHour = P.hrs.filter(function (p) { return PTY_EMOJI[p.pty]; })[0];
    document.getElementById('hero-emoji').textContent = P.rain ? (rainHour ? PTY_EMOJI[rainHour.pty] : '🌧️') : (SKY_EMOJI[P.sky] || '🌤️');
  }

  // ── 등굣길 · 귀갓길 ──
  function leg(cls, head, p) {
    var m = mood(p.t);
    var box = make('div', 'leg ' + cls);
    box.appendChild(make('span', 'leg-head', head));
    box.appendChild(make('span', 'leg-temp', deg(p.t)));
    box.appendChild(make('span', 'leg-mood', m[0] + ' ' + m[1]));
    box.appendChild(make('span', 'leg-tip', wearTip(p.t)));
    if (p.rain) box.appendChild(make('span', 'leg-rain', weatherEmoji(p) + ' 비 ' + p.pop + '%'));
    return box;
  }
  function renderCommute(P) {
    var el = document.getElementById('commute');
    el.textContent = '';
    el.appendChild(leg('morning', '🏫 등굣길 · 8시', P.start));
    var diff = Math.round((P.last.t - P.start.t) * 10) / 10;
    var arrow = make('div', 'leg-arrow', '→');
    arrow.appendChild(make('small', null, (diff > 0 ? '+' : '') + diff + '°'));
    el.appendChild(arrow);
    el.appendChild(leg('night', '🏠 귀갓길 · ' + P.end + '시', P.last));
    var note = document.getElementById('commute-note');
    var drop = Math.round((P.max - P.last.t) * 10) / 10;
    note.hidden = !(P.bigGap || drop >= 5);
    note.textContent = '⚠️ 낮(최고 ' + deg(P.max) + ')보다 귀갓길이 ' + drop + '° 더 추워요. 아침에 입은 그대로면 밤엔 쌀쌀해요!';
  }

  // ── 가방 체크리스트 ──
  var storeKey = 'weather-checklist-' + data.date + '-' + data.slug;
  var saved = {};
  try { saved = JSON.parse(load(storeKey) || '{}'); } catch (e) { saved = {}; }
  function renderChecklist(P) {
    var items = [];
    if (P.rain) items.push(['umbrella', '☔', '우산', P.periods.map(periodText).join(', ') + ' 예보 (최대 ' + Math.max.apply(null, P.periods.map(function (p) { return p.pop; })) + '%)']);
    if (P.bigGap) items.push(['jacket', '🧥', '입고 벗기 편한 겉옷', '귀갓길 ' + P.end + '시 ' + deg(P.last.t) + ' · 바람막이/가디건/집업']);
    if (P.last.t <= 5 || P.min <= 3) items.push(['hotpack', '🔥', '핫팩', '귀갓길 ' + deg(P.last.t) + ', 주머니에 쏙 넣어 가요']);
    if (P.max >= 28) items.push(['water', '💧', '물·손풍기', '낮 최고 ' + deg(P.max) + ', 더위 조심']);

    var el = document.getElementById('checklist');
    var progress = document.getElementById('progress');
    el.textContent = '';
    if (!items.length) {
      var empty = make('div', 'empty');
      empty.appendChild(make('span', 'sq', '✨'));
      var txt = make('div');
      txt.appendChild(make('strong', null, '따로 챙길 건 없어요!'));
      txt.appendChild(make('span', null, '비 소식도, 큰 일교차도 없어요. 입고 나간 옷 그대로 하루 OK 🎒'));
      empty.appendChild(txt);
      el.appendChild(empty);
      progress.textContent = '';
      return;
    }
    var list = make('div', 'checklist');
    var boxes = [];
    items.forEach(function (it) {
      var label = make('label', 'check-item');
      var input = make('input');
      input.type = 'checkbox'; input.name = it[0]; input.checked = !!saved[it[0]];
      label.appendChild(input);
      label.appendChild(make('span', 'sq', it[1]));
      var body = make('span', 'body');
      body.appendChild(make('span', 'title', it[2]));
      body.appendChild(make('span', 'desc', it[3]));
      label.appendChild(body);
      label.appendChild(make('span', 'box', '✓'));
      list.appendChild(label);
      boxes.push(input);
    });
    el.appendChild(list);
    function update() {
      var done = boxes.filter(function (b) { return b.checked; }).length;
      progress.textContent = done === boxes.length ? '준비 완료! 잘 다녀와요 🎉' : boxes.length + '개 중 ' + done + '개 챙김';
      progress.classList.toggle('all-done', done === boxes.length);
    }
    boxes.forEach(function (b) {
      b.addEventListener('change', function () { saved[b.name] = b.checked; store(storeKey, JSON.stringify(saved)); update(); });
    });
    update();
  }

  // ── 교복 코디 ──
  function outfitRow(cls, emoji, title, desc) {
    var row = make('div', 'outfit-row' + (cls ? ' ' + cls : ''));
    row.appendChild(make('span', 'sq', emoji));
    var body = make('div');
    body.appendChild(make('strong', null, title));
    body.appendChild(make('span', 'desc', desc));
    row.appendChild(body);
    return row;
  }
  function renderOutfit(P) {
    var el = document.getElementById('outfit');
    el.textContent = '';
    var u = pick(UNIFORMS, P.max);
    el.appendChild(outfitRow('', u[1], u[2], u[3]));
    var cold = Math.min(P.start.t, P.last.t);
    if (P.bigGap || P.max - cold >= 5) {
      var when = P.last.t <= P.start.t ? '귀갓길 ' + P.end + '시 ' + deg(P.last.t) : '등굣길 8시 ' + deg(P.start.t);
      el.appendChild(outfitRow('extra', '🎒', '가방에 겉옷 하나 더', when + ' — ' + wearTip(cold)));
    }
    el.appendChild(make('p', 'sub-title', '학원·주말에 사복이라면'));
    var chips = make('div', 'chips');
    pick(OUTFITS, P.max)[1].split(', ').forEach(function (item) {
      var chip = make('span', 'chip');
      chip.appendChild(make('span', 'e', OUTFIT_EMOJI[item] || '👕'));
      chip.appendChild(document.createTextNode(item));
      chips.appendChild(chip);
    });
    el.appendChild(chips);
    document.getElementById('outfit-meta').textContent = '낮 최고 ' + deg(P.max) + ' 기준';
  }

  // ── 오늘 내 하루 (학교 일정별 날씨) ──
  function renderDay(P) {
    var el = document.getElementById('day');
    el.textContent = '';
    var steps = EVENTS.filter(function (e) { return e.h < P.end; })
      .concat([{ h: P.end, icon: '🏠', label: SCHEDULES[P.end] || '귀가', home: true }]);
    var nextMarked = false;
    steps.forEach(function (s) {
      var p = data.hourly.filter(function (x) { return x.h === s.h; })[0];
      if (!p) return;
      var li = make('li', 'step' + (s.home ? ' home' : '') + (p.rain ? ' rain' : ''));
      li.appendChild(make('span', 'step-time', s.h + '시'));
      li.appendChild(make('span', 'sq', s.icon));
      var label = make('span', 'step-label', s.label);
      if (isToday && !nextMarked && s.h >= hour) { label.appendChild(make('span', 'tag', s.h === hour ? '지금' : '다음')); nextMarked = true; }
      var m = mood(p.t);
      label.appendChild(make('span', 'step-mood', m[0] + ' ' + m[1]));
      li.appendChild(label);
      var temp = make('span', 'step-temp', deg(p.t));
      temp.appendChild(make('small', null, weatherEmoji(p) + (p.rain ? ' ' + p.pop + '%' : '')));
      li.appendChild(temp);
      el.appendChild(li);
    });
  }

  // ── 기온 그래프 (등교 ~ 귀가) ──
  var NS = 'http://www.w3.org/2000/svg';
  var svg = document.getElementById('temp-chart');
  var tip = document.getElementById('tooltip');
  function svgEl(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (text != null) node.textContent = text;
    svg.appendChild(node);
    return node;
  }
  function drawChart(P) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var pts = P.hrs;
    var W = svg.clientWidth || 320, H = svg.clientHeight || 190;
    var padL = 18, padR = 18, padT = 34, padB = 30;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    var temps = pts.map(function (p) { return p.t; });
    var lo = Math.floor(Math.min.apply(null, temps)) - 2, hi = Math.ceil(Math.max.apply(null, temps)) + 2;
    var n = pts.length, step = (W - padL - padR) / Math.max(1, n - 1);
    function x(i) { return padL + i * step; }
    function y(t) { return padT + (hi - t) / (hi - lo) * (H - padT - padB); }

    var defs = svgEl('defs', {});
    var grad = document.createElementNS(NS, 'linearGradient');
    grad.setAttribute('id', 'area-grad'); grad.setAttribute('x1', 0); grad.setAttribute('y1', 0);
    grad.setAttribute('x2', 0); grad.setAttribute('y2', 1);
    ['grad-a', 'grad-b'].forEach(function (cls, i) {
      var s = document.createElementNS(NS, 'stop'); s.setAttribute('offset', String(i)); s.setAttribute('class', cls); grad.appendChild(s);
    });
    defs.appendChild(grad);

    pts.forEach(function (p, i) {
      if (p.rain) svgEl('rect', { 'class': 'band', x: Math.max(padL - step / 2, x(i) - step / 2), y: padT - 14, width: step, height: H - padB - padT + 14 });
    });
    svgEl('line', { 'class': 'base', x1: padL, x2: W - padR, y1: H - padB, y2: H - padB });
    var d = pts.map(function (p, i) { return (i ? 'L' : 'M') + x(i) + ' ' + y(p.t); }).join(' ');
    svgEl('path', { 'class': 'area', d: d + ' L' + x(n - 1) + ' ' + (H - padB) + ' L' + x(0) + ' ' + (H - padB) + ' Z' });
    svgEl('path', { 'class': 'line', d: d });

    var gap = 44, lastX = -Infinity;
    pts.forEach(function (p, i) {
      var isLast = i === n - 1;
      if (p.h % 2 !== 0 && !isLast) return;
      if (!isLast && (x(i) - lastX < gap || x(n - 1) - x(i) < gap)) return;
      svgEl('text', { 'class': 'axis', x: x(i), y: H - 10, 'text-anchor': i === 0 ? 'start' : isLast ? 'end' : 'middle' }, p.h + '시');
      lastX = x(i);
    });

    // 직접 라벨: 등교, 귀가, 최고 (이웃 점이 더 높으면 라벨을 아래로)
    var maxI = temps.indexOf(Math.max.apply(null, temps));
    var marks = [[0, '등교 ' + deg(pts[0].t), 'start', pts[1] && pts[1].t > pts[0].t],
                 [n - 1, '귀가 ' + deg(pts[n - 1].t), 'end', pts[n - 2] && pts[n - 2].t > pts[n - 1].t]];
    if (maxI > 1 && maxI < n - 2) marks.push([maxI, '최고 ' + deg(pts[maxI].t), 'middle', false]);
    marks.forEach(function (m) {
      var cy = y(pts[m[0]].t), below = m[3] && cy + 22 <= H - padB - 4;
      svgEl('circle', { 'class': 'dot', cx: x(m[0]), cy: cy, r: 4.5 });
      svgEl('text', { 'class': 'lbl', x: x(m[0]), y: below ? cy + 22 : cy - 12, 'text-anchor': m[2] }, m[1]);
    });

    var cross = svgEl('line', { 'class': 'cross', y1: padT - 14, y2: H - padB, visibility: 'hidden' });
    var hoverDot = svgEl('circle', { 'class': 'dot', r: 5, visibility: 'hidden' });
    var hit = svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: 'transparent' });
    function show(evt) {
      var rect = svg.getBoundingClientRect();
      var i = Math.min(n - 1, Math.max(0, Math.round(((evt.clientX - rect.left) * (W / rect.width) - padL) / step)));
      var p = pts[i];
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
      hoverDot.setAttribute('cx', x(i)); hoverDot.setAttribute('cy', y(p.t)); hoverDot.setAttribute('visibility', 'visible');
      tip.textContent = p.h + '시 · ' + deg(p.t) + ' · ' + weatherEmoji(p) + ' 💧' + p.pop + '%';
      tip.style.left = Math.min(rect.width - 70, Math.max(70, x(i) * (rect.width / W))) + 'px';
      tip.classList.add('show');
    }
    function hide() { cross.setAttribute('visibility', 'hidden'); hoverDot.setAttribute('visibility', 'hidden'); tip.classList.remove('show'); }
    hit.addEventListener('pointermove', show);
    hit.addEventListener('pointerdown', show);
    hit.addEventListener('pointerleave', hide);
    document.getElementById('chart-note').innerHTML = P.rain
      ? '<i></i>파란 영역은 비 예보 시간이에요' : '그래프를 누르면 시간별 기온이 보여요';
    document.getElementById('chart-meta').textContent = '8시 ~ ' + P.end + '시 · 일교차 ' + deg(P.max - P.min);
  }

  // ── 귀가 시간 선택 → 전부 다시 계산 ──
  var current;
  var endBtns = Array.prototype.slice.call(document.querySelectorAll('[data-end]'));
  function renderAll(end) {
    current = plan(end);
    endBtns.forEach(function (b) { b.setAttribute('aria-pressed', +b.getAttribute('data-end') === end ? 'true' : 'false'); });
    renderHero(current);
    renderCommute(current);
    renderChecklist(current);
    renderOutfit(current);
    renderDay(current);
    drawChart(current);
  }
  endBtns.forEach(function (b) {
    b.addEventListener('click', function () {
      var end = +b.getAttribute('data-end');
      store('weather-end-hour', String(end));
      renderAll(end);
    });
  });
  var savedEnd = +(load('weather-end-hour') || 22);
  renderAll(SCHEDULES[savedEnd] ? savedEnd : 22);
  var timer;
  window.addEventListener('resize', function () { clearTimeout(timer); timer = setTimeout(function () { drawChart(current); }, 120); });

  // ── 다른 지역 일교차: 권역 칩 + 검색(초성 포함) + 정렬, 앱 아이콘 모양 ──
  var regions = data.regions || [];
  var listEl = document.getElementById('region-list');
  if (listEl && regions.length) {
    var input = document.getElementById('region-search');
    var groupsEl = document.getElementById('region-groups');
    var countEl = document.getElementById('region-count');
    var topEl = document.getElementById('region-top');
    var noResult = document.getElementById('region-empty');
    var sortBtns = Array.prototype.slice.call(document.querySelectorAll('.sort button'));
    var GROUPS = ['전체', '수도권', '강원', '충청', '전라', '경상', '제주'];
    var me = regions.filter(function (r) { return r.slug === data.slug; })[0];
    var group = me ? me.group : '전체';
    var sortMode = 'gap';
    var CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
    function chosung(s) {
      var out = '';
      for (var i = 0; i < s.length; i++) {
        var c = s.charCodeAt(i) - 0xAC00;
        out += (c >= 0 && c < 11172) ? CHO.charAt(Math.floor(c / 588)) : s.charAt(i);
      }
      return out;
    }
    // 지역 이름은 어디든 포함되면, 시·도 이름은 앞부분이 맞으면 결과에 포함
    function matches(r, q) {
      if (/^[ㄱ-ㅎ]+$/.test(q)) return chosung(r.name).indexOf(q) !== -1 || chosung(r.province).indexOf(q) === 0;
      return r.name.indexOf(q) !== -1 || r.province.indexOf(q) === 0;
    }
    function byGap(a, b) { return b.gap - a.gap || a.name.localeCompare(b.name, 'ko'); }
    function byName(a, b) { return a.name.localeCompare(b.name, 'ko'); }

    topEl.appendChild(make('span', null, '🔥 일교차 큰 곳'));
    regions.slice().sort(byGap).slice(0, 3).forEach(function (r) {
      var link = make('a', null, r.name + ' ' + r.gap + '°');
      link.href = r.url;
      topEl.appendChild(link);
    });

    var chips = [];
    GROUPS.forEach(function (g) {
      var n = g === '전체' ? regions.length : regions.filter(function (r) { return r.group === g; }).length;
      if (!n) return;
      var chip = make('button', 'group-chip', g);
      chip.type = 'button';
      chip.setAttribute('data-group', g);
      chip.appendChild(make('small', null, String(n)));
      chip.addEventListener('click', function () { group = g; input.value = ''; renderRegions(); });
      groupsEl.appendChild(chip);
      chips.push(chip);
    });

    function tile(r) {
      var isCurrent = r.slug === data.slug;
      var tier = r.bigGap ? 'big' : (r.gap < 5 ? 'calm' : 'mid');
      var a = make('a', 'app' + (isCurrent ? ' current' : ''));
      a.href = r.url;
      a.title = r.province + ' ' + r.name + ' · 일교차 ' + r.gap + '° (' + r.min + '° ~ ' + r.max + '°)' + (r.umbrella ? ' · 비 예보' : '');
      var icon = make('span', 'app-icon ' + tier);
      icon.appendChild(make('span', 'cap', r.bigGap ? '⚠ 일교차' : '일교차'));
      icon.appendChild(make('span', 'num', r.gap + '°'));
      if (r.umbrella) icon.appendChild(make('span', 'badge', '☔'));
      a.appendChild(icon);
      a.appendChild(make('span', 'app-name', r.name));
      a.appendChild(make('span', 'app-sub', isCurrent ? '보는 중' : r.min + '~' + r.max + '°'));
      return a;
    }
    function renderRegions() {
      var q = input.value.replace(/\s+/g, '');
      var rows = regions.filter(function (r) { return q ? matches(r, q) : (group === '전체' || r.group === group); });
      rows.sort(sortMode === 'gap' ? byGap : byName);
      chips.forEach(function (c) { c.setAttribute('aria-pressed', !q && c.getAttribute('data-group') === group ? 'true' : 'false'); });
      countEl.textContent = q ? '검색 결과 ' + rows.length + '곳' : (group === '전체' ? '전국' : group) + ' ' + rows.length + '곳';
      listEl.textContent = '';
      rows.forEach(function (r) { listEl.appendChild(tile(r)); });
      noResult.hidden = rows.length > 0;
    }
    input.addEventListener('input', renderRegions);
    sortBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        sortMode = btn.getAttribute('data-sort');
        sortBtns.forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
        renderRegions();
      });
    });
    renderRegions();
  }
})();
"""


# ──────────────────────────────────────────────────────────────────
# HTML 본문 (학생용 카드의 내용은 위 스크립트가 귀가 시간에 맞춰 채움)
# ──────────────────────────────────────────────────────────────────
BODY_TEMPLATE = Template("""<main>
  <header class="topbar">
    $topbar_left
    <div class="theme-switch" role="group" aria-label="화면 테마">
      <button type="button" data-theme-choice="auto" aria-pressed="true" title="기기 설정을 따라가요"><span aria-hidden="true">🖥️</span><span class="label">자동</span></button>
      <button type="button" data-theme-choice="light" aria-pressed="false" title="라이트 모드"><span aria-hidden="true">☀️</span><span class="label">라이트</span></button>
      <button type="button" data-theme-choice="dark" aria-pressed="false" title="다크 모드"><span aria-hidden="true">🌙</span><span class="label">다크</span></button>
    </div>
  </header>
  <div class="layout">
  <div class="content">
  <section class="hero $hero_theme rise" id="hero">
    <div class="hero-top">
      <p class="greeting" id="greeting">안녕하세요 👋</p>
      <a class="loc-chip" href="#regions">📍 $location ▾</a>
    </div>
    <div class="hero-main">
      <div class="hero-text">
        <p class="hero-date">$date_label · <span id="window-label">등교 8시 ~ 귀가 22시</span></p>
        <h1 id="verdict">$verdict</h1>
        <p class="hero-sub" id="verdict-sub"></p>
      </div>
      <div class="hero-emoji" id="hero-emoji" aria-hidden="true">$hero_emoji</div>
    </div>
    <div class="schedule">
      <span class="schedule-label">🏠 나는 오늘 몇 시에 집에 가요?</span>
      <div class="schedule-options" role="group" aria-label="귀가 시간">
        <button type="button" data-end="16" aria-pressed="false">16시<small>정규 하교</small></button>
        <button type="button" data-end="18" aria-pressed="false">18시<small>방과후</small></button>
        <button type="button" data-end="21" aria-pressed="false">21시<small>학원</small></button>
        <button type="button" data-end="22" aria-pressed="true">22시<small>야자</small></button>
      </div>
    </div>
  </section>
$notices
  <section class="card wide rise">
    <div class="card-head">
      <h2><span class="h-icon walk" aria-hidden="true">🚶</span>등굣길 · 귀갓길</h2>
    </div>
    <div class="commute" id="commute"></div>
    <p class="commute-note" id="commute-note" hidden></p>
  </section>

  <section class="card rise">
    <div class="card-head">
      <h2><span class="h-icon bag" aria-hidden="true">🎒</span>가방 챙기기</h2>
      <span class="progress" id="progress"></span>
    </div>
    <div id="checklist"></div>
  </section>

  <section class="card rise">
    <div class="card-head">
      <h2><span class="h-icon shirt" aria-hidden="true">👔</span>오늘 교복 코디</h2>
      <span class="meta" id="outfit-meta"></span>
    </div>
    <div id="outfit"></div>
    <p class="fine">학교마다 교복 규정이 달라요. 참고용으로 봐 주세요!</p>
  </section>

  <section class="card wide rise">
    <div class="card-head">
      <h2><span class="h-icon time" aria-hidden="true">📅</span>오늘 내 하루</h2>
    </div>
    <ol class="day" id="day"></ol>
  </section>

  <section class="card wide rise">
    <div class="card-head">
      <h2><span class="h-icon temp" aria-hidden="true">🌡️</span>기온 흐름</h2>
      <span class="meta" id="chart-meta"></span>
    </div>
    <div class="chart-wrap">
      <svg id="temp-chart" role="img" aria-label="$chart_label"></svg>
      <div class="tooltip" id="tooltip"></div>
    </div>
    <p class="chart-note" id="chart-note"></p>
  </section>
  <noscript>
    <section class="card wide"><p style="white-space:pre-line;margin:0">$plain_text</p></section>
  </noscript>
  </div>
$regions_section
  </div>
  <footer>
    <p>📡 기상청 단기예보 $base_label 기준</p>
    <p>🕒 $generated_at 업데이트</p>
  </footer>
</main>
""")


def _hour_emoji(h: HourlyForecast) -> str:
    if h.pty in PTY_EMOJI:
        return PTY_EMOJI[h.pty]
    return SKY_EMOJI.get(h.sky, "🌤️")


def _hero_theme(forecast: ForecastResult, briefing: Briefing) -> Tuple[str, str]:
    """처음 그려질 때의 히어로 색·이모지 (귀가 22시 기준, 이후 스크립트가 선택에 맞춰 바꿈)"""
    if briefing.need_umbrella:
        rain_pty = next((h.pty for h in forecast.hourly if h.pty in PTY_EMOJI), 1)
        return "rain", PTY_EMOJI[rain_pty]
    sky_code = next((k for k, v in {1: "맑음", 3: "구름많음", 4: "흐림"}.items() if v == briefing.sky_text), 3)
    return {1: "sunny", 3: "partly", 4: "cloudy"}.get(sky_code, "partly"), briefing.sky_emoji


def _verdict(briefing: Briefing) -> str:
    """처음 그려질 때의 한 줄 요약 (스크립트의 renderHero와 같은 문구)"""
    if briefing.need_umbrella and briefing.big_temp_gap:
        return "우산이랑 겉옷, 둘 다 챙겨요!"
    if briefing.need_umbrella:
        return "오늘은 우산 챙겨서 등교해요 ☔"
    if briefing.big_temp_gap:
        return "귀갓길엔 쌀쌀해요, 겉옷 챙겨요"
    if briefing.night_temp <= 5:
        return "귀갓길 꽁꽁! 따뜻하게 입어요"
    if briefing.morning_temp <= 5:
        return "등굣길 꽁꽁! 따뜻하게 입고 나가요"
    if min(briefing.morning_temp, briefing.night_temp) < 12:
        return "등하굣길이 쌀쌀해요, 겉옷 입고 나가요"
    if briefing.max_temp >= 28:
        return "더운 날이에요, 물 꼭 챙겨요"
    return "가볍게 등교해도 좋은 날이에요"


def _chart_label(hourly: List[HourlyForecast]) -> str:
    peak = max(hourly, key=lambda h: h.tmp)
    return (f"시간대별 기온 그래프: {hourly[0].hour}시 {hourly[0].tmp:g}도에서 "
            f"{peak.hour}시 최고 {peak.tmp:g}도, {hourly[-1].hour}시 {hourly[-1].tmp:g}도")


# ──────────────────────────────────────────────────────────────────
# 지역별 페이지 데이터
# ──────────────────────────────────────────────────────────────────
@dataclass
class Report:
    """한 지역의 페이지를 만드는 데 필요한 모든 것."""
    slug: str
    name: str
    province: str
    url: str
    forecast: ForecastResult
    briefing: Briefing


def make_report(slug: str, name: str, province: str, nx: int, ny: int, url: str) -> Report:
    forecast = get_hourly_forecast(nx=nx, ny=ny)
    return Report(slug, name, province, url, forecast, analyze(forecast, name))


def collect_reports(max_workers: int = 4) -> Tuple[Report, List[Report]]:
    """(기본 지역 리포트, 전체 지역 리포트 목록)을 만듭니다.
    일부 지역 조회에 실패해도 나머지는 계속 진행하고, 기본 지역 실패만 오류로 처리합니다."""
    def fetch(region: Region) -> Optional[Report]:
        nx, ny = region.grid
        try:
            return make_report(region.slug, region.name, region.province, nx, ny, f"{region.slug}.html")
        except WeatherAPIError as e:
            print(f"[web_page] {region.name} 조회 실패, 목록에서 제외합니다: {e}")
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        reports = [r for r in pool.map(fetch, REGIONS) if r is not None]

    # 기본 지역(.env의 NX, NY)이 목록에 있으면 그 결과를 재사용
    home_region = find_region_by_grid(config.NX, config.NY)
    same = next((r for r in reports if home_region and r.slug == home_region.slug), None)
    if same:
        briefing = analyze(same.forecast, config.LOCATION_NAME)
        home = Report(same.slug, config.LOCATION_NAME, same.province, HOME_URL, same.forecast, briefing)
    else:
        home = make_report("home", config.LOCATION_NAME, "", config.NX, config.NY, HOME_URL)
    return home, reports


def region_summaries(reports: List[Report]) -> List[dict]:
    """지역별 일교차 목록에 들어갈 요약 데이터 (08~22시 기준)."""
    return [
        {
            "slug": r.slug,
            "name": r.name,
            "province": r.province,
            "group": region_group(r.province),
            "url": r.url,
            "min": r.briefing.min_temp,
            "max": r.briefing.max_temp,
            "gap": round(r.briefing.max_temp - r.briefing.min_temp, 1),
            "bigGap": r.briefing.big_temp_gap,
            "umbrella": r.briefing.need_umbrella,
        }
        for r in reports
    ]


def _regions_section(count: int) -> str:
    if not count:
        return ""
    return f"""  <aside class="card sidebar rise" id="regions">
    <div class="card-head">
      <h2><span class="h-icon pin" aria-hidden="true">📍</span>다른 지역 일교차</h2>
      <span class="meta">전국 {count}곳 · 8~22시</span>
    </div>
    <p class="top3" id="region-top"></p>
    <label class="search"><input id="region-search" type="search" autocomplete="off"
      placeholder="지역 검색 (예: 부산, 경기, ㅈㅈ)" aria-label="지역 검색"></label>
    <div class="groups" id="region-groups" role="group" aria-label="권역 선택"></div>
    <div class="list-head">
      <span id="region-count"></span>
      <div class="sort" role="group" aria-label="정렬">
        <button type="button" data-sort="gap" aria-pressed="true">일교차 큰 순</button>
        <button type="button" data-sort="name" aria-pressed="false">가나다순</button>
      </div>
    </div>
    <div class="tiles" id="region-list"></div>
    <p class="no-result" id="region-empty" hidden>검색 결과가 없어요 🥲</p>
    <p class="icon-legend">
      <span><i style="background:#ea580c"></i>겉옷 필요</span>
      <span><i style="background:#1f9d74"></i>보통</span>
      <span><i style="background:#3d7ff5"></i>일교차 작음 (5° 미만)</span>
      <span>☔ 비 예보</span>
    </p>
  </aside>"""


def _page_data(report: Report, summaries: List[dict]) -> str:
    payload = {
        "date": report.forecast.target_date,
        "slug": report.slug,
        # 판정 기준은 analyzer.py 값을 그대로 넘겨서 웹과 메신저 결과가 같도록 함
        "rules": {"pop": UMBRELLA_POP_THRESHOLD, "gap": TEMP_RANGE_THRESHOLD, "drop": COMMUTE_DROP_THRESHOLD},
        "hourly": [
            {"h": h.hour, "t": h.tmp, "pop": h.pop, "pty": h.pty, "sky": h.sky, "rain": is_rain_hour(h)}
            for h in report.forecast.hourly
        ],
        "regions": summaries,
    }
    # </script> 로 인해 스크립트가 끊기지 않도록 이스케이프
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render_html(report: Report, summaries: Optional[List[dict]] = None,
                home_name: Optional[str] = None) -> str:
    """한 지역의 브리핑 페이지 HTML을 만듭니다.
    summaries: 지역별 일교차 목록 데이터 / home_name: 기본 지역 이름(다른 지역 페이지에서 돌아가기 링크용)"""
    esc = html.escape
    forecast, briefing = report.forecast, report.briefing
    summaries = summaries or []
    theme, hero_emoji = _hero_theme(forecast, briefing)

    # 상단 바 왼쪽: 기본 지역 페이지면 앱 이름, 다른 지역 페이지면 돌아가기 링크
    if home_name and report.url != HOME_URL:
        topbar_left = f'<a class="home-link" href="{HOME_URL}">← {esc(home_name)}로 돌아가기</a>'
    else:
        topbar_left = '<span class="brand"><span class="h-icon" aria-hidden="true">🌤️</span>등하교 날씨</span>'

    notices = []
    if briefing.is_mock:
        notices.append('  <p class="notice rise">⚠️ 테스트 모드: 실제 날씨가 아닌 가짜 데이터예요.</p>')
    notices.append(f'  <p class="notice" id="stale" hidden>📅 이 예보는 {esc(briefing.date_label)} 기준이에요. '
                   '오늘 예보는 아침 5시 30분쯤 업데이트돼요.</p>')

    body = BODY_TEMPLATE.substitute(
        topbar_left=topbar_left,
        regions_section=_regions_section(len(summaries)),
        hero_theme=theme,
        hero_emoji=hero_emoji,
        date_label=esc(briefing.date_label),
        location=esc(briefing.location),
        verdict=esc(_verdict(briefing)),
        notices="\n".join(notices),
        chart_label=esc(_chart_label(forecast.hourly)),
        plain_text=esc(briefing.to_text()),
        base_label=esc(briefing.base_label),
        generated_at=now_kst().strftime("%m월 %d일 %H:%M"),
    )

    title_prefix = "[테스트] " if briefing.is_mock else ""
    title = esc(f"{title_prefix}{briefing.date_label} {briefing.location} 등하교 날씨")
    return (
        "<!doctype html>\n<html lang=\"ko\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n"
        "<link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
        f"<text y='.9em' font-size='90'>{hero_emoji}</text></svg>\">\n"
        "<link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/"
        "dist/web/variable/pretendardvariable-dynamic-subset.min.css\">\n"
        # 저장된 테마를 그리기 전에 적용해서, 다크 모드인데 잠깐 하얗게 깜빡이는 현상 방지
        "<script>try{var t=localStorage.getItem('weather-theme');"
        "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}</script>\n"
        f"<style>{PAGE_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}"
        f"<script type=\"application/json\" id=\"weather-data\">{_page_data(report, summaries)}</script>\n"
        f"<script>{PAGE_JS}</script>\n"
        "</body>\n</html>\n"
    )


def render_error_html(message: str) -> str:
    """날씨를 가져오지 못했을 때 보여줄 간단한 페이지."""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>등하교 날씨</title>
<style>
  body {{ margin: 0; padding: 64px 20px; background: #f6f4f1; color: #232836; text-align: center;
         font-family: "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif; word-break: keep-all; }}
  .e {{ font-size: 64px; }}
  p {{ color: #5b6478; }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #12151c; color: #edf0f6; }} p {{ color: #aab2c3; }} }}
</style></head>
<body><div class="e">🙈</div><h1>날씨 정보를 가져오지 못했어요</h1>
<p>{html.escape(message)}</p><p>오늘은 날씨 앱으로 직접 확인해 주세요 🙏</p></body></html>
"""


def build_site(output_dir: Path = OUTPUT_DIR) -> Tuple[Path, int]:
    """기본 지역(index.html)과 전체 지역 페이지(<slug>.html)를 만들어 저장합니다.
    (저장 폴더, 지역 페이지 수)를 돌려줍니다."""
    home, reports = collect_reports()
    summaries = region_summaries(reports)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / HOME_URL).write_text(render_html(home, summaries, home.name), encoding="utf-8")
    for report in reports:
        (output_dir / report.url).write_text(render_html(report, summaries, home.name), encoding="utf-8")
    return output_dir, len(reports)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        folder, count = build_site()
    except WeatherAPIError as err:
        print(f"❌ 날씨 조회 실패: {err}")
        sys.exit(1)
    print(f"✅ 웹페이지 생성 완료: {folder / HOME_URL} (+ 지역 페이지 {count}개)")
