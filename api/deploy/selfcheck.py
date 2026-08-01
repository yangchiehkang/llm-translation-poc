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
   **并断言模型身份**（2026-07-30 补）：后端 `/v1/models` 里必须有 `.env` 的
   `LOCAL_NPU_MODEL`，且 `/health` 回显的 backend/model 与 `.env` 一致。
   可达 ≠ 还是同一个模型：`--served-model-name` 是属主的启动参数，端口活着、
   翻译照返，模型却可能已经换人——那种情况下对外的 DA/TCR 全部失效。
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


def read_env(key: str) -> str:
    # .env 不存在时返回空串而不是抛异常：本文件在本地（无 .env）也要能被导入/静态检查。
    env_path = PROJECT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


# 自检打向本机 API 的地址：端口**从 .env 的 PORT 读**，不留写死的默认值。
# 写死过 8188：220 切 4188 之后，自检会安静地打向一个没人监听的端口，
# 于是"自检失败"被当成"服务挂了"，或者更糟——自检打到了另一个服务上。
# 同一类坑见 MAX_TEXT_CHARS 默认 8000 与 regression.py 的 BASE。
# 端口缺失不在导入期抛错（会连带打断 lint/测试），留到 main() 里报。
_PORT = os.environ.get("SELFCHECK_PORT") or read_env("PORT")
BASE = os.environ.get("SELFCHECK_BASE") or (f"http://127.0.0.1:{_PORT}" if _PORT else "")
LOG_DIR = Path(os.environ.get("SELFCHECK_LOG_DIR", "/data/SERVICE_USER/translation-api/logs"))
SERIES = LOG_DIR / "selfcheck.jsonl"
FAILURES = LOG_DIR / "selfcheck_FAILURES.log"
LONG_TEXT = Path(__file__).resolve().parent / "selfcheck_long_en.txt"

SHORT_TEXT = ("The manufacturer shall demonstrate that the rechargeable electrical energy "
              "storage system complies with the requirements of paragraph 5.1.")
# 长文本探针的时段（本地小时）。每天两次、错开，避开整点高峰。
LONG_HOURS = {int(h) for h in os.environ.get("SELFCHECK_LONG_HOURS", "3,15").split(",")}

# thinking 复燃的 **content 级**哨兵。
#
# 为什么必须有这一条：原来只有 `reasoning_tokens > 0` 一个探测器，那依赖后端带
# `--reasoning-parser`（220 的 40004 带，所以思考内容被解析进 reasoning 字段、
# 计入 reasoning_tokens）。**125 的 9018 不带 reasoning-parser**，属主若打开
# enable_thinking，reasoning_tokens 恒为 null、旧哨兵永远不响，而 `<think>…</think>`
# 会**直接漏进 content**，也就是漏进交付给国创的译文里。
# 所以 125 上这一条是唯一的 thinking 探测器，220 上它与 reasoning_tokens 互为冗余。
THINK_MARKERS = ("<think>", "</think>", "<thinking>", "</thinking>")


def scan_think(text: str) -> list[str]:
    """返回译文里出现的 thinking 标记；空列表表示干净。"""
    if not text:
        return []
    low = text.lower()
    return [m for m in THINK_MARKERS if m in low]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


# 生产术语库的期望 md5 —— 钉的是**生产当前实际在用的那一版**，不是评测版。
#
# 生产与评测共用同一个文件路径（.env 的 TERMBASE_PATH），改它会立刻改变生产译文，
# 而术语库改动必须作为独立部署批次走，不能被评测顺手改掉。本断言就是防这个。
#
# ⚠️ 生产这一版 (f00ba0de) **早于** T4 评测用的那一版 (3b8221df)：
#    T4 的 7 条改动（cell/high voltage/approval authority/compliance/manikin/
#    shall/shall not）从未上过生产。这是有意的——评测归评测，部署归部署。
#    但由此可知：**对外的 TCR 96.43% 是评测术语库的数，不是生产当前行为的数。**
#
# 换版时**同时**更新这里和 README_DEPLOY §五，否则自检会一直报。
EXPECTED_TERMBASE_MD5 = os.environ.get(
    "SELFCHECK_TERMBASE_MD5", "f00ba0de15476b22fbe8b73ad88fe64d")


