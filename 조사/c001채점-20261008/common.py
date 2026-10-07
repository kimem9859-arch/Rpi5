"""c001 채점 공통 — 경로 · 설정 20개 · HEF 4개 · 비교 쌍 (설계 = 상위 docs/superpowers/specs/2026-10-08-c001채점-design.md)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RPI5 = HERE.parents[1]
LEARN = RPI5 / "학습"
DEMO = RPI5 / "Demo"
RESULTS = LEARN / "결과"
MODELS = Path.home() / "data" / "학습실험"
STAGE1 = MODELS / "stage" / "place1"                  # 학습 때 데스크톱에 보낸 라벨 사본(설계 §3.4 — 지문 18/20 같음)
PLACE2 = Path.home() / "data" / "label_dataset" / "place2"
C001_MANIFEST = Path.home() / "data" / "label_batches" / "c001" / "manifest.json"
DARK_SESSION = "20261006_191942_장소2_1"                # 어두운 조명 세션(설계 §2.3)
W = Path.home() / "data" / "c001채점"

for _p in (LEARN, DEMO / "test", DEMO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

NAMES = {"button": ["B1", "B2", "B3", "B4", "EMO"], "tool": ["driver", "wrench", "pliers"]}
NAMES8 = ["B1", "B2", "B3", "B4", "EMO", "driver", "wrench", "pliers"]
CONF = 0.65
C001_BOXES = {"B1": 56, "B2": 56, "B3": 55, "B4": 62, "EMO": 48, "driver": 82, "wrench": 88, "pliers": 88}   # 설계 §2.1
KEY_CLASS = {"B1R": "B1", "B2R": "B2", "B3R": "B3", "B4R": "B4", "EMOR": "EMO",
             "dR": "driver", "wR": "wrench", "pR": "pliers"}                                           # ledger.KEYS 이름 → 종류

# (설정, 무리, 결과 폴더 시드 0·1·2, 쓰임) — 설계 §3.1·§3.2
SETTINGS = [
    ("B-full-base", "button", ["E15-button-base", "E15-button-bases1", "E15-button-bases2"], "지금 기준"),
    ("B-early-base", "button", ["E0b-button-s0", "E0b-button-s1", "E0b-button-s2"], "옛 설정"),
    ("B-full-color", "button", ["B-full-color-s0", "B-full-color-s1", "B-full-color-s2"], "후보"),
    ("B-full-noflip", "button", ["B-full-noflip-s0", "B-full-noflip-s1", "B-full-noflip-s2"], "후보"),
    ("B-full-cutmix03", "button", ["B-full-cutmix03-s0", "B-full-cutmix03-s1", "B-full-cutmix03-s2"], "후보"),
    ("B-full-blur", "button", ["B-full-blur-s0", "B-full-blur-s1", "B-full-blur-s2"], "후보"),
    ("T-full-base-albu", "tool", ["E13-tool-base", "E13-tool-bases1", "E13-tool-bases2"], "지금 기준"),
    ("T-full-base", "tool", ["E0c-tool-f120", "E0c-tool-f120s1", "E0c-tool-f120s2"], "판 확인"),
    ("T-early-base", "tool", ["E0b-tool-s0", "E0b-tool-s1", "E0b-tool-s2"], "옛 설정"),
    ("T-full-in1024", "tool", ["E1c-tool-f120in1024", "E1c-tool-f120in1024s1", "E1c-tool-f120in1024s2"], "후보"),
    ("T-full-lr0005", "tool", ["E4c-tool-f120lr0005", "E4c-tool-f120lr0005s1", "E4c-tool-f120lr0005s2"], "후보"),
    ("T-full-in1024lr0005", "tool", ["E7c-tool-f120both", "E7c-tool-f120boths1", "E7c-tool-f120boths2"], "후보"),
    ("T-full-S1t000", "tool", ["E8-tool-T1t000", "E10-tool-t000s1", "E10-tool-t000s2"], "후보"),
    ("T-full-S1t002", "tool", ["E8-tool-T1t002", "E10-tool-t002s1", "E10-tool-t002s2"], "후보"),
    ("T-full-S1t016", "tool", ["E8-tool-T1t016", "E10-tool-t016s1", "E10-tool-t016s2"], "후보"),
    ("T-full-cutmix03", "tool", ["E11-tool-cutmix03", "E11-tool-cutmix03s1", "E11-tool-cutmix03s2"], "후보"),
    ("T-full-sgd", "tool", ["E12-tool-sgd", "E12-tool-sgds1", "E12-tool-sgds2"], "후보"),
    ("T-full-blur", "tool", ["E14-tool-blur", "E14-tool-blurs1", "E14-tool-blurs2"], "후보"),
    ("T-full-half", "tool", ["T-full-half-s0", "T-full-half-s1", "T-full-half-s2"], "후보"),
    ("T-full-b010", "tool", ["T-full-b010-s0", "T-full-b010-s1", "T-full-b010-s2"], "후보"),
]

# (HEF 이름, 파일, 무리, 짝 .pt 결과 폴더, 설정) — 설계 §3.3
HEFS = [
    ("B-full-base-s0_ours-L2", DEMO / "models" / "B-full-base-s0_ours-L2.hef", "button", "E15-button-base", "B-full-base"),
    ("T-full-base-albu-s0_ours-L2", DEMO / "models" / "T-full-base-albu-s0_ours-L2.hef", "tool", "E13-tool-base", "T-full-base-albu"),
    ("B-early-base-s0_ours-L2", MODELS / "E0b-button-s0" / "model.hef", "button", "E0b-button-s0", "B-early-base"),
    ("T-full-base-s0_ours-L2", MODELS / "E0c-tool-f120" / "model.hef", "tool", "E0c-tool-f120", "T-full-base"),
]
DEMO_HEFS = ("B-full-base-s0_ours-L2", "T-full-base-albu-s0_ours-L2")

# (묻는 것, 후보 설정, 기준 설정, 다른 점) — 설계 §5.1~§5.3 · adopt(후보, 기준) 의 「위로 갈림」 = 후보가 낫다
COMPARE = (
    [("Q3", "B-early-base", "B-full-base", "멈춤 · 나눔 · 판 셋이 다름 — 설정 묶음의 차이"),
     ("Q3", "T-early-base", "T-full-base", "멈춤만 다름 — §12.87 「끝까지 학습」 확인"),
     ("판", "T-full-base", "T-full-base-albu", "같은 설정 · 판(A ↔ B)만 다름")]
    + [("Q4", c, "B-full-base", "후보 하나만 바꿈") for c in
       ("B-full-color", "B-full-noflip", "B-full-cutmix03", "B-full-blur")]
    + [("Q4", c, "T-full-base", "후보 하나만 바꿈(판 A)") for c in
       ("T-full-in1024", "T-full-lr0005", "T-full-in1024lr0005", "T-full-S1t000", "T-full-S1t002",
        "T-full-S1t016", "T-full-cutmix03", "T-full-sgd")]
    + [("Q4", c, "T-full-base-albu", "후보 하나만 바꿈(판 B)") for c in ("T-full-blur", "T-full-half", "T-full-b010")]
)
DRAFT_BIASED = {"T-full-in1024"}      # 시드 0 = c001 공구 초벌 모델(설계 §5.3)


def setting(name):
    return next(s for s in SETTINGS if s[0] == name)


def all_ids():
    return [i for s in SETTINGS for i in s[2]]


def group_of_id(rid):
    return next(s[1] for s in SETTINGS if rid in s[2])


def setting_of_id(rid):
    return next(s[0] for s in SETTINGS if rid in s[2])


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p, obj):
    """임시 파일에 쓰고 이름을 바꾼다 — 끊겨도 반쪽 파일이 남지 않는다(Review Focus 2)."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def set_dir(set_name):
    return W / "sets" / set_name


def set_names(set_name):
    return (set_dir(set_name) / "names.txt").read_text(encoding="utf-8").split()
