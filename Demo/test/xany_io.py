"""X-AnyLabeling 라벨 파일(JSON) 쓰기·읽기 · 이름 점검 · YOLO 변환 — 반자동 라벨링의 파일 경계.

정본 설계 = 상위 sop-project docs/superpowers/specs/2026-09-28-반자동라벨링-design.md §3 · §8
형식 = X-AnyLabeling 사용자 가이드의 JSON 구조(shapes[].label/points/shape_type/description/score/difficult).
🔴 클래스 번호는 CLASSES 순서로 고정한다 — 바꾸면 이미 만든 모든 YOLO 라벨의 뜻이 바뀐다.
🔴 이름은 글자 그대로만 받는다 — 대소문자·공백을 고쳐 주지 않는다(틀린 이름을 조용히 다른 클래스로 만들지 않게).
"""
from __future__ import annotations

import json
from pathlib import Path

CLASSES = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]
EXCLUDE = "exclude"
PROPOSAL_PREFIX = "제안_"
DRAFT_VERSION = "sop-draft-1"      # 우리가 쓴 초벌 표시 — X-AnyLabeling 이 다시 저장하면 바뀐다(Task 8 에서 확인)


def shape(label, box, score=None, description=None, difficult=False):
    x1, y1, x2, y2 = [float(v) for v in box]
    return {"label": label, "score": None if score is None else float(score),
            "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], "group_id": None,
            "description": description, "difficult": bool(difficult), "shape_type": "rectangle",
            "flags": {}, "attributes": {}}


def clip_box(box, w, h):
    x1, y1, x2, y2 = [float(v) for v in box]
    return [min(max(x1, 0.0), w), min(max(y1, 0.0), h), min(max(x2, 0.0), w), min(max(y2, 0.0), h)]


def write_json(path, image_name, w, h, shapes, description=None):
    doc = {"version": DRAFT_VERSION, "flags": {}, "shapes": shapes, "imagePath": image_name,
           "imageData": None, "imageHeight": int(h), "imageWidth": int(w), "description": description}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def read_json(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    shapes = []
    for s in doc.get("shapes") or []:
        pts = s.get("points") or []
        if not pts:
            continue
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        shapes.append({"label": s.get("label", ""), "box": [min(xs), min(ys), max(xs), max(ys)],
                       "description": s.get("description"), "score": s.get("score"),
                       "shape_type": s.get("shape_type")})
    return {"version": doc.get("version"), "w": doc.get("imageWidth"), "h": doc.get("imageHeight"),
            "image": doc.get("imagePath"), "checked": bool(doc.get("checked")), "shapes": shapes}


def problems(shapes):
    out = []
    for s in shapes:
        lab = s["label"]
        if lab.startswith(PROPOSAL_PREFIX):
            out.append(f"제안이 남음: {lab!r} — 맞으면 이름에서 「{PROPOSAL_PREFIX}」를 지우고, 아니면 박스를 지운다")
        elif lab != EXCLUDE and lab not in CLASSES:
            out.append(f"모르는 이름: {lab!r}")
        if s.get("shape_type") not in (None, "rectangle"):
            out.append(f"사각형 아님: {s.get('shape_type')!r} ({lab!r})")
    return out


def to_yolo_lines(shapes, w, h):
    """None = exclude 사진(학습에서 뺀다). problems() 를 먼저 통과한 shapes 만 넣는다."""
    if any(s["label"] == EXCLUDE for s in shapes):
        return None
    lines = []
    for s in shapes:
        x1, y1, x2, y2 = clip_box(s["box"], w, h)
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        c = CLASSES.index(s["label"])
        lines.append(f"{c} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
    return lines