def probe_termbase() -> dict:
    """生产术语库有没有被改动。与 reasoning_tokens==0 同类：外部状态漂移的哨兵。"""
    import hashlib
    rel = read_env("TERMBASE_PATH") or "termbase/auto_regulation_terms_v1.csv"
    path = (PROJECT / rel) if not rel.startswith("/") else Path(rel)
    if not path.exists():
        return {"ok": False, "why": f"术语库文件不存在: {path}"}
    md5 = hashlib.md5(path.read_bytes()).hexdigest()
    ok = (md5 == EXPECTED_TERMBASE_MD5)
    return {"ok": ok, "path": str(path), "md5": md5,
            "expected": EXPECTED_TERMBASE_MD5,
            "why": "ok" if ok else "生产术语库 md5 与预期不符——被改过，或换版后忘了更新预期值"}


def probe_manifest() -> dict:
    """部署清单校验：这台机上跑的代码，是不是与记录在案的那一份逐字节相同。

    与术语库 md5 断言同类，但覆盖面是**全部生产 Python**。两台机并存后，
    "以为两边一样、其实不一样"的分叉面翻倍（已发生四起，见 make_manifest.py），
    人肉比对必然漏，所以做成断言。清单由 api/deploy/make_manifest.py 生成，
    必须与代码同一个 commit。
    """
    import hashlib
    manifest = PROJECT / "api" / "deploy" / "DEPLOY_SHA256SUMS"
    if not manifest.exists():
        return {"ok": False, "why": f"部署清单不存在: {manifest}——本次部署没有留下可校验的凭据"}
    bad, missing, n = [], [], 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        expected, _, rel = line.partition("  ")
        p = PROJECT / rel
        n += 1
        if not p.exists():
            missing.append(rel)
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            bad.append(rel)
    ok = not bad and not missing
    return {"ok": ok, "checked": n, "mismatch": bad, "missing": missing,
            "why": "ok" if ok else
                   f"部署代码与清单不符——改动过、部署漏了、或两台机已分叉"
                   f"（不符 {len(bad)} 个、缺失 {len(missing)} 个）"}


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
    content = resp["choices"][0]["message"].get("content") or ""
    return {"ok": True, "elapsed_s": round(el, 3), "completion_tokens": ct,
            "reasoning_tokens": rt, "tok_per_s": round(ct / el, 1) if el > 0 else None,
            # 断言项：属主若打开 enable_thinking，带 reasoning-parser 的后端这里变 True。
            # 不带 parser 的后端（125 的 9018）此项恒 False —— 靠下面的 think_markers 兜底。
            "thinking_on": bool(rt),
            "think_markers": scan_think(content),
            "reasoning_field": resp["choices"][0]["message"].get("reasoning")}


def probe_backend_model() -> dict:
    """断言后端**真的还在服务我们指定的那个模型**。

    2026-07-28 的 40018 事故里，可达性与模型身份是两件事：端口消失是最粗的
    一种变化，更隐蔽的是端口还在、模型被属主换成另一个（vLLM `serve` 的
    `--served-model-name` 是启动参数，属主重启即可改）。那种情况下
    `backend_reachable` 仍为 true、翻译仍会返回内容，但产出已经不是我们
    验收过的模型——对外数字全部失效而无人知晓。

    两条独立断言（任一不成立即失败）：
      1. 后端 `/v1/models` 的 id 列表里有 `.env` 的 `LOCAL_NPU_MODEL`
      2. `/health` 回显的 `backend_info.model` 与 `.env` 一致，且
         `backend` 仍是 `local_npu`（不是悄悄回退到 dashscope 云端）
    """
    expected = read_env("LOCAL_NPU_MODEL")
    base_url = read_env("LOCAL_NPU_BASE_URL")
    expected_backend = read_env("BACKEND")
    if not expected or not base_url:
        return {"ok": False, "why": "LOCAL_NPU_MODEL / LOCAL_NPU_BASE_URL 未配置"}
    out: dict = {"expected_model": expected, "expected_backend": expected_backend}
    try:
        st, resp, _ = http(base_url.rstrip("/") + "/models", None,
                           {"Content-Type": "application/json"}, timeout=30)
    except Exception as exc:                                        # noqa: BLE001
        return {**out, "ok": False, "why": f"/v1/models 探测失败 {type(exc).__name__}: {exc}"}
    served = [m.get("id") for m in (resp.get("data") or [])] if isinstance(resp, dict) else []
    out["served_models"] = served
    if st != 200 or expected not in served:
        return {**out, "ok": False,
                "why": f"后端 /v1/models 里没有 {expected}（HTTP {st}，实际服务 {served}）"
                       f"——模型被属主换过，或端口指向了另一个服务"}
    _, health, _ = http(f"{BASE}/health", timeout=10)
    hd = (health.get("data") or {}) if isinstance(health, dict) else {}
    bi = hd.get("backend_info") or {}
    out["health_backend"] = hd.get("backend")
    out["health_model"] = bi.get("model")
    if hd.get("backend") != expected_backend or bi.get("model") != expected:
        return {**out, "ok": False,
                "why": f"/health 回显 backend={hd.get('backend')} model={bi.get('model')}，"
                       f"与 .env 的 {expected_backend}/{expected} 不一致"}
    return {**out, "ok": True, "why": "ok"}


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
                "in_chars": len(text), "out_chars": len(out), "out_head": out[:60],
                # content 级 thinking 哨兵：在**完整**译文上扫，不是只扫 out_head
                "think_markers": scan_think(out)}


