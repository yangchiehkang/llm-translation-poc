#!/usr/bin/env python3
"""生成部署清单 DEPLOY_SHA256SUMS —— 两台机"跑的是不是同一份代码"的唯一凭据。

为什么需要它
------------
已经发生过四起"同一份代码在不同地方不一样"：
  1. 术语库版本 生产 f00ba0de / 评测 3b8221df（清单第 1 项）
  2. match_terms span 抑制修复未部署（第 2 项）
  3. target_alias 支持未部署（第 3 项）
  4. regression.py 的 C 段在 220 现役副本上热修（读 MAX_TEXT_CHARS 取 95%），
     **从未回灌仓库** —— 直到 2026-08-02 部署 125 时才被发现
每一起都是"以为一样、其实不一样"，而且都是**人肉比对**才发现的。两台机并存以后
分叉面翻倍，靠人肉必然漏。所以把它变成自检的一个断言。

用法
----
  # 改完代码后在**本地权威副本**上重新生成，并与代码一起提交
  python3 api/deploy/make_manifest.py
  # 部署后每轮自检自动校验（见 selfcheck.py 的 probe_manifest）

纪律
----
清单**必须与代码同一个 commit**。只改代码不重生成清单，自检会立刻报
manifest_mismatch —— 这是设计意图，不是误报：它说明部署的东西和记录的东西对不上。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MANIFEST = PROJECT / "api" / "deploy" / "DEPLOY_SHA256SUMS"

# 纳入范围：生产路径上的全部 Python。翻译行为由这些文件决定，改了就必须重新部署。
# 不含 .env（机器专属、含密钥）、不含 termbase（另有独立的 md5 断言）、
# 不含 outputs/ 与 data/（数据不是代码）。
ROOTS = ("api", "scripts/common")


def iter_files():
    for root in ROOTS:
        base = PROJECT / root
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            yield p


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def build() -> str:
    lines = []
    for p in iter_files():
        lines.append(f"{sha256(p)}  {p.relative_to(PROJECT)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    content = build()
    check = "--check" in sys.argv
    if check:
        if not MANIFEST.exists():
            print("DEPLOY_SHA256SUMS 不存在")
            return 1
        old = MANIFEST.read_text(encoding="utf-8")
        if old != content:
            print("清单与当前代码不一致——请重新生成并与代码一起提交")
            return 1
        print(f"清单一致（{len(content.strip().splitlines())} 个文件）")
        return 0
    MANIFEST.write_text(content, encoding="utf-8")
    print(f"已写入 {MANIFEST.relative_to(PROJECT)}（{len(content.strip().splitlines())} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
