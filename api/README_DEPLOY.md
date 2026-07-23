# 港中深法规翻译 API 包装层 — 部署与运维

本目录是**自包含的 `api/` 包**，在现有翻译代码外面套一层 FastAPI，符合《港中深 API 接口文档 v1.0》。
只做包装，直接 `import` 现有 `scripts/common` 的 `match_terms / build_messages / call_dashscope_generation`，
**不复制第二份翻译实现，不改动任何现有 `scripts/` 代码**。

- 后端配置开关：`BACKEND=dashscope | local_npu`，两个后端同签名 `translate(text, src_lang, tgt_lang, terms) -> str`，默认 `dashscope`。
- 服务监听 `0.0.0.0:8188`。
- 统一响应 `{code,msg,data}`，**HTTP 一律 200**，错误体现在 `code`。

---

## 一、目录与路径（服务器现状）

| 项 | 路径 |
|---|---|
| 项目根（实际能跑通的副本，branch `dev/yangjiekang`） | `PROJECT_ROOT` |
| API 包 | `<项目根>/api/` |
| 独立 venv（装在 /data，避开根分区） | `/data/SERVICE_USER/translation-api/venv` |
| 日志目录 | `/data/SERVICE_USER/translation-api/logs`（`LOG_DIR` 可配） |
| `.env`（chmod 600，已在 .gitignore） | `<项目根>/.env` |
| systemd --user 单元 | `~/.config/systemd/user/translation-api.service` |

> 本机无 root，采用 **systemd `--user`** 常驻（`Restart=always`）。管理员可用 `api/deploy/translation-api.system.service` 装成系统级服务。

---

## 二、首次部署

```bash
# 1) 建独立 venv（装在 /data）
python3 -m venv /data/SERVICE_USER/translation-api/venv
/data/SERVICE_USER/translation-api/venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ \
    -r PROJECT_ROOT/api/requirements.txt

# 2) 准备 .env（切勿提交；chmod 600）
cd PROJECT_ROOT
cp api/.env.example .env
vim .env                      # 填 API_TOKENS、DASHSCOPE_API_KEY
chmod 600 .env

# 3) 建日志目录
mkdir -p /data/SERVICE_USER/translation-api/logs

# 4) 安装 systemd --user 单元
mkdir -p ~/.config/systemd/user
cp api/deploy/translation-api.user.service ~/.config/systemd/user/translation-api.service
systemctl --user daemon-reload
systemctl --user enable --now translation-api

# 5)（可选）开机/登出后仍常驻
loginctl enable-linger "$USER"   # 若无权限，请管理员执行
```

---

## 三、启停

```bash
systemctl --user start   translation-api      # 启
systemctl --user stop    translation-api      # 停
systemctl --user restart translation-api      # 重启（改配置后执行）
systemctl --user status  translation-api      # 状态
```

手动前台启动（调试用，不经 systemd）：

```bash
cd PROJECT_ROOT
API_VENV=/data/SERVICE_USER/translation-api/venv bash api/deploy/run.sh
```

---

## 四、看日志

```bash
# systemd 侧
journalctl --user -u translation-api -f
journalctl --user -u translation-api --since "10 min ago"

# 文件侧（含 request_id / 接口 / translateType / languageType / 原文长度 / 命中术语数 / 耗时 / 状态；原文只记前 200 字符）
tail -f /data/SERVICE_USER/translation-api/logs/api.log
```

日志字段示例：
```
request_id=ab12cd34ef56 interface=/openApi/translate/law translateType=1 languageType=EN-CN
src_len=182 matched_terms=3 elapsed_ms=1874 status=ok src='...前200字...'
```

---

## 五、改配置 / 切后端

所有配置在 `<项目根>/.env`，改完 `systemctl --user restart translation-api` 生效。

| 变量 | 作用 |
|---|---|
| `BACKEND` | `dashscope`（默认）/ `local_npu` |
| `API_TOKENS` | 逗号分隔多 token（国创一个、自测一个）|
| `DASHSCOPE_API_KEY` | dashscope 后端密钥 |
| `LAW_PATH` | 翻译接口路径（默认 `/openApi/translate/law`）|
| `TERMINOLOGY_LIST_AS_OBJECT` | `false` 返回数组 / `true` 返回单对象 |
| `MAX_TEXT_CHARS` | 单次输入文本上限（默认 8000）|
| `MAX_TOKENS` | 输出 token 下限（默认 4096）|
| `DYNAMIC_MAX_TOKENS` / `MODEL_MAX_OUTPUT_TOKENS` / `OUTPUT_TOKENS_RATIO` | 按输入长度动态计算输出上限，夹在 [MAX_TOKENS, 8192] |
| `MODEL_NAME` / `TEMPERATURE` / `TIMEOUT` / `RETRIES` | 模型参数 |
| `LOCAL_NPU_BASE_URL` / `LOCAL_NPU_MODEL` | 切到 local_npu 时指向本地 OpenAI 兼容服务 |
| `PREFER_IPV4` | `true`（默认）优先 IPv4，规避本机 IPv6→dashscope 不通导致的 ~63s SYN 超时 |

