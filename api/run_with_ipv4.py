#!/usr/bin/env python3
"""在装上 IPv4-first 修复后再运行目标脚本，让 scripts/ 里的批处理翻译复用同样的修复
（否则会吃到本机 IPv6->dashscope 不通导致的 ~63s SYN 超时）。

用法：
  python api/run_with_ipv4.py <目标脚本.py 或 模块名> [该脚本的参数...]

例：
  /data/miniconda3/envs/ascend/bin/python api/run_with_ipv4.py \
      scripts/translation/qwenmax_translate.py --input data/... --output-dir data/...

只做一件事：进程启动早期把 socket.getaddrinfo 的 IPv4 排到前面，再把控制权交给目标脚本。
纯标准库 socket 补丁，任何 Python 环境（含 conda ascend）都可用，无需改动 scripts/。
"""
import os
import runpy
import sys

# 保证 api.net 可被 import（本文件在 <项目根>/api/ 下）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from api.net import install_ipv4_first

install_ipv4_first()

if len(sys.argv) < 2:
    sys.stderr.write("usage: python api/run_with_ipv4.py <target.py|module> [args...]\n")
    sys.exit(2)

target = sys.argv[1]
# 让目标脚本看到正确的 argv（去掉本启动器这一层）
sys.argv = sys.argv[1:]

if target.endswith(".py"):
    runpy.run_path(target, run_name="__main__")
else:
    runpy.run_module(target, run_name="__main__")
