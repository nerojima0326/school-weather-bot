"""
메신저 알림 발송 모듈.

- 1순위: Discord Webhook Embed 메시지 전송
- 2순위: 카카오톡 오픈빌더 스킬 응답(JSON, version 2.0 / simpleText) 생성
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional

import requests

import config
from analyzer import Briefing, fmt_temp

DISCORD_USERNAME = "등하교 날씨봇"
COLOR_RAIN = 0x3B82F6    # 파랑: 우산 필요
COLOR_CLEAR = 0xF59E0B   # 주황: 우산 불필요
COLOR_ERROR = 0xEF4444   # 빨강: 오류

KAKAO_TEXT_LIMIT = 1000  # 카카오 simpleText 최대 글자 수


# ──────────────────────────────────────────────────────────────────
# Discord
# ──────────────────────────────────────────────────────────────────
def build_discord_payload(briefing: Briefing) -> dict:
    """Discord Webhook으로 보낼 Embed 메시지 JSON을 만듭니다. (3줄 핵심 요약 카드)"""
    footer = f"기상청 단기예보 {briefing.base_label} 기준"
    if briefing.is_mock:
        footer = "⚠️ 테스트 모드(가짜 데이터) · " + footer

    embed = {
        "title": briefing.title,
        "description": "\n\n".join(briefing.summary_lines()),
        "color": COLOR_RAIN if briefing.need_umbrella else COLOR_CLEAR,
        "fields": [
            {"name": "🏫 등교 (08시)", "value": fmt_temp(briefing.morning_temp), "inline": True},
            {"name": "🌙 하교 (22시)", "value": fmt_temp(briefing.night_temp), "inline": True},
            {"name": "🌡️ 최저 / 최고",
             "value": f"{fmt_temp(briefing.min_temp)} / {fmt_temp(briefing.max_temp)}", "inline": True},
            {"name": f"{briefing.sky_emoji} 하늘", "value": briefing.sky_text, "inline": True},
            {"name": "💧 최대 강수확률", "value": f"{briefing.max_pop}%", "inline": True},
            {"name": "☂️ 우산", "value": "필수!" if briefing.need_umbrella else "필요 없음", "inline": True},
        ],
        "footer": {"text": footer},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return {"username": DISCORD_USERNAME, "embeds": [embed]}


def _post_discord(payload: dict, webhook_url: str) -> bool:
    for attempt in range(1, 3):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
        except requests.RequestException as e:
            print(f"[notifier] Discord 전송 실패: {e}")
            return False

        if resp.status_code in (200, 204):
            print("[notifier] ✅ Discord 전송 완료")
            return True
        if resp.status_code == 429 and attempt == 1:
            # 전송 한도 초과 → Discord가 알려준 시간만큼 기다렸다가 한 번 더 시도
            try:
                retry_after = float(resp.json().get("retry_after", 1))
            except ValueError:
                retry_after = 1.0
            time.sleep(min(retry_after, 10))
            continue
        print(f"[notifier] Discord 전송 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
        return False
    return False


def send_discord(briefing: Briefing, webhook_url: Optional[str] = None) -> bool:
    """브리핑을 Discord Embed 메시지로 전송합니다. 성공하면 True."""
    url = webhook_url or config.DISCORD_WEBHOOK_URL
    if not url:
        print("[notifier] DISCORD_WEBHOOK_URL이 설정되지 않아 전송을 건너뜁니다.")
        return False
    return _post_discord(build_discord_payload(briefing), url)


def send_discord_error(message: str, webhook_url: Optional[str] = None) -> bool:
    """날씨를 가져오지 못했을 때 짧은 오류 알림을 보냅니다."""
    url = webhook_url or config.DISCORD_WEBHOOK_URL
    if not url:
        return False
    payload = {
        "username": DISCORD_USERNAME,
        "embeds": [{
            "title": "⚠️ 오늘 날씨 정보를 가져오지 못했어요",
            "description": f"{message}\n\n오늘은 날씨 앱으로 직접 확인해 주세요! 🙏",
            "color": COLOR_ERROR,
        }],
    }
    return _post_discord(payload, url)


# ──────────────────────────────────────────────────────────────────
# 카카오톡 오픈빌더 스킬 응답
# ──────────────────────────────────────────────────────────────────
def build_kakao_text_response(text: str, quick_replies: Optional[List[str]] = None) -> dict:
    """카카오 i 오픈빌더 스킬 응답 규격(version 2.0, simpleText) JSON을 반환합니다.
    quick_replies: 말풍선 아래 버튼으로 보여줄 문구 목록 (누르면 그 문구를 그대로 보냄)"""
    if len(text) > KAKAO_TEXT_LIMIT:
        text = text[: KAKAO_TEXT_LIMIT - 1] + "…"
    template: dict = {"outputs": [{"simpleText": {"text": text}}]}
    if quick_replies:
        template["quickReplies"] = [
            {"label": label[:14], "action": "message", "messageText": label}
            for label in quick_replies[:10]  # 카카오 제한: 최대 10개, 라벨 14자
        ]
    return {"version": "2.0", "template": template}


def build_kakao_skill_response(briefing: Briefing, prefix: str = "",
                               quick_replies: Optional[List[str]] = None) -> dict:
    """브리핑을 카카오 스킬 응답으로 만듭니다. prefix는 브리핑 앞에 붙일 안내 문구입니다."""
    text = f"{prefix}\n\n{briefing.to_text()}" if prefix else briefing.to_text()
    return build_kakao_text_response(text, quick_replies)


def build_kakao_error_response(message: str, quick_replies: Optional[List[str]] = None) -> dict:
    return build_kakao_text_response(f"⚠️ 날씨 정보를 가져오지 못했어요.\n{message}", quick_replies)


# ──────────────────────────────────────────────────────────────────
# 콘솔
# ──────────────────────────────────────────────────────────────────
def print_console(briefing: Briefing) -> None:
    print()
    print(briefing.to_text())
    print()
