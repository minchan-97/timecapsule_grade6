"""
타임캡슐 — 교실용 편지 앱
편지를 팻말에 걸어두면 나무가 자라고, 마지막 수업에 하나씩 열립니다.
반마다 날짜·코드·편지가 완전히 따로 굴러갑니다.
"""
import base64
import json
import random
import re

import requests
from datetime import date, datetime
from pathlib import Path

import streamlit as st

# ─────────────────────────────────────────────────────────────
# 반 설정 — 여기만 바꾸면 됩니다
#
#   code  : 아이들이 입력하는 코드. 이 코드가 반을 알아서 찾아갑니다.
#           8개가 서로 겹치지 않게 하세요.
#   start : 편지 쓰는 날 (0주차)
#   open  : 마지막 수업 (개봉일)
#   cuts  : 그림이 바뀌는 주차. 생략하면 DEFAULT_CUTS 를 씁니다.
#           예) "6-1": {..., "cuts": (2, 4, 7)}
# ─────────────────────────────────────────────────────────────
DEFAULT_CUTS = (2, 5, 9)   # 0~1주 팻말만 / 2~4주 묘목 / 5~8주 자라는 중 / 9주~ 큰 나무

CLASSES = {
    "5-1": {"name": "5학년 1반", "code": "namu51", "start": date(2026, 9, 1), "open": date(2026, 12, 15)},
    "5-2": {"name": "5학년 2반", "code": "namu52", "start": date(2026, 9, 1), "open": date(2026, 12, 16)},
    "5-3": {"name": "5학년 3반", "code": "namu53", "start": date(2026, 9, 2), "open": date(2026, 12, 17)},
    "5-4": {"name": "5학년 4반", "code": "namu54", "start": date(2026, 9, 2), "open": date(2026, 12, 18)},
    "6-1": {"name": "6학년 1반", "code": "namu61", "start": date(2026, 9, 3), "open": date(2026, 12, 15)},
    "6-2": {"name": "6학년 2반", "code": "namu62", "start": date(2026, 9, 3), "open": date(2026, 12, 16)},
    "6-3": {"name": "6학년 3반", "code": "namu63", "start": date(2026, 9, 4), "open": date(2026, 12, 17)},
    "6-4": {"name": "6학년 4반", "code": "namu64", "start": date(2026, 9, 4), "open": date(2026, 12, 18)},
}

CREDIT = "copyright by-김주아"   # 시작 화면 아래에 작게. 빈 문자열로 두면 안 나옵니다.

TEACHER_PIN = "0000"   # 배포 전에 반드시 바꾸세요. 이 코드로 들어가면 개봉 화면입니다.
MUSIC_FILE  = "music.mp3"

DATA_DIR = Path("data")
STATIC   = Path("static")

BG_FILE     = "base_wide.jpg"   # 시작 화면용 기본 배경
# 학교 나무의 성장 단계별 배경. 학생 화면에서 stage_index(0~3)로 고릅니다.
# 배경 자체가 학교 화단이고, 그 나무가 단계마다 자랍니다.
BG_STAGES   = ["bg_stage0.webp", "bg_stage1.webp",
               "bg_stage2.webp", "bg_stage3.webp"]

# 나무는 배경에서 떼어낸 별도 레이어입니다. 그래야 바람에 흔들 수 있습니다.
# 값은 배경 그림 안에서의 위치(%)로, 원래 그려져 있던 자리 그대로입니다.
# w, h 는 모두 그림판(1400x788) 대비 %입니다.
# 높이를 브라우저의 자동 계산(height:auto)에 맡기면 다른 CSS 에 영향을 받아
# 나무가 뜨거나 눌립니다. 그래서 세로도 직접 지정합니다.
TREES = [
    None,
    {"f": "tree_s.webp", "left": 47.20, "top": 57.91, "w": 5.21,  "h": 15.99, "sway": 1.6, "dur": 4.5},
    {"f": "tree_m.webp", "left": 46.92, "top": 31.80, "w": 19.93, "h": 46.45, "sway": 0.9, "dur": 6.5},
    {"f": "tree_l.webp", "left": 33.54, "top": 19.25, "w": 35.93, "h": 63.07, "sway": 0.6, "dur": 8.0},
]

# ── 번호별 개인 나무 ──────────────────────────────────────────
# 편지를 넣는 순간 그 아이의 나무가 심어지고, 쓴 날부터 자랍니다.
# r = 세로%/가로% (그림 원본 비율). 어디에 놓든 모양이 안 망가집니다.
# 묘목·중간 단계는 모든 종류가 함께 씁니다. 다 자랐을 때만 달라집니다.
TREE_KINDS = {
    "s": {"f": "tree_s.webp", "r": 3.0665, "sway": 1.6, "dur": 4.6},
    "m": {"f": "tree_m.webp", "r": 2.3307, "sway": 1.0, "dur": 6.4},
}

# 다 자란 나무 10종. r = 세로%/가로%.
# 폭은 r 에서 거꾸로 계산하므로, 모양이 달라도 키는 모두 같습니다.
R_REF = 1.7555      # 기본 나무의 비율. 이걸 기준으로 키를 맞춥니다.
TREE_CHOICES = {
    "basic": {"label": "느티나무",     "f": "tree_l.webp",  "r": 1.7555},
    "t1":    {"label": "동글나무",     "f": "tree1_l.webp", "r": 3.5462},
    "t2":    {"label": "수양버들",     "f": "tree2_l.webp", "r": 2.4873},
    "t3":    {"label": "두갈래나무",   "f": "tree3_l.webp", "r": 3.0343},
    "t4":    {"label": "넓은가지나무", "f": "tree4_l.webp", "r": 2.3929},
    "t5":    {"label": "삼단나무",     "f": "tree5_l.webp", "r": 3.7415},
    "t6":    {"label": "삼각나무",     "f": "tree6_l.webp", "r": 3.8559},
    "t7":    {"label": "키다리나무",   "f": "tree7_l.webp", "r": 3.2226},
    "t8":    {"label": "다섯송이나무", "f": "tree8_l.webp", "r": 2.9631},
    "t9":    {"label": "전나무",       "f": "tree9_l.webp", "r": 2.8951},
}
DEFAULT_TREE = "basic"
TREE_CUTS = (3, 8)      # 0~2주 묘목 / 3~7주 자라는 중 / 8주~ 큰 나무
# 나무는 모두 비슷한 크기입니다. 대신 발치의 팻말에 이름이 적힙니다.
TREE_W = 13.0           # 기본 가로 (캔버스 %). r 로 보정해 키를 맞춥니다.
SIGN_W = 3.2            # 이름 팻말 가로
SIGN_R = 2.0198         # 팻말 세로/가로 비율

# ── 나무 돌보기 ───────────────────────────────────────────────
WATER_PER_DAY = 1       # 하루에 줄 수 있는 물
WATER_TO_WEEK = 3       # 물 3번 = 1주 더 자란 효과
WATER_BONUS_MAX = 4     # 물로 앞당길 수 있는 최대 주수
FRUIT_PER_WATER = 2     # 물 2번마다 열매 1개

BG_RATIO = "1200 / 1800"   # 배경 그림 비율. 나무·꽃 좌표가 이 판 위에서 계산됩니다.
STAGE_LABEL = ["아직 아무것도", "묘목", "자라는 중", "큰 나무"]

# 꾸미기 아이템 — sky=하늘에 뜨는 것, ground=땅에 놓는 것
# r = 세로%/가로% (그림 원본 비율에서 나온 값). 세로를 직접 지정하기 위한 값입니다.
ITEMS = {
    "delphinium": {"label": "파란 꽃",  "zone": "ground", "w": 3.0, "r": 3.525},
    "poppy":      {"label": "주황 꽃",  "zone": "ground", "w": 3.6, "r": 1.925},
    "daisy":      {"label": "노란 꽃",  "zone": "ground", "w": 3.0, "r": 2.603},
    "clover":     {"label": "클로버",   "zone": "ground", "w": 2.2, "r": 1.893},
    "grass":      {"label": "풀과 돌",  "zone": "ground", "w": 6.5, "r": 1.332},
    "bush":       {"label": "덤불",     "zone": "ground", "w": 6.5, "r": 1.155},
    "butterfly":  {"label": "나비",     "zone": "sky",    "w": 2.8, "r": 2.520},
    "bird":       {"label": "새",       "zone": "sky",    "w": 3.8, "r": 2.107},
}

MAX_PER_STUDENT = 3   # 한 사람이 놓을 수 있는 개수


# ─────────────────────────────────────────────────────────────
# 반 조회
# ─────────────────────────────────────────────────────────────
def find_class_by_code(code):
    code = code.strip()
    for key, c in CLASSES.items():
        if code and code == c["code"]:
            return key
    return None


def cfg(key):
    return CLASSES[key]


