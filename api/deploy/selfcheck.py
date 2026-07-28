#!/usr/bin/env python3
"""生产自检：定时打一发**真实翻译**，把可用性与延迟记成时序。

为什么需要它
------------
2026-07-28 后端端口 40018 被属主下线，生产静默中断 **5 天**——服务 active、
`/health` 200、日志零请求，**没有任何机制会告诉我们**。后端是别人的共享服务，
40004 完全可能重演。我们不需要拥有那个服务，但需要在它变化时立刻知道。

`/health` 修好也没用，如果没人看。所以要定时**真的翻一句**。

三件事
------
1. **每次（10 分钟一发）**：短文本真实翻译，只管可用性；顺带把耗时记进时序。
   同时直调后端取 usage，断言 `reasoning_tokens == 0` —— 40004 带着
   `--reasoning-parser qwen3`，属主哪天打开 `enable_thinking` 我们要立刻知道。
2. **每天两次（错开时段，默认 03:x 与 15:x）**：一发 6000 字符真实翻译，
   记耗时与 completion_tokens。MAX_TEXT_CHARS=6000 的余量估计
   （p95≈53s、并发 1.49 倍 → 79s，对 120s 留 41s）全部建立在 **40018** 的实测上，
   40004 从未验证过，而它是合并后的端点、消费方可能更多。
   **不为采数据高频打长文本**——那台机是共享的。
3. **失败保留完整详情**：请求体、响应体、异常栈、当时的 /health 快照，
   全部落进单独的失败日志。只记一个 false 等于没记。

输出
----
  <LOG_DIR>/selfcheck.jsonl        每次一行，时序，供后续算 p50/p95
  <LOG_DIR>/selfcheck_FAILURES.log 只在失败时追加，含完整详情，文件名刻意显眼

用法（cron，每 10 分钟）
------------------------
  */10 * * * * /data/SERVICE_USER/translation-api/venv/bin/python \
      PROJECT_ROOT/api/deploy/selfcheck.py >> \
      /data/SERVICE_USER/translation-api/logs/selfcheck_cron.log 2>&1
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("SELFCHECK_BASE", "http://127.0.0.1:8188")
LOG_DIR = Path(os.environ.get("SELFCHECK_LOG_DIR", "/data/SERVICE_USER/translation-api/logs"))
SERIES = LOG_DIR / "selfcheck.jsonl"
FAILURES = LOG_DIR / "selfcheck_FAILURES.log"
LONG_TEXT = Path(__file__).resolve().parent / "selfcheck_long_en.txt"

SHORT_TEXT = ("The manufacturer shall demonstrate that the rechargeable electrical energy "
              "storage system complies with the requirements of paragraph 5.1.")
# 长文本探针的时段（本地小时）。每天两次、错开，避开整点高峰。
LONG_HOURS = {int(h) for h in os.environ.get("SELFCHECK_LONG_HOURS", "3,15").split(",")}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_env(key: str) -> str:
    for line in (PROJECT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def http(url: str, payload: dict | None = None, headers: dict | None = None,
         timeout: float = 180.0) -> tuple[int, dict | str, float]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode(), e.code
    el = time.time() - t
    try:
        return status, json.loads(body), el
    except Exception:
        return status, body, el


def record_failure(kind: str, detail: dict) -> None:
    """失败时保留**完整**详情——请求、响应、异常栈、/health 快照。"""
    try:
        _, health, _ = http(f"{BASE}/health", timeout=10)
    except Exception as exc:                                        # noqa: BLE001
        health = f"health probe itself failed: {exc}"
    block = {
        "ts": now(), "host": socket.gethostname(), "kind": kind,
        "detail": detail, "health_snapshot": health,
    }
    FAILURES.parent.mkdir(parents=True, exist_ok=True)
    with FAILURES.open("a", encoding="utf-8") as f:
        f.write("=" * 78 + "\n")
        f.write(json.dumps(block, ensure_ascii=False, indent=2) + "\n")


def probe_backend_usage(token: str) -> dict:
    """直调后端取 usage —— API 不返回 token 数，thinking 是否被打开只能这样看。"""
    base_url = read_env("LOCAL_NPU_BASE_URL")
    model = read_env("LOCAL_NPU_MODEL")
    if not base_url or not model:
        return {"ok": False, "why": "backend not local_npu / 未配置"}
    body = {"model": model, "temperature": 0, "max_tokens": 64,
            "messages": [{"role": "user", "content": "把这句译成中文，只输出译文：" + SHORT_TEXT}]}
    try:
        st, resp, el = http(base_url.rstrip("/") + "/chat/completions", body,
                            {"Content-Type": "application/json"}, timeout=120)
    except Exception as exc:                                        # noqa: BLE001
        return {"ok": False, "why": f"{type(exc).__name__}: {exc}"}
    if st != 200 or not isinstance(resp, dict):
        return {"ok": False, "why": f"HTTP {st}", "resp": str(resp)[:400]}
    u = resp.get("usage") or {}
    ctd = u.get("completion_tokens_details") or {}
    rt = ctd.get("reasoning_tokens")
    ct = u.get("completion_tokens") or 0
    return {"ok": True, "elapsed_s": round(el, 3), "completion_tokens": ct,
            "reasoning_tokens": rt, "tok_per_s": round(ct / el, 1) if el > 0 else None,
            # 断言项：属主若打开 enable_thinking，这里立刻变 True
            "thinking_on": bool(rt),
            "reasoning_field": resp["choices"][0]["message"].get("reasoning")}


def translate(token: str, text: str, timeout: float) -> tuple[bool, dict]:
    st, resp, el = http(f"{BASE}{read_env('LAW_PATH') or '/openApi/translate/law'}",
                        {"translateType": "1", "languageType": "EN-CN", "originalText": text},
                        {"Content-Type": "application/json",
                         "Authorization": f"Bearer {token}"}, timeout=timeout)
    ok = st == 200 and isinstance(resp, dict) and resp.get("code") == 0 \
        and bool((resp.get("data") or {}).get("translateText"))
    out = (resp.get("data") or {}).get("translateText", "") if isinstance(resp, dict) else ""
    return ok, {"http": st, "elapsed_s": round(el, 3), "code": resp.get("code")
                if isinstance(resp, dict) else None,
                "msg": resp.get("msg") if isinstance(resp, dict) else str(resp)[:300],
                "in_chars": len(text), "out_chars": len(out), "out_head": out[:60]}


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    token = read_env("API_TOKENS").split(",")[0]
    rec: dict = {"ts": now(), "host": socket.gethostname()}
    failed = []

    ok, short = translate(token, SHORT_TEXT, timeout=180)
    rec["short"] = short
    rec["short_ok"] = ok
    if not ok:
        failed.append("short_translate")
        record_failure("short_translate", {"request_text": SHORT_TEXT, "result": short})

    usage = probe_backend_usage(token)
    rec["backend_usage"] = usage
    if not usage.get("ok"):
        failed.append("backend_usage_probe")
        record_failure("backend_usage_probe", {"result": usage})
    elif usage.get("thinking_on"):
        # 不是故障，但必须立刻知道：后端属主打开了 thinking，延迟与译文都会变。
        failed.append("thinking_turned_on")
        record_failure("thinking_turned_on", {
            "why": "reasoning_tokens > 0 —— 后端 enable_thinking 被打开，"
                   "延迟与译文都会变，需重新评估交付承诺与历史对照数",
            "result": usage})

    st, health, _ = http(f"{BASE}/health", timeout=10)
    hd = health.get("data", {}) if isinstance(health, dict) else {}
    rec["backend_reachable"] = hd.get("backend_reachable")
    rec["backend_check_detail"] = hd.get("backend_check_detail")
    if hd.get("backend_reachable") is False:
        failed.append("backend_unreachable")
        record_failure("backend_unreachable", {"health": health})

    # 长文本探针：每天两次，错开时段。**不为采数据高频打长文本，机器是共享的。**
    hour = datetime.now().hour
    minute = datetime.now().minute
    if hour in LONG_HOURS and minute < 10 and LONG_TEXT.exists():
        text = LONG_TEXT.read_text(encoding="utf-8")
        lok, lon = translate(token, text, timeout=300)
        lon["completion_tokens_est"] = None
        rec["long"] = lon
        rec["long_ok"] = lok
        if not lok:
            failed.append("long_translate")
            record_failure("long_translate",
                           {"in_chars": len(text), "result": lon,
                            "note": "MAX_TEXT_CHARS=6000 的余量估计出自 40018，40004 从未验证"})

    rec["failed"] = failed
    with SERIES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    tag = "OK " if not failed else "FAIL"
    u = rec.get("backend_usage") or {}
    print(f"[{rec['ts']}] {tag} short={short['elapsed_s']}s code={short['code']} "
          f"reachable={rec['backend_reachable']} "
          f"tok/s={u.get('tok_per_s')} reasoning_tokens={u.get('reasoning_tokens')}"
          + (f"  long={rec['long']['elapsed_s']}s" if "long" in rec else "")
          + (f"  FAILED={failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                               # noqa: BLE001
        record_failure("selfcheck_crashed", {"traceback": traceback.format_exc()})
        print("[selfcheck] CRASHED, 详情见", FAILURES)
        sys.exit(2)
