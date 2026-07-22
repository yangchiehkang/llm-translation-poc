#!/usr/bin/env python3
"""填入真实 DASHSCOPE_API_KEY 后的回归验收（真实调用 qwen-max）：
  A. 验收第4项：3 条术语的文本翻译，确认术语按指定译法出现在译文里
  B. 从 outputs/translations/ 取 3 条已有 qwen-max 样本，通过接口重跑，与原结果对比
  C. 长文本截断保护：构造接近上限的长文本，确认要么完整返回、要么明确报截断错误
所有输出为真实返回，不推测。
"""
import json
import sys
import time
import urllib.request
from difflib import SequenceMatcher

BASE = "http://127.0.0.1:8188"
PROJECT = "PROJECT_ROOT"
REF = f"{PROJECT}/outputs/translations/source_only_300_by_lang/first/no_term_baseline_first_translations.jsonl"


def token():
    for line in open(f"{PROJECT}/.env", encoding="utf-8"):
        if line.startswith("API_TOKENS="):
            return line.split("=", 1)[1].strip().split(",")[1]
    raise SystemExit("no self-test token in .env")


def call(payload, tok, timeout=120):
    req = urllib.request.Request(
        f"{BASE}/openApi/translate/law",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {tok}"},
        method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read())
    return body, int((time.time() - t0) * 1000)


def load_ref(n=3):
    rows = []
    for line in open(REF, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("source_lang") == "de" and (r.get("hypothesis") or "").strip() and 40 < len(r["source_text"]) < 280:
            rows.append(r)
        if len(rows) >= n:
            break
    return rows


def main():
    tok = token()

    print("=" * 70)
    print("A. 验收第4项：3 条术语 EN-CN 文本翻译，术语生效自证")
    print("=" * 70)
    a_terms = [
        {"originalTerminology": "type approval", "translateTerminology": "整车型式批准"},
        {"originalTerminology": "approval authority", "translateTerminology": "型式批准主管部门"},
        {"originalTerminology": "technical service", "translateTerminology": "技术检测机构"},
    ]
    a_payload = {
        "translateType": "1", "languageType": "EN-CN",
        "originalText": "The approval authority shall notify the technical service before granting type approval for the vehicle.",
        "terminologyList": a_terms,
    }
    body, ms = call(a_payload, tok)
    print(f"code={body['code']} msg={body['msg']} elapsed_ms={ms}")
    if body["code"] == 0:
        tx = body["data"]["translateText"]
        print("译文:", tx)
        for t in a_terms:
            hit = t["translateTerminology"] in tx
            print(f"  术语 {t['originalTerminology']!r} -> {t['translateTerminology']!r} : {'✅命中' if hit else '❌未命中'}")

    print()
    print("=" * 70)
    print("B. 回归：3 条已有 qwen-max 样本(DE-CN)重跑，与 outputs/ 原结果对比")
    print("=" * 70)
    for i, r in enumerate(load_ref(3), 1):
        payload = {"translateType": "1", "languageType": "DE-CN",
                   "originalText": r["source_text"], "terminologyList": []}
        body, ms = call(payload, tok)
        new = body.get("data", {}).get("translateText", "") if body["code"] == 0 else f"[{body['code']}] {body['msg']}"
        old = r["hypothesis"]
        sim = SequenceMatcher(None, old, new).ratio()
        print(f"\n--- 样本 {i} (id={r.get('sample_id')}) elapsed_ms={ms} ---")
        print("  原文     :", r["source_text"][:100])
        print("  原结果   :", old[:100])
        print("  接口重跑 :", new[:100])
        print(f"  字面相似度: {sim:.2f}  (同模型 qwen-max；原结果为 no_term_baseline 模板+temp>0，接口用分级路由，故非逐字相同属正常)")

    print()
    print("=" * 70)
    print("C. 长文本截断保护：接近上限的长文本，确认完整返回 或 明确报截断")
    print("=" * 70)
    base_sent = ("Die Genehmigungsbehörde stellt sicher, dass der technische Dienst die Prüfungen "
                 "gemäß den Anforderungen dieser Verordnung durchführt und die Konformität der Produktion bewertet. ")
    long_text = (base_sent * 60)[:7500]  # 约 7500 字符，接近 8000 上限
    print(f"输入字符数: {len(long_text)}")
    body, ms = call({"translateType": "1", "languageType": "DE-CN",
                     "originalText": long_text, "terminologyList": []}, tok, timeout=180)
    print(f"code={body['code']} msg={body['msg']} elapsed_ms={ms}")
    if body["code"] == 0:
        out = body["data"]["translateText"]
        print(f"完整返回，译文字符数={len(out)}；结尾: ...{out[-60:]!r}")
        print("结论: ✅ 完整返回（未截断）")
    elif body["code"] == 500 and "截断" in body["msg"]:
        print("结论: ✅ 明确报截断错误（未静默返回半截译文）")
    else:
        print(f"结论: 其他 code={body['code']}（如 422 超长上限）")


if __name__ == "__main__":
    main()