def cuts(key):
    return cfg(key).get("cuts", DEFAULT_CUTS)


# ─────────────────────────────────────────────────────────────
# 저장소
#
# Supabase 가 설정되어 있으면 거기에, 없으면 로컬 파일에 저장합니다.
# Streamlit Community Cloud 는 앱이 잠들거나 재배포되면 파일이 사라지므로
# 실제 수업에서는 반드시 Supabase 를 설정해야 합니다.
#
# .streamlit/secrets.toml (또는 Streamlit Cloud 의 Secrets):
#   SUPABASE_URL = "https://xxxx.supabase.co"
#   SUPABASE_KEY = "eyJ..."
# ─────────────────────────────────────────────────────────────
def normalize_url(raw):
    """붙여넣기 실수를 최대한 흡수해 프로젝트 기본 주소만 남깁니다.

    받아들이는 형태:
      https://abcd.supabase.co
      https://abcd.supabase.co/            (끝 슬래시)
      https://abcd.supabase.co/rest/v1     (Data API 주소를 그대로 붙여넣은 경우)
      https://supabase.com/dashboard/project/abcd   (대시보드 주소)
      abcd.supabase.co                     (https 없음)
    """
    u = (raw or "").strip().strip('"').strip("'")
    if not u:
        return ""
    if "/dashboard/project/" in u:                       # 대시보드 주소
        ref = u.split("/dashboard/project/")[1].split("/")[0].split("?")[0]
        return f"https://{ref}.supabase.co"
    if not u.startswith("http"):
        u = "https://" + u
    u = u.split("?")[0].rstrip("/")
    for tail in ("/rest/v1", "/rest", "/auth/v1", "/storage/v1"):
        if u.endswith(tail):
            u = u[: -len(tail)]
    return u.rstrip("/")


def sb_conf():
    try:
        url = normalize_url(st.secrets["SUPABASE_URL"])
        key = str(st.secrets["SUPABASE_KEY"]).strip().strip('"').strip("'")
    except Exception:
        return None
    if not url or not key:
        return None
    return url, key


def sb_headers():
    _, key = sb_conf()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


class SupabaseError(RuntimeError):
    """상태 코드와 서버 설명을 그대로 담습니다. 원인 파악이 훨씬 빨라집니다."""

    def __init__(self, action, table, status, body):
        self.status, self.body = status, body
        if "PGRST125" in body or "Invalid path" in body:
            hint = ("SUPABASE_URL 이 잘못됐습니다. 프로젝트 기본 주소만 넣으세요. "
                    "예: https://abcd.supabase.co (뒤에 /rest/v1 을 붙이지 마세요)")
        elif "PGRST205" in body or "does not exist" in body:
            hint = f"'{table}' 표가 없습니다. SUPABASE.md 의 SQL 을 실행했는지 확인하세요."
        else:
            hint = {
                401: "키가 틀렸거나 만료됐습니다. service_role 키가 맞는지 확인하세요.",
                403: "권한이 없습니다. anon 키 대신 service_role 키를 쓰세요.",
                404: "주소나 표 이름을 확인하세요.",
                409: "같은 값이 이미 있습니다.",
            }.get(status, "")
        super().__init__(f"[{action} {table}] HTTP {status} {hint}\n{body[:300]}")


def sb_select(table, class_key):
    url, _ = sb_conf()
    r = requests.get(
        f"{url}/rest/v1/{table}",
        headers=sb_headers(),
        params={"class_key": f"eq.{class_key}", "select": "*", "order": "id.asc"},
        timeout=10,
    )
    if r.status_code >= 400:
        raise SupabaseError("읽기", table, r.status_code, r.text)
    return r.json()


def sb_insert(table, row):
    """표에 없는 칸이 있으면 그 칸만 빼고 다시 넣습니다.

    나중에 기능을 더하면서 칸이 늘어나도, SQL 을 미처 실행하지 않은 상태에서
    아이 화면이 멈추지 않게 합니다. 잃는 건 그 칸의 값 하나뿐입니다.
    """
    url, _ = sb_conf()
    payload = dict(row)
    for _ in range(4):
        r = requests.post(
            f"{url}/rest/v1/{table}", headers=sb_headers(), json=payload, timeout=10
        )
        if r.status_code < 400:
            return
        m = re.search(r"Could not find the '(\w+)' column", r.text or "")
        if m and m.group(1) in payload:
            payload.pop(m.group(1))
            continue
        raise SupabaseError("쓰기", table, r.status_code, r.text)
    raise SupabaseError("쓰기", table, r.status_code, r.text)


def sb_check():
    """두 표를 실제로 한 번씩 읽어 보고 결과를 돌려줍니다."""
    out = {}
    for t in ("letters", "garden"):
        try:
            sb_select(t, "__check__")
            out[t] = (True, "정상")
        except SupabaseError as e:
            out[t] = (False, str(e))
        except Exception as e:
            out[t] = (False, f"{type(e).__name__}: {e}")
    return out


