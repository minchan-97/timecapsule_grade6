#!/usr/bin/env python3
"""Time Capsule v9 lightweight load tester.

Purpose
-------
1) Probe a deployed Streamlit URL with concurrent HTTP GET requests.
2) Exercise the Supabase REST workload used by the app (reads; optionally safe writes)
   against an isolated temporary class_key and clean it up afterward.

This does NOT emulate Streamlit's WebSocket/session rerun protocol exactly. It is a
practical pre-class smoke/load test for HTTP availability and the Supabase data path.

Examples
--------
  python load_test.py app --url https://YOUR-APP.streamlit.app --users 31 --rounds 3
  python load_test.py db-read --users 31 --rounds 5
  python load_test.py db-mixed --users 31 --rounds 3 --confirm-write
  python load_test.py all --url https://YOUR-APP.streamlit.app --users 50 --rounds 3 --confirm-write

Supabase credentials are loaded, in order, from environment variables
SUPABASE_URL/SUPABASE_KEY, then .streamlit/secrets.toml.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import requests

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

ROOT = Path(__file__).resolve().parent
DEFAULT_USERS = 31
DEFAULT_ROUNDS = 3
TIMEOUT = 15


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[f]
    return xs[f] * (c - k) + xs[c] * (k - f)


@dataclass
class Result:
    name: str
    ok: bool
    seconds: float
    status: int | None = None
    detail: str = ""


def summarize(title: str, results: Iterable[Result], wall_seconds: float) -> bool:
    rs = list(results)
    good = [r for r in rs if r.ok]
    bad = [r for r in rs if not r.ok]
    lat = [r.seconds for r in good]
    print(f"\n=== {title} ===")
    print(f"requests : {len(rs)}")
    print(f"success  : {len(good)} ({(len(good)/len(rs)*100 if rs else 0):.1f}%)")
    print(f"errors   : {len(bad)}")
    print(f"wall     : {wall_seconds:.2f}s")
    print(f"throughput: {(len(rs)/wall_seconds if wall_seconds else 0):.2f} req/s")
    if lat:
        print(f"latency  : avg {statistics.mean(lat):.3f}s | p50 {percentile(lat,.50):.3f}s | "
              f"p95 {percentile(lat,.95):.3f}s | max {max(lat):.3f}s")
    if bad:
        print("first errors:")
        for r in bad[:8]:
            print(f"  - {r.name}: status={r.status} {r.detail[:180]}")
    return not bad


def run_parallel(jobs: list[tuple[str, Callable[[], requests.Response]]], users: int) -> tuple[list[Result], float]:
    barrier = threading.Barrier(min(users, len(jobs))) if jobs else None

    def wrapped(name: str, fn: Callable[[], requests.Response]) -> Result:
        # Synchronize the first wave so the server sees a realistic spike.
        if barrier is not None:
            try:
                barrier.wait(timeout=5)
            except threading.BrokenBarrierError:
                pass
        t0 = time.perf_counter()
        try:
            r = fn()
            dt = time.perf_counter() - t0
            ok = 200 <= r.status_code < 400
            return Result(name, ok, dt, r.status_code, "" if ok else r.text[:300])
        except Exception as e:
            return Result(name, False, time.perf_counter() - t0, None, f"{type(e).__name__}: {e}")

    t0 = time.perf_counter()
    out: list[Result] = []
    with ThreadPoolExecutor(max_workers=users) as ex:
        futures = [ex.submit(wrapped, name, fn) for name, fn in jobs]
        for f in as_completed(futures):
            out.append(f.result())
    return out, time.perf_counter() - t0


def normalize_url(raw: str) -> str:
    u = (raw or "").strip().strip('"').strip("'")
    if not u:
        return ""
    if "/dashboard/project/" in u:
        ref = u.split("/dashboard/project/")[1].split("/")[0].split("?")[0]
        return f"https://{ref}.supabase.co"
    if not u.startswith("http"):
        u = "https://" + u
    u = u.split("?")[0].rstrip("/")
    for tail in ("/rest/v1", "/rest", "/auth/v1", "/storage/v1"):
        if u.endswith(tail):
            u = u[: -len(tail)]
    return u.rstrip("/")


def load_supabase_conf() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if url and key:
        return normalize_url(url), key.strip().strip('"').strip("'")
    p = ROOT / ".streamlit" / "secrets.toml"
    if p.exists() and tomllib is not None:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        url = str(data.get("SUPABASE_URL", ""))
        key = str(data.get("SUPABASE_KEY", ""))
    if not url or not key:
        raise SystemExit(
            "Supabase credentials not found. Set SUPABASE_URL and SUPABASE_KEY as environment "
            "variables, or create .streamlit/secrets.toml. Never commit the service_role key."
        )
    return normalize_url(url), key.strip().strip('"').strip("'")


class SB:
    def __init__(self, url: str, key: str):
        self.url = url
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def get(self, table: str, class_key: str) -> requests.Response:
        return requests.get(
            f"{self.url}/rest/v1/{table}", headers=self.headers,
            params={"class_key": f"eq.{class_key}", "select": "*", "order": "id.asc"},
            timeout=TIMEOUT,
        )

    def insert(self, table: str, row: dict) -> requests.Response:
        return requests.post(
            f"{self.url}/rest/v1/{table}", headers=self.headers, json=row, timeout=TIMEOUT
        )

    def cleanup(self, class_key: str) -> None:
        for table in ("garden", "letters"):
            try:
                r = requests.delete(
                    f"{self.url}/rest/v1/{table}", headers=self.headers,
                    params={"class_key": f"eq.{class_key}"}, timeout=TIMEOUT,
                )
                if r.status_code >= 400:
                    print(f"WARNING: cleanup {table} failed HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"WARNING: cleanup {table} failed: {e}")


def app_probe(url: str, users: int, rounds: int) -> bool:
    url = url.rstrip("/")
    jobs = []
    for r in range(rounds):
        for u in range(users):
            # Cache-busting query avoids all requests collapsing into an intermediary cache.
            q = f"?loadtest={r}-{u}-{uuid.uuid4().hex[:8]}"
            jobs.append((f"app r{r+1} u{u+1}", lambda q=q: requests.get(url + q, timeout=TIMEOUT)))
    rs, wall = run_parallel(jobs, users)
    return summarize(f"Streamlit HTTP probe ({users} concurrent, {rounds} rounds)", rs, wall)


def db_read(sb: SB, users: int, rounds: int, class_key: str) -> bool:
    jobs = []
    for r in range(rounds):
        for u in range(users):
            table = "letters" if (u + r) % 2 == 0 else "garden"
            jobs.append((f"GET {table} r{r+1} u{u+1}", lambda table=table: sb.get(table, class_key)))
    rs, wall = run_parallel(jobs, users)
    return summarize(f"Supabase reads ({users} concurrent, {rounds} rounds)", rs, wall)


def db_mixed(sb: SB, users: int, rounds: int, class_key: str) -> bool:
    # Each virtual user gets one unique letter. Subsequent rounds generate garden actions and reads.
    now = datetime.now().isoformat(timespec="seconds")
    letter_jobs = []
    for u in range(users):
        row = {
            "class_key": class_key,
            "number": str(u + 1),
            "nickname": f"load{u+1}",
            "body": "부하테스트용 임시 편지입니다. 실제 학생 데이터가 아닙니다.",
            "written_at": now,
        }
        letter_jobs.append((f"POST letter u{u+1}", lambda row=row: sb.insert("letters", row)))
    rs1, wall1 = run_parallel(letter_jobs, users)
    ok1 = summarize(f"Supabase simultaneous letter saves ({users})", rs1, wall1)

    mixed_jobs = []
    items = ["daisy", "clover", "grass", "bush", "bird", "butterfly"]
    for r in range(rounds):
        for u in range(users):
            n = str(u + 1)
            # 2/3 writes, 1/3 reads approximates an intentionally harsh interaction burst.
            kind = (u + r) % 3
            if kind == 0:
                row = {
                    "class_key": class_key, "op": "water",
                    "event_id": f"water-{n}-{r}-{uuid.uuid4().hex[:8]}", "number": n,
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
                mixed_jobs.append((f"POST water r{r+1} u{u+1}", lambda row=row: sb.insert("garden", row)))
            elif kind == 1:
                row = {
                    "class_key": class_key, "op": "add",
                    "event_id": f"{n}-{r}-{uuid.uuid4().hex[:10]}", "number": n,
                    "item": random.choice(items), "x": round(random.uniform(5, 95), 1),
                    "y": round(random.uniform(25, 85), 1), "flip": bool(random.getrandbits(1)),
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
                mixed_jobs.append((f"POST garden r{r+1} u{u+1}", lambda row=row: sb.insert("garden", row)))
            else:
                table = "garden" if r % 2 else "letters"
                mixed_jobs.append((f"GET {table} r{r+1} u{u+1}", lambda table=table: sb.get(table, class_key)))
    rs2, wall2 = run_parallel(mixed_jobs, users)
    ok2 = summarize(f"Supabase mixed burst ({users} concurrent, {rounds} rounds)", rs2, wall2)
    return ok1 and ok2


def verdict(ok: bool) -> int:
    print("\n=== 판단 ===")
    if ok:
        print("PASS: 이 테스트 범위에서는 HTTP 오류 없이 요청을 처리했습니다.")
        print("수업 전에는 p95 지연이 3초 이하인지, 오류율이 0%인지 특히 확인하세요.")
        return 0
    print("CHECK: 오류가 발생했습니다. 첫 오류의 상태코드/메시지를 확인한 뒤 재시험하세요.")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Time Capsule v9 pre-class load test")
    ap.add_argument("mode", choices=["app", "db-read", "db-mixed", "all"])
    ap.add_argument("--url", help="deployed Streamlit app URL (required for app/all)")
    ap.add_argument("--users", type=int, default=DEFAULT_USERS, help="concurrent virtual users (default 31)")
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="request rounds per user (default 3)")
    ap.add_argument("--confirm-write", action="store_true", help="allow isolated temporary writes for db-mixed/all")
    args = ap.parse_args()
    if args.users < 1 or args.users > 200:
        ap.error("--users must be 1..200")
    if args.rounds < 1 or args.rounds > 50:
        ap.error("--rounds must be 1..50")
    if args.mode in {"app", "all"} and not args.url:
        ap.error("--url is required for app/all")
    if args.mode in {"db-mixed", "all"} and not args.confirm_write:
        ap.error("db-mixed/all requires --confirm-write because it creates temporary rows")

    ok = True
    if args.mode in {"app", "all"}:
        ok = app_probe(args.url, args.users, args.rounds) and ok

    if args.mode in {"db-read", "db-mixed", "all"}:
        url, key = load_supabase_conf()
        sb = SB(url, key)
        # Never touch a real class key. Timestamp + UUID gives a unique namespace.
        class_key = f"LOADTEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        print(f"\nTemporary class_key: {class_key}")
        try:
            if args.mode == "db-read":
                ok = db_read(sb, args.users, args.rounds, class_key) and ok
            else:
                ok = db_mixed(sb, args.users, args.rounds, class_key) and ok
        finally:
            if args.mode in {"db-mixed", "all"}:
                print("\nCleaning temporary load-test rows ...")
                sb.cleanup(class_key)
                print("Cleanup requested. Real class data was not addressed by this script.")

    return verdict(ok)


if __name__ == "__main__":
    raise SystemExit(main())
