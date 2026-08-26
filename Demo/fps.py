"""실측 FPS 계산 — 프레임 도착 간격에서 초당 프레임 수를 낸다.

정본: 상위 docs/superpowers/specs/2026-08-16-ui-애니메이션-design.md §4

🔴 **왜 safety_console 이 아니라 별도 모듈인가** — `safety_console` 을 import 하면
   Hailo 백엔드가 함께 로드되고, **프로세스 종료 시 HailoRT 정리에서 죽는다**
   (세그멘테이션/버스 오류. 애니메이션 작업 이전 버전에서도 동일 — 기존 현상).
   순수 계산 함수를 거기 두면 테스트가 그 사고를 그대로 물려받아 exit code 로
   판정할 수 없다. 계산은 장치를 열지 않는 곳에 둔다.
"""

import time


def fps_from_intervals(intervals):
    """프레임 도착 간격(초) 목록 → 실측 FPS. 표본이 없으면 None.

    🔴 평균이 아니라 **중앙값**이다 — 재연결·정지 구간의 큰 간격 하나가
       평균을 통째로 무너뜨린다(측정이 아니라 사고를 재는 꼴이 된다).
    """
    vals = sorted(v for v in intervals if v > 0)
    if not vals:
        return None
    mid = vals[len(vals) // 2] if len(vals) % 2 else \
        (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
    return 1.0 / mid if mid > 0 else None


def fps_stale(last_frame_time, now=None, stale_after=2.0):
    """마지막 프레임이 `stale_after` 초를 넘겼는가 — 프레임을 못 받았으면 True.

    🔴 **왜 따로 필요한가** — `fps_from_intervals` 는 중앙값이라 프레임이 끊겨도
       마지막 간격들이 그대로 남아 **같은 값을 영원히 낸다.** 화면은 멈췄는데
       FPS 는 정상으로 보여 **끊김을 눈으로 알 수 없다**(2026-08-26 발견).
       간격만으로는 알 수 없고 **마지막 도착 시각**을 봐야 한다.

    ⚠️ 임계 2.0 초는 2차 점검 「영상 수신」(`precheck.run_stage2`)과 **같은 값**이다.
       두 곳이 다른 숫자를 쓰면 표시와 점검이 서로 다른 말을 하게 된다.
    """
    now = time.time() if now is None else now
    last = last_frame_time or 0.0
    if not last:
        return True
    return (now - last) >= stale_after
