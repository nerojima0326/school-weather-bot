"""
등하교 날씨 브리핑 봇 실행 파일.

    python main.py             # 로컬 스케줄러 모드: 켜두면 매일 07:30에 자동 전송
    python main.py --once      # 지금 바로 1회 실행 (GitHub Actions에서 사용)
    python main.py --once --dry-run   # 메신저로 보내지 않고 콘솔에만 출력
"""
from __future__ import annotations

import argparse
import sys
import time

import schedule

import config
from analyzer import analyze
from notifier import print_console, send_discord, send_discord_error
from weather_fetcher import WeatherAPIError, get_hourly_forecast, now_kst


def run_briefing(dry_run: bool = False) -> bool:
    """날씨 조회 → 분석 → 전송을 한 번 수행합니다. 성공하면 True."""
    print(f"\n===== 날씨 브리핑 시작 ({now_kst():%Y-%m-%d %H:%M} KST) =====")
    try:
        forecast = get_hourly_forecast()
    except WeatherAPIError as e:
        print(f"❌ 날씨 조회 실패: {e}")
        if not dry_run:
            send_discord_error(str(e))
        return False

    briefing = analyze(forecast, config.LOCATION_NAME)
    print_console(briefing)

    if dry_run:
        print("[main] --dry-run 모드라서 메신저 전송은 건너뜁니다.")
        return True
    if not config.DISCORD_WEBHOOK_URL:
        print("[main] DISCORD_WEBHOOK_URL이 비어 있어 콘솔 출력만 했습니다. (.env 설정 확인)")
        return True
    return send_discord(briefing)


def _scheduled_job() -> None:
    # 스케줄러 루프가 예외로 죽지 않도록 모든 오류를 잡아 기록만 합니다.
    try:
        run_briefing()
    except Exception as e:
        print(f"❌ 브리핑 중 예상치 못한 오류: {e}")


def run_scheduler() -> None:
    schedule.every().day.at(config.BRIEFING_TIME).do(_scheduled_job)
    print(f"⏰ 스케줄러 시작: 매일 {config.BRIEFING_TIME}에 브리핑을 보냅니다. (종료: Ctrl+C)")
    print(f"   다음 실행 예정: {schedule.next_run():%Y-%m-%d %H:%M}")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n스케줄러를 종료합니다.")


def main() -> None:
    # Windows 콘솔에서 이모지/한글이 깨지거나 오류가 나지 않도록 UTF-8로 출력
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="등하교 날씨 브리핑 봇")
    parser.add_argument("--once", action="store_true", help="지금 바로 1회 실행하고 종료")
    parser.add_argument("--dry-run", action="store_true", help="메신저로 보내지 않고 콘솔에만 출력")
    args = parser.parse_args()

    if args.once or args.dry_run:
        ok = run_briefing(dry_run=args.dry_run)
        sys.exit(0 if ok else 1)
    run_scheduler()


if __name__ == "__main__":
    main()