def main() -> int:
    if not BASE:
        print("PORT 未在 .env 中设置，且未给 SELFCHECK_BASE/SELFCHECK_PORT"
              "——拒绝猜测端口（曾写死 8188，220 切 4188 后会静默打空）")
        return 1
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

    # content 级 thinking 哨兵：译文里出现 <think>/</think> 即刻报。
    # 这是 125（后端无 reasoning-parser）唯一的 thinking 探测器；在 220 上与
    # reasoning_tokens 互为冗余。命中意味着思考内容正在漏进交付给国创的译文。
    think_hit = list(short.get("think_markers") or [])
    if think_hit:
        failed.append("think_leaked_into_content")
        record_failure("think_leaked_into_content", {
            "why": "译文 content 里出现 thinking 标记 —— 后端 enable_thinking 被打开，"
                   "且后端未带 reasoning-parser，思考内容未被剥离，正在直接进入对外译文。",
            "markers": think_hit, "result": short})

    usage = probe_backend_usage(token)
    rec["backend_usage"] = usage
    if usage.get("think_markers"):
        if "think_leaked_into_content" not in failed:
            failed.append("think_leaked_into_content")
        record_failure("think_leaked_into_content", {
            "why": "直调后端的 content 里出现 thinking 标记（API 层译文可能已被清洗，"
                   "但后端行为已变，交付承诺与历史对照数需重新评估）。",
            "markers": usage.get("think_markers"), "result": usage})
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

    bm = probe_backend_model()
    rec["backend_model"] = bm
    if not bm.get("ok"):
        failed.append("backend_model_mismatch")
        record_failure("backend_model_mismatch", {
            "why": "后端模型身份断言不成立。40004 是 root 拥有的共享服务（40018 就是"
                   "这么消失的），端口活着不等于还在服务我们验收过的那个模型；"
                   "模型一换，对外的 DA/TCR 数字全部失效。",
            "result": bm})

    mf = probe_manifest()
    rec["manifest"] = mf
    if not mf.get("ok"):
        failed.append("manifest_mismatch")
        record_failure("manifest_mismatch", {
            "why": "部署代码与 DEPLOY_SHA256SUMS 不符。两台机并存后，代码分叉"
                   "不会有任何外部症状——直到对外数字对不上才被发现。",
            "result": mf})

    tb = probe_termbase()
    rec["termbase"] = tb
    if not tb.get("ok"):
        failed.append("termbase_changed")
        record_failure("termbase_changed", {
            "why": "生产术语库文件被改动。生产与评测共用同一个 CSV，"
                   "术语库改动必须作为独立部署批次处理，不能被评测顺手改掉。",
            "result": tb})

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
          f"tok/s={u.get('tok_per_s')} reasoning_tokens={u.get('reasoning_tokens')} "
          f"model={bm.get('health_model') or '?'}{'' if bm.get('ok') else ' MISMATCH'} "
          f"termbase={'ok' if tb.get('ok') else 'CHANGED'}"
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
