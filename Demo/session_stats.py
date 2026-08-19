"""한 번의 작업에서 일어난 일을 모은다 — 작업 완료 결과창의 재료.

정본: 상위 docs/superpowers/specs/2026-08-19-자동진행-결과창-design.md §3

⚠️ Qt 에 의존하지 않는다 — GUI 없이 시험할 수 있어야 한다.
⚠️ 시간을 **인자로 받는다**(`now`). 생략하면 실시간을 쓴다(런타임 편의).
   fsm.py · sub_task.py 와 같은 규약이다.

🔴 오탐지(false positive)를 집계하지 않는다. 오탐 판정에는 정답 라벨이 필요하고
   실시간 데모 중에 그것을 알 방법이 없다 — 숫자를 만들면 근거 없는 수치가 된다.
🔴 검출을 **비율로 만들지 않는다.** "프레임 단위 손 검출률을 성능 지표로 쓰지 말 것
   — 손이 없는 프레임이 분모에 섞여 값이 오염된다"(CLAUDE.md §5). 프레임 수와
   신뢰도 합만 남기고, 나누는 것은 하지 않는다.
"""

import time


def _now(now):
    return time.time() if now is None else now


class SessionStats:
    def __init__(self):
        self.reset()

    def reset(self):
        self._recipe = ""
        self._step_count = 0
        self._started = None
        self._steps = []           # {order, button, name, pressed_at, done_at, sec}
        self._pending = {}         # button -> pressed_at
        self._violations = []
        self._interlocks = []
        self._tools = []           # {button, want, start, grasp_sec, wrong{키:횟수}}
        self._tool_names = {}      # 공구 키 -> 표시명(레시피 sub.tool_names)
        self._frames = 0
        self._dets = {}            # name -> {frames, score_sum, score_frames}

    # ------------------------------------------------------------------ 시작
    def start(self, recipe_name, step_count, now=None):
        self.reset()
        self._recipe = recipe_name
        self._step_count = step_count
        self._started = _now(now)

    @property
    def running(self):
        return self._started is not None

    # ------------------------------------------------------------------ 단계
    def button_pressed(self, button, expected, ok, now=None):
        if ok:
            self._pending[button] = _now(now)

    def step_done(self, order, button, name, now=None):
        t = _now(now)
        pressed = self._pending.pop(button, t)
        self._steps.append({"order": order, "button": button, "name": name,
                            "pressed_at": pressed, "done_at": t,
                            "sec": t - pressed})

    # ------------------------------------------------------------------ 서브
    def sub_started(self, button, spec, now=None):
        """🔴 **공구 서브만** 담는다 — 집계 계약이다.

        공구가 필요 없는 단계(`wait`)까지 담으면 결과창에 「요구 None」 줄이
        찍힌다(2026-08-19 리뷰 C2). 덤으로 `tool_grasped` 가 `self._tools[-1]`
        을 쓰는 구조적 위험도 사라진다 — 공구 없는 단계가 마지막 항목이 되어
        늦게 도착한 공구 결과를 잘못 받아 적는 일이 없어진다.
        """
        spec = spec or {}
        if not spec.get("tool"):
            return
        self._tool_names.update(spec.get("tool_names") or {})
        self._tools.append({"button": button, "want": spec.get("tool"),
                            "_start": _now(now), "grasp_sec": None, "wrong": {}})

    def sub_done(self, button, now=None):
        pass          # 쥔 시각은 tool_grasped 가 이미 기록한다

    def tool_grasped(self, key, ok, now=None):
        if not self._tools:
            return
        cur = self._tools[-1]
        if ok:
            if cur["grasp_sec"] is None:
                cur["grasp_sec"] = _now(now) - cur["_start"]
        elif key:
            # 🔴 **횟수**를 센다 — 종류당 1회만 남기면 세 번 집어도 「1회」로 보인다
            #    (설계 §3.3 은 횟수·종류 둘 다를 요구한다).
            cur["wrong"][key] = cur["wrong"].get(key, 0) + 1

    # ------------------------------------------------------------------ 위반
    def violation(self, expected, actual, level, now=None):
        self._violations.append({"at": _now(now), "expected": expected,
                                 "actual": actual, "level": level})

    def interlock(self, engaged, now=None):
        t = _now(now)
        if engaged:
            self._interlocks.append({"at": t, "released_at": None})
        elif self._interlocks and self._interlocks[-1]["released_at"] is None:
            self._interlocks[-1]["released_at"] = t

    # ------------------------------------------------------------------ 검출
    def frame(self, names):
        """프레임 1장의 검출 목록. names = [(이름, 신뢰도), ...] 또는 [이름, ...]

        🔴 신뢰도가 **None** 이면 점수를 더하지 않고 표본으로도 세지 않는다 —
           점수가 없는 검출(손 like/unlike 판정)에 자리표시자 1.0 을 넣으면
           화면에 「평균 신뢰도 1.00」이라는 근거 없는 수치가 나간다.
        """
        self._frames += 1
        for item in names:
            name, score = item if isinstance(item, (tuple, list)) else (item, 0.0)
            d = self._dets.setdefault(name, {"frames": 0, "score_sum": 0.0,
                                             "score_frames": 0})
            d["frames"] += 1
            if score is not None:
                d["score_sum"] += float(score)
                d["score_frames"] += 1

    # ------------------------------------------------------------------ 마감
    def finish(self, now=None):
        t = _now(now)
        started = self._started if self._started is not None else t
        out = {
            "recipe": self._recipe,
            "started_at": started,
            "finished_at": t,
            "total_sec": t - started,
            "ok": not self._violations,
            "steps": list(self._steps),
            "violations": list(self._violations),
            "interlocks": list(self._interlocks),
            "tools": [{"button": x["button"], "want": x["want"],
                       "grasp_sec": x["grasp_sec"], "wrong": dict(x["wrong"])}
                      for x in self._tools],
            "tool_names": dict(self._tool_names),
            "frames": self._frames,
            "detections": {k: dict(v) for k, v in self._dets.items()},
        }
        # 🔴 완주 후에는 running 을 꺼 집계를 멈춘다. 「작업 시작」을 거치지 않고
        # 다시 PROCESS_RUN 으로 돌아가는 경로(EMO→BLOCK→차단 해제)가 있어, 다음
        # start() 를 안 거치면 이전 작업의 결과에 새 프레임·위반이 계속 더해진다
        # (2026-08-19 코드리뷰). ⚠️ finish() 를 또 부르면 이번엔 _started 가 없어
        # total_sec·started_at 은 "지금"을 기준으로 다시 계산된다 — steps·
        # violations 등 나머지 목록은 그대로다(별도 필드라 안 지워진다).
        self._started = None
        return out