**切到 local_npu：**
```bash
# .env 里
BACKEND=local_npu
LOCAL_NPU_BASE_URL=http://127.0.0.1:<本地推理端口>/v1
LOCAL_NPU_MODEL=<本地已在跑的模型名>
# 重启
systemctl --user restart translation-api
```
> 本期不做模型选型、显存规划、卡号分配。local_npu 指向服务器上**已在跑**的本地 OpenAI 兼容推理服务。

**当前生产配置（`.env` 不进 git，此处为唯一状态记录点）：**

| 变量 | 当前值 |
|---|---|
| `BACKEND` | `local_npu` |
| `LOCAL_NPU_BASE_URL` | `http://<VLLM_ENDPOINT_ALT>/v1` |
| `LOCAL_NPU_MODEL` | `Qwen3.6-35B-A3B` |
| `TEMPERATURE` | `0` |
| `MAX_TEXT_CHARS` | `6000` |

> 40018 是服务器本地 vLLM（Qwen3.6-35B-A3B，root 拥有、绑 `<INTERNAL_HOST>`、共享服务、卡 2/3 TP 对）；`TEMPERATURE=0` 取确定性（同输入逐字一致）。该 vLLM 若被停/重绑，接口会 `code:500`，此时按下方回滚。
> `MAX_TEXT_CHARS=6000`（由 8000 下调）：延迟方差实测中 8000 字符 p95≈95s、距 120s 硬超时余量偏薄，共享服务负载高峰可能击穿；6000 字符实测 p95≈53s，约 2× 余量。实测 6000 字符单次约 30s。

### 回滚到 dashscope（已实测可用，2026-07-23）

```bash
# .env 里
BACKEND=dashscope
# 重启
systemctl --user restart translation-api
# 确认
curl -s http://127.0.0.1:8188/health   # 期望 backend=dashscope、backend_info.api_key_valid=true
```

- 回滚后翻译由 **qwen-max** 执行；**语种识别也自动改由当前后端（qwen-max）完成**——识别走 `backends.classify()` 抽象层，不依赖 `LOCAL_NPU_*` 是否配置。
- 实测：`BACKEND=dashscope` 下不带 `languageType` 的英文请求约 **2.1s** 返回 `code:0`（识别 + 翻译共两次云调用），**无 IPv6 SYN 惩罚**（`PREFER_IPV4` 生效）。
- 前提：`.env` 里 `DASHSCOPE_API_KEY` 为**真实密钥**（`/health` 的 `api_key_valid:true`）；占位符会 `api_key_valid:false` 并 `code:500` 快速失败。
- 回滚回 local_npu：`BACKEND` 改回 `local_npu` 再重启，`/health` 复验 `backend=local_npu`、`model=Qwen3.6-35B-A3B`。

---

## 六、接口一览

| 接口 | 方法 | 路径 | 鉴权 |
|---|---|---|---|
| 健康检查 | GET | `/health` | 否 |
| 标准法规翻译 | POST | `/openApi/translate/law` | 是 |
| 术语库列表 | GET | `/openApi/terminology/list` | 是 |
| 企标编写（占位）| GET/POST | `/openApi/standard/write` | — |
| 培训PPT生成（占位）| GET/POST | `/openApi/ppt/generate` | — |
| 术语提取（占位）| GET/POST | `/openApi/terminology/extract` | — |

**translateType**：字符串 `"1"`（文本）/ `"2"`（文档，本期返回 404）。
**languageType**：`EN-CN / DE-CN / FR-CN / ES-CN / RU-CN / AR-CN / TH-CN`（未知取值 → `code:422` 并列出枚举）。

### 术语处理
- `originalTerminology / translateTerminology` → 内部 `source_term / target_term`，**一律按 `priority=high` 硬约束**注入 `required_target_terms`。
- **冲突规则**：请求内术语优先，本地 CSV 补充，同一 `source_term` 冲突以请求方为准，并记 INFO 日志（含 request_id 与两边译法）。
- 匹配复用 `termbase.match_terms()`（大小写不敏感、词边界、长术语优先、已去重）。
- 译后用 `target_present()` 校验，未命中记 WARNING，**不做强制字符串替换**（避免破坏中文语序）。

