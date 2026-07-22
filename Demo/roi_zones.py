"""ROI 구역 판정 — 손끝이 어느 버튼의 어느 단계에 있는가. **판정 규칙의 단일 출처.**

왜 별도 모듈인가 (2026-07-22):
    같은 규칙이 런타임(`camera_thread.roi_at_point`)과 측정 도구(`test/dwell_probe`)에
    **복제**돼 있었고, 후자 주석이 이미 경고하고 있었다 — *"측정 도구가 다른 규칙을 쓰면
    그 수치가 실제 동작을 대표하지 못한다."* 링(1단계)까지 추가하면 복제가 커지므로
    **의존성 없는 순수 모듈로 뽑아 양쪽이 import** 한다. `camera_thread` 는 Qt·Hailo 를
    끌어와 측정 도구가 import 할 수 없어서 여기로 뺐다.

    🔴 **이 규칙을 바꿀 때는 여기만 고친다.** 다른 곳에 같은 판정을 다시 쓰지 말 것.

2단계 구역 (설계 = docs/superpowers/specs/2026-07-22-도넛-2단계-ROI-design.md):

        ┌───────────────────────┐
        │  1단계 (링, ring px)   │  접근 — 체류 타이머 예열 + 경고 표시
        │   ┌───────────────┐   │
        │   │  2단계         │   │  위험 — **여기서만 차단이 발화**한다 (C1)
        │   │  (검출 박스)    │   │
        │   └───────────────┘   │
        └───────────────────────┘

    ROI 는 고정 좌표가 아니라 **YOLO 가 검출한 버튼 박스 그 자체**다(FPV 라 박스가
    버튼을 따라다닌다). 링은 그 박스를 상하좌우로 `ring` 픽셀 넓힌 테두리다.
"""

INSIDE, RING = 2, 1


def zone_at_point(fx, fy, boxes, ring=0):
    """(라벨, 단계) — 2=박스 안 / 1=링 안 / (None, None)=밖.

    boxes = [(라벨, x1, y1, x2, y2), ...]

    규칙:
      · **안쪽이 링을 이긴다** — 한 점이 A의 안쪽이면서 B의 링이면 A로 판정한다.
      · 같은 단계끼리 겹치면 **더 작은(가까운) 박스 우선** — 오판을 줄이는 기존 규칙 유지.
      · `ring=0` 이면 링이 없어 **도넛 도입 전과 완전히 동일**하게 동작한다(롤백 스위치).
    """
    hit_in, area_in = None, None
    hit_ring, area_ring = None, None

    for label, x1, y1, x2, y2 in boxes:
        if x1 <= fx <= x2 and y1 <= fy <= y2:
            area = (x2 - x1) * (y2 - y1)
            if area_in is None or area < area_in:
                hit_in, area_in = label, area
        elif ring > 0 and x1 - ring <= fx <= x2 + ring and y1 - ring <= fy <= y2 + ring:
            area = (x2 - x1 + 2 * ring) * (y2 - y1 + 2 * ring)
            if area_ring is None or area < area_ring:
                hit_ring, area_ring = label, area

    if hit_in is not None:
        return hit_in, INSIDE
    if hit_ring is not None:
        return hit_ring, RING
    return None, None