# 매 조작마다 서버를 부르지 않도록 잠깐 캐시합니다. 쓰기 직후에는 비웁니다.
@st.cache_data(ttl=15, show_spinner=False)
def _read(table, class_key, _bust=0):
    if sb_conf():
        return sb_select(table, class_key)
    path = DATA_DIR / f"{table}_{class_key}.jsonl"
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _write(table, class_key, row):
    if sb_conf():
        sb_insert(table, dict(row, class_key=class_key))
    else:
        DATA_DIR.mkdir(exist_ok=True)
        with open(DATA_DIR / f"{table}_{class_key}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _read.clear()


TREE_EXPECT = {"tree_s.webp": (73, 126), "tree_m.webp": (279, 366), "tree_l.webp": (503, 497)}
TREE_FILES_EXPECT = [c["f"] for c in TREE_CHOICES.values()]


@st.cache_data(show_spinner=False)
def assets_ok():
    """static 폴더가 app.py 와 같은 세대인지 확인합니다.

    옛 그림 파일이 섞여 있으면 TREES 좌표와 어긋나 나무가 공중에 뜹니다.
    """
    bad = [f"{f} 없음" for f in TREE_FILES_EXPECT if not (STATIC / f).exists()]
    for name, size in TREE_EXPECT.items():
        path = STATIC / name
        if not path.exists():
            bad.append(f"{name} 없음")
            continue
        try:
            from PIL import Image
            got = Image.open(path).size
            if got != size:
                bad.append(f"{name} 크기 {got} (기대 {size})")
        except Exception:
            pass
    return bad


def sb_delete(table, class_key, match):
    url, _ = sb_conf()
    params = {"class_key": f"eq.{class_key}"}
    params.update({k: f"eq.{v}" for k, v in match.items()})
    r = requests.delete(f"{url}/rest/v1/{table}", headers=sb_headers(),
                        params=params, timeout=10)
    if r.status_code >= 400:
        raise SupabaseError("삭제", table, r.status_code, r.text)


def delete_letter(key, number):
    """편지를 정말로 지웁니다. 되돌릴 수 없습니다.

    부적절한 내용을 치우기 위한 기능이라 흔적을 남기지 않습니다.
    지우면 그 번호로 다시 쓸 수 있습니다.
    """
    if sb_conf():
        sb_delete("letters", key, {"number": str(number)})
    else:
        path = DATA_DIR / f"letters_{key}.jsonl"
        if path.exists():
            keep = [l for l in path.read_text(encoding="utf-8").splitlines()
                    if l.strip() and json.loads(l).get("number") != str(number)]
            path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    _read.clear()


def storage_label():
    return "Supabase" if sb_conf() else "로컬 파일(임시)"


# ── 편지 ──────────────────────────────────────────────────────
def load_letters(key, safe=False):
    try:
        return _read("letters", key)
    except Exception:
        if safe:
            return []
        raise


def save_letter(key, record):
    _write("letters", key, record)


def find_letter(key, number):
    for r in load_letters(key):
        if str(r["number"]) == str(number):
            return r
    return None


# ── 농장 꾸미기 — 추가만 하는 기록장(append-only) ──────────────
#
# 지우기는 아이들도 할 수 있지만, 기록이 사라지지는 않습니다.
# 지움도 하나의 기록으로 덧붙습니다. 그래서 언제든 되돌릴 수 있습니다.
def garden_log(key, safe=False):
    try:
        return _read("garden", key)
    except Exception:
        if safe:
            return []
        raise


def garden_append(key, event):
    _write("garden", key, event)


def garden_state(key, log=None, safe=False):
    """기록을 처음부터 재생해서 지금 화면에 보일 것만 남깁니다."""
    placed = {}
    for e in (garden_log(key, safe=safe) if log is None else log):
        if e.get("op") == "add":
            placed[e["event_id"]] = e
        elif e.get("op") == "remove":
            placed.pop(e.get("event_id"), None)
    return list(placed.values())


def care_log(key, number):
    """그 아이의 돌보기 기록만 셉니다. 편지·꾸미기와 같은 기록장을 씁니다."""
    waters, fruits, last = 0, 0, None
    for e in garden_log(key, safe=True):
        if str(e.get("number")) != str(number):
            continue
        if e.get("op") == "water":
            waters += 1
            last = max(last or "", e.get("at", ""))
        elif e.get("op") == "fruit":
            fruits += 1
    return {"waters": waters, "fruits": fruits, "last": last}


def watered_today(key, number):
    last = care_log(key, number)["last"]
    return bool(last) and last[:10] == date.today().isoformat()


def water_bonus_weeks(waters):
    return min(WATER_BONUS_MAX, waters // WATER_TO_WEEK)


def fruits_ready(key, number, kind):
    if kind != "l":
        return 0
    c = care_log(key, number)
    return max(0, c["waters"] // FRUIT_PER_WATER - c["fruits"])


def tree_choices(key):
    """번호별로 마지막에 고른 나무 종류. 기록장에 op="tree" 로 쌓입니다."""
    out = {}
    for e in garden_log(key, safe=True):
        if e.get("op") == "tree" and e.get("item") in TREE_CHOICES:
            out[str(e.get("number"))] = e["item"]
    return out


def set_tree_choice(key, number, choice):
    garden_append(key, {
        "op": "tree", "event_id": f"tree-{number}-{int(datetime.now().timestamp()*1000)}",
        "number": str(number), "item": choice,
        "at": datetime.now().isoformat(timespec="seconds"),
    })


def care_action(key, number, op):
    garden_append(key, {
        "op": op, "event_id": f"{op}-{number}-{int(datetime.now().timestamp()*1000)}",
        "number": number, "at": datetime.now().isoformat(timespec="seconds"),
    })


def garden_place(key, number, item, x, y, flip=False):
    # 같은 밀리초에 두 개를 놓으면 id가 겹쳐 하나가 사라집니다. 난수를 붙입니다.
    eid = f"{number}-{int(datetime.now().timestamp()*1000)}-{random.randrange(1<<24):06x}"
    garden_append(key, {
        "op": "add", "event_id": eid, "number": number, "item": item,
        "x": round(x, 1), "y": round(y, 1), "flip": bool(flip),
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    return eid


def garden_remove(key, eid, by):
    garden_append(key, {
        "op": "remove", "event_id": eid, "by": by,
        "at": datetime.now().isoformat(timespec="seconds"),
    })


def personal_trees(key, me=None):
    """편지 한 통이 나무 한 그루입니다. 별도 저장 없이 편지에서 바로 만듭니다.

    - 자라는 정도는 그 아이가 편지를 쓴 날부터 셉니다.
    - 자리는 번호 순으로 언덕에 고르게 나누고, 번호에서 만든 값으로 조금씩 흩습니다.
    - me 와 같은 번호면 가운데 크게 놓습니다.
    """
    letters = load_letters(key, safe=True)
    if not letters:
        return []

    def num(r):
        try:
            return int(r["number"])
        except (TypeError, ValueError):
            return 0

    letters = sorted(letters, key=num)
    picks = tree_choices(key)

    # 각자 자기 화면에서는 '내 나무' 한 그루만 보입니다.
    # 배경(학교 나무)이 공유 성장이라면, 앞의 내 묘목은 개인 것입니다.
    # me 에 해당하는 편지만 남깁니다. me 가 없으면(교사 미리보기 등) 빈 화면.
    letters = [r for r in letters if me is not None and str(r["number"]) == str(me)]

    n = len(letters)
    out = []
    for i, r in enumerate(letters):
        planted = datetime.fromisoformat(r["written_at"]).date()
        raw = max(0, (date.today() - planted).days // 7)
        bonus = water_bonus_weeks(care_log(key, r["number"])["waters"])
        weeks = raw + bonus
        kind = "l" if weeks >= TREE_CUTS[1] else ("m" if weeks >= TREE_CUTS[0] else "s")
        if kind == "l":
            c = TREE_CHOICES.get(picks.get(str(r["number"]), DEFAULT_TREE), TREE_CHOICES[DEFAULT_TREE])
            k = {"f": c["f"], "r": c["r"], "sway": 0.6, "dur": 8.2}
        else:
            k = TREE_KINDS[kind]

        mine = True   # 이 화면에는 내 나무만 있습니다.

        # 폭은 비율에서 거꾸로 계산합니다. 모양이 달라도 키가 같아집니다.
        fit = R_REF / k["r"]

        # 내 나무는 화면 왼쪽 하단 앞쪽에 고정으로 크게 놓습니다.
        # (배경의 학교 나무와 원근으로 분리되도록 앞·아래·왼쪽)
        x = 22.0                 # 왼쪽
        ground = 84.0            # 아래(앞쪽)
        w = TREE_W * 1.6 * fit   # 개인 나무이므로 크게
        sign_w = SIGN_W * 1.15

        out.append({
            "f": k["f"], "r": k["r"], "sway": k["sway"], "dur": k["dur"],
            "x": round(x, 2), "ground": ground, "w": round(w, 2),
            "sign_w": round(sign_w, 2),
            "mine": mine, "number": r["number"], "nickname": r.get("nickname", ""),
            "weeks": weeks, "raw_weeks": raw, "bonus": bonus, "kind": kind,
            "choice": picks.get(str(r["number"]), DEFAULT_TREE),
        })
    # 내 나무를 마지막에 그려 맨 앞에 오게 합니다
    out.sort(key=lambda t: (t["mine"], t["ground"]))
    return out


def garden_count(key, number):
    return sum(1 for e in garden_state(key) if e["number"] == number)


# ─────────────────────────────────────────────────────────────
# 성장 — 시작일로부터 몇 주가 지났는지로만 결정
# ─────────────────────────────────────────────────────────────
def weeks_elapsed(key):
    return max(0, (date.today() - cfg(key)["start"]).days // 7)


def stage_index(key):
    w = weeks_elapsed(key)
    for i, cut in enumerate(cuts(key)):
        if w < cut:
            return i
    return 3


def days_left(key):
    return max(0, (cfg(key)["open"] - date.today()).days)


@st.cache_data(show_spinner=False)
def asset_url(name):
    """그림을 data URI 로 직접 실어 보냅니다.

    Streamlit 정적 서빙(app/static/...)은 배포 환경에 따라 동작하지 않는
    경우가 있어, 설정에 의존하지 않는 이 방식을 씁니다.
    캐시가 걸려 있어 인코딩은 최초 1회만 일어납니다.
    """
    path = STATIC / name
    if not path.exists():
        return ""
    mime = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[name.rsplit(".", 1)[1]]
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


# ─────────────────────────────────────────────────────────────
# 스타일
# ─────────────────────────────────────────────────────────────
def inject_css(stage_file, intro=False):
    """intro=True 면 아이콘이 먼저 뜨고 배경이 뒤따라 번집니다."""
    bg = asset_url(stage_file)
    bg_anim = "animation: veilOut 2.0s ease-out 1.15s both;" if intro else "opacity: 0; display: none;"
    css = f"""
@import url('https://fonts.googleapis.com/css2?family=Gaegu:wght@400;700&display=swap');
  #MainMenu, footer, header {{visibility: hidden;}}
  .stApp {{background-color: #f3ece2;}}
  [data-testid="stAppViewContainer"],
  [data-testid="stMain"],
  [data-testid="stHeader"],
  [data-testid="stBottomBlockContainer"],
  section.main,
  .main {{background: transparent !important;}}
  /* 시작 화면에서 배경을 잠시 덮었다가 걷히는 막 */
  .stApp::after {{
    content: "";
    position: fixed;
    inset: 0;
    background: #f3ece2;
    pointer-events: none;
    z-index: 0;
    {bg_anim}
  }}
  /* 배경은 맨 뒤, 본문은 그 위. 그리는 순서에만 기대지 않도록 못을 박습니다. */
  .block-container {{position: relative; z-index: 1;}}
  [data-testid="stMain"] {{position: relative; z-index: 1;}}
  @keyframes veilOut {{from {{opacity: 1;}} to {{opacity: 0;}}}}

  /* 시작 화면 아이콘 */
  .icon-wrap {{text-align: center; margin: 0.4rem 0 1.2rem;}}
  .icon-wrap img {{
    width: 190px; max-width: 52vw; height: auto;
    filter: drop-shadow(0 10px 26px rgba(90,70,40,0.22));
    animation: iconIn 1.15s cubic-bezier(.2,.7,.3,1) both;
  }}
  @keyframes iconIn {{
    from {{opacity: 0; transform: scale(0.86) translateY(10px);}}
    to   {{opacity: 1; transform: scale(1) translateY(0);}}
  }}
  .intro-late {{animation: lateIn 1.4s ease-out 1.5s both;}}
  @keyframes lateIn {{from {{opacity: 0;}} to {{opacity: 1;}}}}

  @media (prefers-reduced-motion: reduce) {{
    .stApp::after {{animation: none !important; opacity: 0 !important;}}
    .icon-wrap img, .intro-late {{animation: none !important; opacity: 1 !important;}}
  }}

  .block-container {{max-width: 620px; padding-top: 2.2rem; padding-bottom: 4rem;}}

  html, body, [class*="css"], .stMarkdown, p, div, label, input, textarea {{
    font-family: 'Gaegu', cursive;
    font-weight: 700;
  }}

  .sky-title {{
    font-family: 'Gaegu', cursive; font-size: 2.5rem; font-weight: 700;
    color: #2f4a26; text-align: center; letter-spacing: 0.04em;
    text-shadow: 0 0 10px rgba(255,255,255,1), 0 2px 3px rgba(255,255,255,1);
    margin-bottom: 0.1rem;
  }}
  .sky-sub {{
    text-align: center; color: #3c4a38; font-size: 1.4rem; font-weight: 700;
    text-shadow: 0 0 8px rgba(255,255,255,1), 0 1px 2px rgba(255,255,255,1);
    margin-bottom: 1.6rem;
  }}

  .paper {{
    background: rgba(253, 249, 240, 0.97);
    border: 1px solid rgba(139,111,78,0.28); border-radius: 3px;
    padding: 1.5rem 1.6rem; box-shadow: 0 8px 28px rgba(90,70,40,0.16);
    animation: rise 0.7s ease-out;
  }}
  @keyframes rise {{
    from {{opacity: 0; transform: translateY(14px);}}
    to   {{opacity: 1; transform: translateY(0);}}
  }}
  @media (prefers-reduced-motion: reduce) {{ .paper {{animation: none;}} }}

  .letter-body {{
    font-family: 'Gaegu', cursive; font-size: 1.7rem; line-height: 1.9;
    color: #24211c; font-weight: 700; white-space: pre-wrap; word-break: break-word;
  }}
  .letter-from {{
    font-family: 'Gaegu', cursive; font-size: 1.45rem;
    color: #6b5232; font-weight: 700; text-align: right; margin-top: 1.2rem;
  }}
  .meta {{
    font-size: 1.22rem; color: #5f584e; font-weight: 700;
    border-top: 1px dashed rgba(139,111,78,0.3);
    padding-top: 0.7rem; margin-top: 1.1rem;
  }}
  .badge {{
    display: inline-block; background: rgba(253,249,240,0.9);
    border: 1px solid rgba(139,111,78,0.25); border-radius: 999px;
    padding: 0.4rem 1.1rem; font-size: 1.3rem; color: #2f4a26; font-weight: 700;
    background: rgba(253,249,240,0.96); border-color: rgba(139,111,78,0.45);
  }}
  .center {{text-align: center;}}

  .stButton > button {{
    background: #55703c; color: #fff; border: none; border-radius: 4px; font-weight: 700;
    padding: 0.62rem 1.5rem; font-family: 'Gaegu', cursive;
  }}
  .stButton > button:hover {{background: #43592e; color: #fff;}}
  .stButton > button:focus-visible {{outline: 3px solid #f2c25c; outline-offset: 2px;}}

  .stTextInput input, .stTextArea textarea {{
    background: rgba(253,249,240,0.98); border: 1px solid rgba(139,111,78,0.5);
  }}
  .stTextArea textarea {{font-family: 'Gaegu', cursive; font-size: 1.55rem; line-height: 1.85;}}
  /* Streamlit 기본 글씨 — 크기·굵기·색을 함께 올립니다.
     수채화 배경 위에 바로 얹히므로 흰 테두리 그림자로 시인성을 확보합니다. */
  .stApp, .stMarkdown p, .stMarkdown li,
  label, button, input, textarea, select,
  [data-baseweb="select"], [data-testid="stWidgetLabel"] p,
  [data-testid="stCaptionContainer"] p, [data-testid="stExpander"] summary p {{
    font-family: 'Gaegu', cursive !important;
  }}
  .stApp, .stMarkdown p, .stMarkdown li {{
    font-size: 1.3rem; color: #24211c; font-weight: 700;
  }}
  label, .stRadio label, .stCheckbox label,
  [data-testid="stWidgetLabel"] p {{
    font-size: 1.38rem !important;
    font-weight: 700 !important;
    color: #24211c !important;
    text-shadow: 0 0 7px rgba(255,255,255,1), 0 1px 2px rgba(255,255,255,1);
  }}
  .stRadio [role="radiogroup"] label p,
  .stCheckbox label p {{
    font-size: 1.4rem !important; font-weight: 700 !important; color: #24211c !important;
  }}
  [data-testid="stCaptionContainer"] p,
  .stCaption, small {{
    font-size: 1.2rem !important;
    color: #3f3a33 !important;
    font-weight: 700 !important;
    text-shadow: 0 0 6px rgba(255,255,255,1);
  }}
  .stButton > button {{font-size: 1.35rem; font-weight: 700;}}
  .stTextInput input, .stTextArea textarea {{
    font-size: 1.4rem; color: #24211c; font-weight: 700;
  }}
  .stTextInput input::placeholder, .stTextArea textarea::placeholder {{
    color: #9a9184; font-weight: 400;
  }}
  [data-baseweb="select"] {{font-size: 1.35rem;}}
  [data-baseweb="select"] div {{color: #24211c; font-weight: 700;}}
  [data-testid="stExpander"] summary p {{
    font-size: 1.35rem; font-weight: 700; color: #24211c;
  }}
  [data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"],
  [data-testid="stThumbValue"] {{
    color: #3f3a33 !important; font-weight: 700 !important;
    text-shadow: 0 0 6px rgba(255,255,255,1);
  }}
  /* 농장 배경 — 화면 전체. 세로 그림 양옆은 베이지 파스텔로 채웁니다. */
  .backdrop {{
    position: fixed; top: 0; left: 0;
    width: 100vw; height: 100vh;
    z-index: 0; pointer-events: none; overflow: hidden;
    background: #f3ece2;   /* 세로 그림 좌우 여백 채움 */
  }}
  /* 그림판 — 화면을 덮되 그림 비율을 유지합니다.
     나무와 꽃의 %좌표가 이 판을 기준으로 하므로, 화면 비율이 바뀌어도
     언덕 위에 놓인 것이 하늘로 떠오르지 않습니다. */
  .canvas {{
    position: absolute; top: 50%; left: 50%;
    /* 세로 그림(1200:1800)을 '높이에 맞춰' 온전히 보여 줍니다.
       화면 높이를 꽉 채우고, 폭은 비율대로 따라옵니다.
       가로 화면에서는 그림이 화면보다 좁으므로 좌우에 베이지 여백이 남습니다. */
    transform: translate(-50%, -50%);
    transition: transform 0.5s ease;
    height: 100vh;
    width:  calc(100vh * 1200 / 1800);
    --cw: calc(100vh * 1200 / 1800 / 100);   /* 그림판 가로의 1% */
    background-image: url("{bg}");
    background-size: 100% 100%;
    background-repeat: no-repeat;
  }}
  /* 모바일 주소창 때문에 100vh 가 실제 화면보다 큰 문제를 보정합니다.
     세로 그림을 높이에 맞추는 방식은 그대로 두고 단위만 dvh 로 바꿉니다. */
  @supports (height: 100dvh) {{
    .backdrop {{height: 100dvh;}}
    .canvas {{
      height: 100dvh;
      width:  calc(100dvh * 1200 / 1800);
      --cw: calc(100dvh * 1200 / 1800 / 100);
    }}
  }}
  /* Streamlit 의 전역 img 규칙이 크기를 바꾸지 못하게 막습니다 */
  .canvas img {{
    position: absolute;
    max-width: none !important;
    max-height: none !important;
    min-width: 0 !important;
    min-height: 0 !important;
    object-fit: fill;
  }}
  /* 개인 나무 — 밑동을 땅에 붙이고 그 점을 축으로 흔듭니다 */
  .ptree {{
    transform: translate(-50%, -100%);   /* 애니메이션이 없을 때의 제자리 */
    transform-origin: 50% 100%;
    filter: drop-shadow(0 4px 8px rgba(90,70,40,0.10));
    animation-name: treeSway;
    animation-iteration-count: infinite;
    animation-timing-function: ease-in-out;
  }}
  .ptree.mine {{filter: drop-shadow(0 6px 14px rgba(90,70,40,0.28));}}
  /* 이름 팻말 — 나무 발치에 섭니다 */
  .sign {{
    position: absolute;
    transform: translate(-50%, -100%);
    pointer-events: none;
    filter: drop-shadow(0 2px 4px rgba(90,70,40,0.18));
  }}
  .sign img {{width: 100%; height: 100%; display: block;}}
  .sign span {{
    position: absolute;
    left: 50%; top: 31%;
    transform: translate(-50%, -50%);
    font-family: 'Gaegu', cursive;
    font-weight: 700;
    line-height: 1;
    color: #33261a;
    white-space: nowrap;
    text-shadow: 0 1px 0 rgba(255,248,235,0.6);
  }}
  .sign.mine {{filter: drop-shadow(0 3px 7px rgba(90,70,40,0.3));}}
  .sign.mine span {{color: #2f2519;}}
  /* 흔들었을 때 — 크게 흔들렸다가 잦아듭니다 */
  .ptree.shaking {{
    animation-name: treeShake;
    animation-duration: 1.8s !important;
    animation-iteration-count: 1;
    animation-fill-mode: both;           /* 끝난 뒤에도 제자리를 유지 */
    animation-timing-function: cubic-bezier(.36,.07,.19,.97);
  }}
  @keyframes treeShake {{
    0%   {{transform: translate(-50%, -100%) rotate(0deg);}}
    8%   {{transform: translate(-50%, -100%) rotate(-3.4deg);}}
    22%  {{transform: translate(-50%, -100%) rotate(2.8deg);}}
    38%  {{transform: translate(-50%, -100%) rotate(-2deg);}}
    54%  {{transform: translate(-50%, -100%) rotate(1.3deg);}}
    70%  {{transform: translate(-50%, -100%) rotate(-0.8deg);}}
    85%  {{transform: translate(-50%, -100%) rotate(0.4deg);}}
    100% {{transform: translate(-50%, -100%) rotate(0deg);}}
  }}
  @keyframes treeSway {{
    0%, 100% {{transform: translate(-50%, -100%) rotate(calc(var(--sway) * -1));}}
    50%      {{transform: translate(-50%, -100%) rotate(var(--sway));}}
  }}
  .deco {{
    transform-origin: 50% 100%;
    transform: translate(-50%, -100%) scaleX(var(--fx, 1));
    filter: drop-shadow(0 3px 5px rgba(90,70,40,0.18));
    animation-iteration-count: infinite;
    animation-timing-function: ease-in-out;
  }}
  .deco.swayA {{animation-name: swayA;}}
  .deco.flyA {{
    animation-name: flyA;
    transform-origin: 50% 50%;
    transform: translate(-50%, -50%) scaleX(var(--fx, 1));
  }}
  /* --fx 가 -1 이면 좌우로 뒤집힙니다 (나비·새가 반대편을 보게) */
  @keyframes swayA {{
    0%, 100% {{transform: translate(-50%, -100%) scaleX(var(--fx, 1)) rotate(-2.2deg);}}
    50%      {{transform: translate(-50%, -100%) scaleX(var(--fx, 1)) rotate(2.2deg);}}
  }}
  @keyframes flyA {{
    0%, 100% {{transform: translate(-50%, -50%) translate(0, 0) scaleX(var(--fx, 1)) rotate(-3deg);}}
    50%      {{transform: translate(-50%, -50%) translate(16px, -12px) scaleX(var(--fx, 1)) rotate(3deg);}}
  }}
  .ghost {{opacity: 0.55;}}
  .credit {{
    text-align: center;
    font-size: 1.4rem;
    letter-spacing: 0.02em;
    color: #111111;
    font-weight: 700;
    text-shadow: 0 0 8px rgba(255,255,255,1), 0 1px 2px rgba(255,255,255,1);
    margin-top: 2.2rem;
  }}
  /* 돌보기 반응 — 물방울, 낙엽, 열매 */
  .drop, .leaf, .fruit {{position: absolute; pointer-events: none;}}
  .drop {{
    width: 0.55%; height: 1.6%;
    background: rgba(120,180,225,0.85);
    border-radius: 50% 50% 60% 60%;
    animation: dropFall 1.5s ease-in forwards;
  }}
  @keyframes dropFall {{
    0%   {{opacity: 0; transform: translateY(0) scaleY(0.6);}}
    15%  {{opacity: 1;}}
    100% {{opacity: 0; transform: translateY(var(--fall)) scaleY(1.3);}}
  }}
  .leaf {{
    border-radius: 50% 0 50% 0;
    opacity: 0.92;
    animation-name: leafFall;
    animation-timing-function: cubic-bezier(.35,.05,.6,1);
    animation-fill-mode: forwards;
  }}
  @keyframes leafFall {{
    0%   {{opacity: 0; transform: translate(0, 0) rotate(0deg);}}
    10%  {{opacity: 0.95;}}
    45%  {{transform: translate(calc(var(--drift) * 0.6), calc(var(--fall) * 0.45))
                      rotate(calc(var(--spin) * 0.5));}}
    100% {{opacity: 0;
           transform: translate(var(--drift), var(--fall)) rotate(var(--spin));}}
  }}
  .fruit {{
    width: 1.1%; height: 2%;
    background: radial-gradient(circle at 35% 30%, #f6a15a, #d9533a);
    border-radius: 50%;
    box-shadow: 0 1px 3px rgba(90,50,30,0.3);
    animation: fruitBob 3.4s ease-in-out infinite;
  }}
  @keyframes fruitBob {{
    0%, 100% {{transform: translateY(0);}}
    50%      {{transform: translateY(0.6%);}}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .fruit, .leaf, .drop, .ptree.shaking {{animation: none !important;}}
    .leaf, .drop {{display: none;}}
  }}
  /* 정렬 확인용 — 판의 테두리와 언덕선(82.3%) 을 그려 봅니다 */
  .canvas.guide {{outline: 3px dashed rgba(220,60,60,0.9); outline-offset: -3px;}}
  .canvas.guide::after {{
    content: ""; position: absolute; left: 0; right: 0; top: 82.3%;
    border-top: 2px solid rgba(220,60,60,0.9);
  }}
  @media (prefers-reduced-motion: reduce) {{
    .canvas {{transition: none;}}
    .deco {{animation: none !important;
            transform: translate(-50%, -100%) scaleX(var(--fx, 1)) !important;}}
    .deco.flyA {{transform: translate(-50%, -50%) scaleX(var(--fx, 1)) !important;}}
    .ptree {{animation: none !important; transform: translate(-50%, -100%) !important;}}
  }}
"""
    # 빈 줄이 하나라도 있으면 Streamlit 마크다운이 HTML 블록을 끊어버려
    # 나머지 CSS가 화면에 글자로 찍힙니다. 반드시 전부 제거합니다.
    css = "".join(line.strip() + " " for line in css.splitlines() if line.strip())
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def play_music():
    """음악을 자동 재생하고 재생기는 화면에서 감춥니다.

    브라우저는 사용자가 한 번이라도 클릭한 뒤에야 소리를 허용합니다.
    시작 화면에서 '들어가기'를 누르는 순간 그 조건이 충족되므로,
    그 이후 화면에서는 자동 재생이 걸립니다.
    시작 화면에는 음악을 넣지 않습니다.
    """
    music = STATIC / MUSIC_FILE
    if not music.exists():
        return
    st.markdown(
        '<style>[data-testid="stAudio"]{position:absolute;width:1px;height:1px;'
        'opacity:0;pointer-events:none;}</style>',
        unsafe_allow_html=True,
    )
    try:
        st.audio(str(music), loop=True, autoplay=True)
    except TypeError:
        st.audio(str(music))   # 구버전 Streamlit


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_backdrop(key, extra=None, stage=None, guide=False):
    """화면 전체를 그 반의 농장으로 만듭니다.

    배경 그림(나무 없음) 위에 나무 레이어와 꾸민 것들을 얹습니다.
    나무를 따로 떼어냈기 때문에 바람에 흔들 수 있습니다.
    """
    layers = []

    # 번호별 개인 나무. 편지 한 통이 나무 한 그루입니다.
    me = st.session_state.get("_me")
    # 방금 누른 동작은 나무를 그리기 "전에" 알아야 흔들림을 걸 수 있습니다.
    fx_now = st.session_state.pop("_fx", None)
    shaking = fx_now == "shake"
    for t in personal_trees(key, me=me):
        h = t["w"] * t["r"]
        cls = "ptree mine" if t["mine"] else "ptree"
        if t["mine"] and shaking:
            cls += " shaking"
        layers.append((
            t["ground"],
            f'<img class="{cls}" src="{asset_url(t["f"])}" '
            f'style="left:{t["x"]}%;top:{t["ground"]}%;'
            f'width:{t["w"]}%;height:{h:.2f}%;'
            f'--sway:{t["sway"]}deg;animation-duration:{t["dur"]}s;" '
            f'alt="{esc(str(t["number"]))}번 나무">'
        ))

        # 발치의 이름 팻말. 나무보다 아주 조금 앞에 옵니다.
        name = (t["nickname"] or str(t["number"]))[:5]
        sw = t["sign_w"]
        sh = sw * SIGN_R
        layers.append((
            500 + t["ground"],   # 이름은 가리면 소용없으므로 항상 맨 앞
            f'<div class="sign{" mine" if t["mine"] else ""}" '
            f'style="left:{t["x"] + t["w"] * 0.34:.2f}%;top:{t["ground"]:.2f}%;'
            f'width:{sw:.2f}%;height:{sh:.2f}%;">'
            f'<img src="{asset_url("sign.webp")}" alt="">'
            f'<span style="font-size:calc({sw * 0.42:.2f} * var(--cw));">{esc(name)}</span>'
            f'</div>'
        ))

    items = garden_state(key, safe=True)
    if extra:
        items = items + [extra]
    for i, e in enumerate(items):
        meta = ITEMS.get(e["item"])
        if not meta:
            continue
        scale = 0.75 + (e["y"] / 100) * 0.55          # 아래쪽일수록 가깝게 = 크게
        w = meta["w"] * scale
        cls = "flyA" if meta["zone"] == "sky" else "swayA"
        ghost = " ghost" if e.get("event_id") == "_preview" else ""
        fx = -1 if e.get("flip") else 1          # 좌우 뒤집기
        # 미리보기는 항상 맨 앞. 나머지는 아래쪽에 있을수록 앞에 옵니다.
        depth_key = 999 if ghost else e["y"]
        layers.append((
            depth_key,
            f'<img class="deco {cls}{ghost}" src="{asset_url("items/" + e["item"] + ".webp")}" '
            f'style="left:{e["x"]}%;top:{e["y"]}%;'
            f'width:{w:.2f}%;height:{w * meta["r"]:.2f}%;--fx:{fx};'
            f'animation-duration:{3.2 + (i % 5) * 0.7:.1f}s;'
            f'animation-delay:{(i % 7) * 0.4:.1f}s;" alt="">'
        ))

    # 방금 한 동작에 대한 반응(물방울 / 낙엽). 한 번 보여 주고 사라집니다.
    my = [t for t in personal_trees(key, me=me) if t["mine"]] if me else []
    if my:
        t = my[0]
        top = t["ground"] - t["w"] * t["r"]
        if fx_now == "water":
            for j in range(9):
                layers.append((
                    1000,
                    f'<div class="drop" style="left:{t["x"] - 6 + j * 1.5:.1f}%;'
                    f'top:{top - 3:.1f}%;--fall:{t["ground"] - top + 3:.1f}%;'
                    f'animation-delay:{j * 0.12:.2f}s;"></div>'
                ))
        elif fx_now == "shake":
            span = t["w"] * 0.9
            for j in range(16):
                g = (j * 47 % 100) / 100          # 잎마다 다른 고정값
                h = (j * 71 % 100) / 100
                drift = (g - 0.5) * 2 * (6 + h * 8)          # 좌우로 흩날리는 폭
                size = 0.7 + h * 0.7
                shade = ("#8fae5c", "#7a9b4e", "#a3bd6e", "#6f8f45")[j % 4]
                layers.append((
                    1000,
                    f'<div class="leaf" style="'
                    f'left:{t["x"] - span / 2 + span * g:.1f}%;'
                    f'top:{top + (t["ground"] - top) * (0.1 + 0.45 * h):.1f}%;'
                    f'width:{size:.2f}%;height:{size * 1.5:.2f}%;background:{shade};'
                    f'--fall:{t["ground"] - top - (t["ground"] - top) * (0.1 + 0.45 * h):.1f}%;'
                    f'--drift:{drift:.1f}vw;--spin:{300 + g * 420:.0f}deg;'
                    f'animation-duration:{2.0 + h * 1.6:.1f}s;'
                    f'animation-delay:{j * 0.055:.2f}s;"></div>'
                ))

        # 열매 — 다 자란 내 나무에만 맺힙니다
        for j in range(min(fruits_ready(key, me, t["kind"]), 8)):
            gx, gy = (j * 37 % 100) / 100, (j * 53 % 100) / 100
            layers.append((
                1000,
                f'<div class="fruit" style="'
                f'left:{t["x"] - t["w"] * 0.3 + t["w"] * 0.6 * gx:.1f}%;'
                f'top:{top + (t["ground"] - top) * (0.2 + 0.4 * gy):.1f}%;'
                f'animation-delay:{j * 0.3:.1f}s;"></div>'
            ))

    cls = "canvas guide" if guide else "canvas"
    html = "".join(h for _, h in sorted(layers, key=lambda p: p[0]))

    # 세로(폰) 고정 레이아웃에서는 그림판이 항상 화면 높이에 맞춰 가운데 옵니다.
    # 좌우로 밀 필요가 없으므로 shift 를 쓰지 않습니다.
    shift = ""

    st.markdown(
        f'<div class="backdrop"><div class="{cls}"{shift}>{html}</div></div>',
        unsafe_allow_html=True,
    )
    return items


def printable_html(key, letters):
    """서버가 사라져도 남는 사본. 브라우저에서 열어 PDF로 인쇄하세요."""
    c = cfg(key)
    parts = []
    for r in sorted(letters, key=lambda x: int(x["number"])):
        w = datetime.fromisoformat(r["written_at"]).date()
        parts.append(
            f"<article><h2>{r['number']}번 {esc(r['nickname'])}</h2>"
            f"<p>{esc(r['body'])}</p>"
            f"<small>{w.year}. {w.month}. {w.day}</small></article>"
        )
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>타임캡슐 — {c['name']}</title>
<style>
 @import url('https://fonts.googleapis.com/css2?family=Gaegu:wght@400;700&display=swap');
 body{{font-family:'Gaegu',sans-serif;font-size:1.15rem;max-width:640px;margin:3rem auto;padding:0 1.5rem;color:#24211c;}}
 h1{{font-size:1.6rem;border-bottom:2px solid #7d9b5e;padding-bottom:.6rem;}}
 article{{page-break-inside:avoid;margin:2.4rem 0;border-left:3px solid #d8ddc9;padding-left:1.2rem;}}
 h2{{font-size:1.1rem;color:#5c6b4f;margin-bottom:.6rem;}}
 p{{white-space:pre-wrap;line-height:1.9;}}
 small{{color:#999;}}
</style>
<h1>타임캡슐 — {c['name']}</h1>
<p>{c['start']} 에 맡기고 {c['open']} 에 열었습니다. 모두 {len(letters)}통.</p>
{''.join(parts)}
</html>"""


# ─────────────────────────────────────────────────────────────
# 화면 1 — 편지 쓰기
# ─────────────────────────────────────────────────────────────
def page_write(key):
    c = cfg(key)
    st.markdown('<div class="sky-title">타임캡슐</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sky-sub">{c["name"]} · {c["open"].month}월 {c["open"].day}일에 열립니다</div>',
        unsafe_allow_html=True,
    )

    if date.today() > c["open"]:
        st.markdown('<div class="paper center">편지 쓰는 기간이 끝났어요.</div>', unsafe_allow_html=True)
        return

    number = st.text_input("번호", max_chars=2, placeholder="예: 7", key=f"w_num_{key}")
    if number.strip().isdigit():
        st.session_state["_me"] = number.strip()
    nickname = st.text_input("이름 또는 별명", max_chars=12, placeholder="편지 아래에 적힐 이름", key=f"w_nick_{key}")
    body = st.text_area(
        "그날의 나에게",
        height=260, max_chars=1200,
        placeholder="지금 무슨 생각을 하고 있는지, 그때는 어떤 사람이 되어 있길 바라는지 써 보세요.",
        key=f"w_body_{key}",
    )

    st.caption("한 번 넣으면 개봉일까지 열 수 없어요. 선생님은 관리를 위해 내용을 볼 수 있습니다.")

    if st.button("팻말에 걸기", key=f"w_btn_{key}"):
        num = number.strip()
        if not num.isdigit():
            st.error("번호는 숫자로 적어 주세요.")
            return
        if not nickname.strip():
            st.error("이름 또는 별명을 적어 주세요.")
            return
        if len(body.strip()) < 20:
            st.error("편지가 너무 짧아요. 20자 이상 써 주세요.")
            return
        if find_letter(key, num):
            st.error(f"{num}번은 이미 편지를 넣었어요. '내 나무 보기'에서 확인할 수 있어요.")
            return

        try:
            save_letter(key, {
                "number": num,
                "nickname": nickname.strip(),
                "body": body.strip(),
                "written_at": datetime.now().isoformat(timespec="seconds"),
            })
        except Exception as err:
            # 조용히 실패하면 아이는 저장된 줄 압니다. 반드시 알려야 합니다.
            st.error("편지를 넣지 못했어요. 아래 내용을 복사해 두고 선생님께 알려 주세요.")
            st.exception(err)
            return
        st.session_state.just_saved = num
        st.rerun()


# ─────────────────────────────────────────────────────────────
# 화면 2 — 내 나무 보기
# ─────────────────────────────────────────────────────────────
def page_tree(key):
    """우리 농장 — 꽃을 골라 놓고, 자기가 놓은 것은 치울 수 있습니다.

    번호는 마지막에 받습니다. 먼저 고르고 움직여 보게 해야
    화면이 비어 보이지 않습니다.
    """
    c = cfg(key)
    st.markdown('<div class="sky-title">나무 키우기</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sky-sub">{c["name"]} · {weeks_elapsed(key)}주차 · '
        f'{STAGE_LABEL[stage_index(key)]} · 개봉까지 {days_left(key)}일</div>',
        unsafe_allow_html=True,
    )

    names = list(ITEMS.keys())
    labels = [ITEMS[i]["label"] for i in names]
    picked = st.selectbox("무엇을 놓을까요", labels, key=f"g_sel_{key}")
    item = names[labels.index(picked)]

    # 슬라이더가 돌려주는 값을 그대로 씁니다.
    # session_state 를 다시 읽으면 위젯이 아직 등록되기 전 순간에 KeyError 가 납니다.
    zone = ITEMS[item]["zone"]
    x = st.slider("왼쪽 ↔ 오른쪽", 5, 95, 50, key=f"g_x_{key}")
    if zone == "ground":
        y = st.slider("뒤쪽 ↔ 앞쪽", 68, 96, 82, key=f"g_y_{key}")
    else:
        y = st.slider("낮게 ↔ 높게", 20, 60, 42, key=f"g_yk_{key}")

    flip = st.checkbox("좌우 뒤집기", key=f"g_flip_{key}",
                       help="나비나 새가 반대편을 보게 합니다.")
    st.caption("움직이면 화면 뒤에 흐리게 미리 보입니다.")

    number = st.text_input("번호", max_chars=2, placeholder="예: 7", key=f"t_num_{key}").strip()

    # 배경에 흐리게 얹을 미리보기
    st.session_state["_preview"] = {
        "event_id": "_preview", "number": number or "0", "item": item,
        "x": x, "y": y, "flip": flip,
    }
    if number.isdigit():
        st.session_state["_me"] = number      # 내 나무를 가운데 크게 그리기 위해

    if st.button("여기에 놓기", key=f"g_put_{key}"):
        if not number.isdigit():
            st.error("번호를 넣어 주세요.")
        elif garden_count(key, number) >= MAX_PER_STUDENT:
            st.error(f"한 사람이 {MAX_PER_STUDENT}개까지 놓을 수 있어요. 하나를 치우면 다시 놓을 수 있어요.")
        else:
            try:
                garden_place(key, number, item, x, y, flip)
            except Exception as err:
                st.error("놓지 못했어요. 잠시 뒤에 다시 해 보세요.")
                st.exception(err)
                return
            st.rerun()

    if number.isdigit():
        my = [t for t in personal_trees(key, me=number) if t["mine"]]
        if my:
            t = my[0]
            label = {"s": "묘목", "m": "자라는 중", "l": "큰 나무"}[t["kind"]]
            care = care_log(key, number)
            extra = f" · 물로 +{t['bonus']}주" if t["bonus"] else ""
            st.markdown(
                f'<div class="center" style="margin:0.6rem 0;"><span class="badge">'
                f'{esc(t["nickname"] or number)}의 나무 · {label} · 심은 지 {t["raw_weeks"]}주{extra}</span></div>',
                unsafe_allow_html=True,
            )

            # 나무 종류 고르기
            ids = list(TREE_CHOICES.keys())
            labels = [TREE_CHOICES[i]["label"] for i in ids]
            cur = t["choice"] if t["choice"] in ids else DEFAULT_TREE
            pick = st.selectbox("나무 종류", labels, index=ids.index(cur),
                                key=f"tree_sel_{key}_{number}")
            chosen = ids[labels.index(pick)]
            if chosen != cur:
                set_tree_choice(key, number, chosen)
                st.rerun()
            if t["kind"] != "l":
                st.caption("고른 모습은 다 자랐을 때 나타나요. 지금은 모두 같은 묘목이에요.")

            ready = fruits_ready(key, number, t["kind"])
            b1, b2, b3 = st.columns(3)
            with b1:
                done = watered_today(key, number)
                if st.button("물 주기" if not done else "오늘 다 줬어요",
                             key=f"care_w_{key}", disabled=done, use_container_width=True):
                    care_action(key, number, "water")
                    st.session_state["_fx"] = "water"
                    st.rerun()
            with b2:
                if st.button("흔들기", key=f"care_s_{key}", use_container_width=True):
                    st.session_state["_fx"] = "shake"
                    st.rerun()
            with b3:
                if st.button(f"열매 따기 ({ready})", key=f"care_f_{key}",
                             disabled=ready == 0, use_container_width=True):
                    care_action(key, number, "fruit")
                    st.rerun()

            msg = f"물 {care['waters']}번 · 딴 열매 {care['fruits']}개"
            if t["kind"] != "l":
                msg += f" · 물 {WATER_TO_WEEK}번마다 1주씩 빨리 자라요"
            st.caption(msg)
        else:
            st.caption("편지를 넣으면 내 나무가 심어져요.")

        mine = [e for e in garden_state(key, safe=True) if str(e["number"]) == number]
        st.markdown(f"**내가 놓은 것** — {len(mine)}/{MAX_PER_STUDENT}개")
        for e in mine:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f'<span class="badge">{ITEMS[e["item"]]["label"]}</span>',
                            unsafe_allow_html=True)
            with col2:
                if st.button("치우기", key=f"g_del_{e['event_id']}"):
                    garden_remove(key, e["event_id"], by=number)
                    st.rerun()
        if mine:
            st.caption("치워도 기록은 남아서 선생님이 되돌릴 수 있어요.")

        rec = find_letter(key, number)
        if rec:
            written = datetime.fromisoformat(rec["written_at"]).date()
            st.markdown(
                f'<div class="center" style="margin-top:1rem;"><span class="badge">'
                f'{esc(rec["nickname"])}의 편지는 잘 있어요 · {(date.today()-written).days}일째'
                f'</span></div>',
                unsafe_allow_html=True,
            )

    st.markdown(
        f'<div class="center" style="margin-top:1.2rem;"><span class="badge">'
        f'{c["name"]} 편지 {len(load_letters(key, safe=True))}통 · '
        f'꾸민 것 {len(garden_state(key, safe=True))}개</span></div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────
# 화면 3 — 개봉 (교사용)
# ─────────────────────────────────────────────────────────────
def page_open():
    # 반 고르기를 드롭다운이 아니라 별도 화면의 버튼으로 둡니다.
    # 화면에서 놓칠 일이 없고, 수업 중에 누르기도 쉽습니다.
    key = st.session_state.get("open_key")

    if not key:
        st.markdown('<div class="sky-title">어느 반을 열까요</div>', unsafe_allow_html=True)

        if not sb_conf():
            st.warning(
                "지금은 임시 저장(로컬 파일)입니다. 앱이 잠들거나 재배포되면 "
                "편지와 꾸민 것이 모두 사라집니다. Supabase 를 설정해 주세요."
            )
        else:
            bad = {t: m for t, (ok, m) in sb_check().items() if not ok}
            if bad:
                st.error("Supabase 연결에 문제가 있습니다.")
                for t, m in bad.items():
                    st.code(m, language=None)
                st.caption(f"실제로 부른 주소: `{sb_conf()[0]}/rest/v1/letters`")
            else:
                st.caption(f"Supabase 연결 정상 · {sb_conf()[0]}")

        stale = assets_ok()
        if stale:
            st.error("static 폴더가 옛 버전입니다. 나무 위치가 어긋납니다.")
            st.code("\n".join(stale), language=None)

        ks = list(CLASSES.keys())
        for row in range(0, len(ks), 2):
            cols = st.columns(2)
            for col, k in zip(cols, ks[row:row + 2]):
                with col:
                    n = len(load_letters(k, safe=True))
                    if st.button(f"{CLASSES[k]['name']}  ({n}통)", key=f"pick_{k}",
                                 use_container_width=True):
                        st.session_state.open_key = k
                        st.session_state.pop("order", None)
                        st.session_state.idx = -1
                        st.rerun()
        return

    c = cfg(key)

    # 배경은 반드시 위젯보다 "먼저" 그려야 합니다.
    # position:fixed 라 나중에 그리면 앞선 위젯들을 덮어 가려 버립니다.
    # 교사가 편지를 열고 있으면 그 학생 번호(_open_me, 편지 넘길 때 저장됨)의
    # 나무를 띄웁니다. 편지 열기 전에는 나무가 없습니다.
    _open_me = st.session_state.get("_open_me")
    if _open_me:
        st.session_state["_me"] = str(_open_me)
    else:
        st.session_state.pop("_me", None)
    render_backdrop(key, stage=3, guide=st.session_state.get("guide_on", False))

    top1, top2 = st.columns([1, 1])
    with top1:
        if st.button("← 다른 반", key="back_class", use_container_width=True):
            st.session_state.pop("open_key", None)
            st.session_state.pop("order", None)
            st.session_state.pop("_open_me", None)
            st.session_state.idx = -1
            st.rerun()
    with top2:
        st.markdown(f'<div style="padding-top:0.5rem;"><span class="badge">{c["name"]}</span></div>',
                    unsafe_allow_html=True)

    st.checkbox("정렬 확인", key="guide_on",
                help="빨간 테두리는 그림판, 빨간 가로선은 언덕선입니다. "
                     "선이 언덕 위에 놓이고 나무 밑동이 그 선에 닿으면 정상입니다.")

    try:
        letters = load_letters(key)
    except SupabaseError as err:
        st.error("편지를 불러오지 못했습니다.")
        st.code(str(err), language=None)
        return
    if not letters:
        st.markdown(f'<div class="paper center">{c["name"]}은 아직 편지가 없어요.</div>', unsafe_allow_html=True)
        return

    if "order" not in st.session_state:
        order = list(range(len(letters)))
        random.shuffle(order)
        st.session_state.order = order

    order = st.session_state.order
    idx = st.session_state.get("idx", -1)

    play_music()

    if idx < 0:
        st.session_state.pop("_open_me", None)   # 편지 열기 전에는 나무 없음
        st.markdown('<div class="sky-title">타임캡슐이 열립니다</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="sky-sub">{c["name"]} · {len(letters)}그루 · {len(letters)}통의 편지</div>',
            unsafe_allow_html=True,
        )
        if st.button("첫 번째 편지 열기"):
            st.session_state.idx = 0
            st.rerun()
        st.download_button(
            "인쇄용으로 내려받기",
            data=printable_html(key, letters),
            file_name=f"타임캡슐_{c['name']}_{c['open']}.html",
            mime="text/html",
        )

        # 치운 것 되돌리기 — 기록이 전부 남아 있어 복구할 수 있습니다
        removed = [e for e in garden_log(key) if e.get("op") == "remove"]
        if removed:
            with st.expander(f"치워진 것 되돌리기 ({len(removed)}개 기록)"):
                state_ids = {e["event_id"] for e in garden_state(key)}
                adds = {e["event_id"]: e for e in garden_log(key) if e.get("op") == "add"}
                seen = set()
                for r in reversed(removed[-30:]):
                    a = adds.get(r["event_id"])
                    if not a or a["event_id"] in state_ids or a["event_id"] in seen:
                        continue
                    seen.add(a["event_id"])
                    lbl = ITEMS.get(a["item"], {}).get("label", a["item"])
                    if st.button(f"{a['number']}번의 {lbl} 되돌리기", key=f"undo_{r['event_id']}"):
                        garden_append(key, {k2: v for k2, v in a.items()
                                            if k2 in ("op", "event_id", "number", "item", "x", "y")}
                                      | {"at": datetime.now().isoformat(timespec="seconds")})
                        st.rerun()

        # ── 관리 · 지우기 ────────────────────────────────────
        with st.expander("관리 · 지우기"):
            st.caption("부적절한 내용을 치울 때만 쓰세요. 편지는 되돌릴 수 없습니다.")

            st.markdown("**편지**")
            armed = st.checkbox("편지 지우기 켜기", key="del_arm")
            for r in sorted(letters,
                            key=lambda x: int(x["number"]) if str(x["number"]).isdigit() else 0):
                head = r["body"].strip().replace("\n", " ")[:26]
                cc1, cc2 = st.columns([4, 1])
                with cc1:
                    st.markdown(
                        f'<span class="badge">{r["number"]}번 {esc(r["nickname"])}</span>'
                        f'<span style="font-size:0.95rem;color:#7a7266;"> {esc(head)}…</span>',
                        unsafe_allow_html=True,
                    )
                with cc2:
                    if st.button("지우기", key=f"delL_{r['number']}",
                                 disabled=not armed, use_container_width=True):
                        delete_letter(key, r["number"])
                        st.rerun()

            placed = garden_state(key)
            if placed:
                st.markdown("**꾸민 것**")
                st.caption("이건 기록이 남아서 위에서 되돌릴 수 있습니다.")
                for e in placed:
                    lbl = ITEMS.get(e["item"], {}).get("label", e["item"])
                    dc1, dc2 = st.columns([4, 1])
                    with dc1:
                        st.markdown(f'<span class="badge">{e["number"]}번 · {lbl}</span>',
                                    unsafe_allow_html=True)
                    with dc2:
                        if st.button("치우기", key=f"delG_{e['event_id']}",
                                     use_container_width=True):
                            garden_remove(key, e["event_id"], by="교사")
                            st.rerun()
        return

    if idx >= len(order):
        st.markdown('<div class="sky-title">여기까지</div>', unsafe_allow_html=True)
        st.markdown('<div class="paper center letter-body">모두 잘 자랐습니다.</div>', unsafe_allow_html=True)
        return

    rec = letters[order[idx]]
    # 지금 열려 있는 편지의 학생 번호를 저장 → 배경이 그 학생 나무를 띄웁니다.
    st.session_state["_open_me"] = str(rec["number"])
    written = datetime.fromisoformat(rec["written_at"]).date()
    st.markdown(f'<div class="sky-sub">{idx+1} / {len(order)}</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
<div class="paper">
  <div class="letter-body">{esc(rec['body'])}</div>
  <div class="letter-from">— {esc(rec['nickname'])}</div>
  <div class="meta">{written.year}. {written.month}. {written.day}에 쓴 편지</div>
</div>
""",
        unsafe_allow_html=True,
    )

    if st.button("다음 편지" if idx + 1 < len(order) else "마치기"):
        st.session_state.idx = idx + 1
        st.rerun()


# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title="타임캡슐", page_icon="🌳", layout="centered")

    key = st.session_state.get("cls")
    teacher = st.session_state.get("teacher", False)

    at_start = not key and not teacher

    # 반이 정해지면(학생=key, 교사=open_key) 그 반의 성장 단계 배경을 씁니다.
    # 시작 화면만 기본 배경.
    bg_key = key or (st.session_state.get("open_key") if teacher else None)
    if bg_key:
        bg_now = BG_STAGES[stage_index(bg_key)]
    else:
        bg_now = BG_FILE
    inject_css(bg_now, intro=at_start)

    # 시작 화면 — 아이콘이 먼저 뜨고 배경이 뒤따릅니다
    if at_start:
        st.markdown(
            f'<div class="icon-wrap"><img src="{asset_url("icon.webp")}" alt=""></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="sky-title intro-late">타임캡슐</div>', unsafe_allow_html=True)
        st.markdown('<div class="sky-sub intro-late">선생님이 알려준 코드를 넣어 주세요</div>', unsafe_allow_html=True)
        code = st.text_input("반 코드", type="password")
        if st.button("들어가기"):
            found = find_class_by_code(code)
            if found:
                st.session_state.cls = found
                st.rerun()
            elif code.strip() == TEACHER_PIN:
                st.session_state.teacher = True
                st.rerun()
            else:
                st.error("코드가 맞지 않아요.")
        if CREDIT:
            st.markdown(f'<div class="credit intro-late">{esc(CREDIT)}</div>',
                        unsafe_allow_html=True)
        return

    if teacher:
        page_open()
        return

    render_backdrop(key, extra=st.session_state.get("_preview"))

    if st.session_state.get("just_saved"):
        num = st.session_state.pop("just_saved")
        c = cfg(key)
        st.markdown('<div class="sky-title">잘 걸었어요</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
<div class="paper center">
  <div class="letter-body">{num}번의 편지를 팻말에 걸었습니다.<br>
  나무가 자라는 동안 가끔 보러 오세요.</div>
  <div class="meta">{c['open'].year}. {c['open'].month}. {c['open'].day}에 열립니다 · {days_left(key)}일 남음</div>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    play_music()

    # 탭 대신 라디오. 탭은 안쪽이 숨겨진 채로 그려져서 화면에 따라 안 보일 수 있습니다.
    mode = st.radio(
        "무엇을 할까요",
        ["편지 쓰기", "나무 키우기"],
        horizontal=True,
        key="stu_mode",
        label_visibility="collapsed",
    )
    if mode == "편지 쓰기":
        page_write(key)
    else:
        page_tree(key)


if __name__ == "__main__":
    try:
        main()
    except SupabaseError as err:
        # 빨간 추적문 대신 무엇이 잘못됐는지 그대로 보여 줍니다
        st.error("저장소에 연결하지 못했습니다.")
        st.code(str(err), language=None)
        st.caption(
            "SUPABASE.md 의 2단계(표 만들기)와 4단계(Secrets)를 확인하세요. "
            "고치는 동안 아이들에게는 편지를 쓰지 않도록 안내해 주세요."
        )