### 输入上限 & 输出截断（承诺值 + 保护）
- **输入上限** `MAX_TEXT_CHARS=8000` 字符。qwen-max ~32k token 上下文，扣除输出与 prompt 开销后仍有大量余量；取 8000 作保守承诺值。超长返回 `code:422`，本期不做切分。
- **输出上限（防截断）**：英译中一段长文本约需数千输出 token，固定 `max_tokens=2048` 会被**静默截断**。现改为 **按输入长度动态计算** `max_tokens`：`min(8192, max(4096, ceil(输入字符数 × 1.2)))`。
- **截断检测**：每次调用检查模型返回的 `finish_reason`，若为 `length` 说明触顶被截，直接返回 `code:500`，msg 写明"译文超长被截断"，**绝不静默返回半截译文**。

---

## 七、排障 checklist

### A. 服务起不来
1. `systemctl --user status translation-api` 看退出码；`journalctl --user -u translation-api --since "5 min ago"` 看堆栈。
2. venv 是否装好：`/data/SERVICE_USER/translation-api/venv/bin/python -c "import fastapi, uvicorn, dashscope"`。
3. `.env` 是否存在且可读：`ls -l PROJECT_ROOT/.env`（应 `-rw-------`）。
4. 端口占用：`ss -ltnp | grep 8188`，撞端口就改 `.env` 的 `PORT` 再 restart。
5. `PYTHONPATH` 是否含项目根（unit 里 `Environment=PYTHONPATH=...`），否则 `import scripts.common` 失败。

### B. 翻译报错（接口通但 `code:500`）
1. `tail -f /data/SERVICE_USER/translation-api/logs/api.log` 找对应 `request_id` 的堆栈。
2. `BACKEND=dashscope`：确认 `DASHSCOPE_API_KEY` 已由 EnvironmentFile 注入（`systemctl --user show translation-api -p EnvironmentFiles`），并确认机器能出公网到 `dashscope.aliyuncs.com`。
3. `BACKEND=local_npu`：确认 `LOCAL_NPU_BASE_URL` 可达、模型名正确。
4. 超时/限流：调大 `.env` 的 `TIMEOUT` 或减小并发；日志里 `[RETRY]` 表示已重试。
5. **单次翻译异常慢（~63s 固定，与文本长度无关）**：几乎必然是 IPv6→dashscope 不通、Python 在 IPv6 SYN 上卡满 `tcp_syn_retries` 才回退 IPv4。确认 `.env` 里 `PREFER_IPV4=true`（默认已开，`api/net.py` 把 getaddrinfo 的 IPv4 排前）。验证：`getent ahostsv6 dashscope.aliyuncs.com` 若有 AAAA 但 `curl -6 --max-time 5 https://dashscope.aliyuncs.com` 超时，即坐实。修好后单次应为 1~3s（短文本）。

---

## 八、在 scripts/ 批处理翻译里复用 IPv4 修复（重要）

`PREFER_IPV4` 修复**只作用于本 API 进程**。如果直接跑 `scripts/` 里的批处理翻译脚本
（如 `scripts/translation/qwenmax_translate.py`），**会重新吃到 ~63s/次** 的 IPv6 SYN 超时。

三种启用方式，任选其一：

**① 启动器（推荐，零改动 scripts/）**——用 `api/run_with_ipv4.py` 包一层：
```bash
/data/miniconda3/envs/ascend/bin/python api/run_with_ipv4.py \
    scripts/translation/qwenmax_translate.py --input data/... --output-dir data/...
```
它在进程早期装上和本服务一样的 IPv4-first 补丁，再把控制权交给原脚本。纯标准库、任何环境可用。

**② 脚本内两行（若愿意在脚本顶部加）**：
```python
import sys; sys.path.insert(0, "PROJECT_ROOT")
from api.net import install_ipv4_first; install_ipv4_first()   # 必须在 import dashscope / 首次调用前
```

**③ 系统级（需管理员，一劳永逸，全机生效）**：编辑 `/etc/gai.conf`，取消注释或加入
```
precedence ::ffff:0:0/96  100
```
让 IPv4 优先级高于 IPv6；或 `sysctl -w net.ipv6.conf.all.disable_ipv6=1`（更激进）。这两者对所有进程生效，之后本 API 的 `PREFER_IPV4` 也可保持开启（幂等无副作用）。

### C. 国创访问不通（本机自测通但外部不通）
1. 服务确实监听 `0.0.0.0`：`ss -ltnp | grep 8188` 应是 `0.0.0.0:8188` 而非 `127.0.0.1`。
2. 本机自测：`curl -s http://127.0.0.1:8188/health`。
3. 外部联调走 SSH 隧道自测：本地 `ssh -L 8188:127.0.0.1:8188 <NPU_HOST>`，再 `curl http://127.0.0.1:8188/health`。（`<NPU_HOST>` 是作者本地 `~/.ssh/config` 里的别名，请替换为你自己的连接方式。）
4. NAT / 端口转发 / 外网可达性由国创侧负责，本服务不处理。
5. token 不对会返回 `code:401`（HTTP 仍 200），先用自测 token 验证链路。
