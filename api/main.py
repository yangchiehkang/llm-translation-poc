# FastAPI 应用：只做包装，直接 import 现有翻译/术语函数。
# 统一 {code,msg,data}，HTTP 一律 200；全局异常处理器兜住 FastAPI 默认 422。

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# scripts.common 依赖项目根在 sys.path 上（与 scripts/translation/qwenmax_translate.py 同款处理）。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import CONFIG
# 在任何模型调用之前，先按需装上 IPv4-first 修正（消除 dashscope IPv6 SYN 卡顿）。
if CONFIG.PREFER_IPV4:
    from api.net import install_ipv4_first
    install_ipv4_first()
from api.contract import (
    ApiError, json_ok, json_result,
    CODE_OK, CODE_NOT_FOUND, CODE_INVALID_PARAM, CODE_INTERNAL,
)
from api.auth import require_bearer
from api.languages import resolve_language_type, canonical_language_type, SUPPORTED_LANGUAGE_TYPES
from api.logging_setup import setup_logging, clip_source
from api import terms as term_service
from api import backends
from api.backends.base import TranslationTruncated
from api.langdetect import detect_language, LanguageDetectionError
from scripts.common.io_utils import read_csv
from scripts.common.text_utils import utc_now

setup_logging()
logger = logging.getLogger("api.main")

app = FastAPI(title="港中深法规翻译 API 包装层", version="1.0")


# ----------------------------------------------------------------------------
# 全局异常处理器：任何异常都转成 {code,msg,data}，HTTP 200，禁止 {"detail":[...]} 漏出。
# ----------------------------------------------------------------------------
@app.exception_handler(ApiError)
async def _handle_api_error(request: Request, exc: ApiError):
    return json_result(exc.code, exc.msg, exc.data)


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(request: Request, exc: RequestValidationError):
    # 兜住 FastAPI 默认 422：把 pydantic 的 errors 压成一句人读的 msg。
    try:
        parts = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
            parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        msg = "参数校验失败：" + "; ".join(parts) if parts else "参数校验失败"
    except Exception:
        msg = "参数校验失败"
    return json_result(CODE_INVALID_PARAM, msg, None)


@app.exception_handler(StarletteHTTPException)
async def _handle_http_exception(request: Request, exc: StarletteHTTPException):
    code = exc.status_code if exc.status_code in {401, 403, 404, 422, 500} else CODE_INTERNAL
    return json_result(code, str(exc.detail), None)


@app.exception_handler(Exception)
async def _handle_unexpected(request: Request, exc: Exception):
    logger.exception("unhandled error path=%s", request.url.path)
    return json_result(CODE_INTERNAL, f"服务端内部错误: {exc}", None)


# ----------------------------------------------------------------------------
# 请求解析：同一个 law 路由要同时收 JSON 与 multipart。
# ----------------------------------------------------------------------------
async def _parse_law_request(request: Request) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    fields: dict[str, Any] = {
        "originalText": None,
        "languageType": None,
        "terminologyList": None,
        "translateType": None,
        "has_terminology_key": False,
        "file_present": False,
        "file_source": None,   # multipart | base64
    }

    if "multipart/form-data" in content_type:
        form = await request.form()
        fields["originalText"] = form.get("originalText")
        fields["languageType"] = form.get("languageType")
        fields["translateType"] = form.get("translateType")
        if "terminologyList" in form:
            fields["has_terminology_key"] = True
            raw = form.get("terminologyList")
            fields["terminologyList"] = _coerce_term_list(raw)
        upload = form.get("originalFile")
        if upload is not None and hasattr(upload, "filename"):
            fields["file_present"] = True
            fields["file_source"] = "multipart"
        return fields

    if "application/x-www-form-urlencoded" in content_type:
        # 表单编码不受支持（文档要求 Content-Type: application/json）。按 JSON 解析必然
        # 失败并报"请求体不是合法 JSON"，那句话指不到真正的原因；这里直接点破。
        raise ApiError(
            CODE_INVALID_PARAM,
            "不支持 application/x-www-form-urlencoded；请用 Content-Type: application/json 提交 JSON 请求体",
        )

    # 默认按 JSON 解析
    raw_body = await request.body()
    if not raw_body:
        body: dict[str, Any] = {}
    else:
        try:
            body = json.loads(raw_body)
        except Exception:
            raise ApiError(CODE_INVALID_PARAM, "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise ApiError(CODE_INVALID_PARAM, "请求体必须是 JSON 对象")

    fields["originalText"] = body.get("originalText")
    fields["languageType"] = body.get("languageType")
    fields["translateType"] = body.get("translateType")
    if "terminologyList" in body:
        fields["has_terminology_key"] = True
        fields["terminologyList"] = _coerce_term_list(body.get("terminologyList"))
    # base64 文档入口
    b64 = body.get("originalFileBase64") or body.get("originalFile")
    if b64:
        fields["file_present"] = True
        fields["file_source"] = "base64"
        fields["_file_b64"] = b64
    return fields


def _coerce_term_list(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            raw = json.loads(raw)
        except Exception:
            raise ApiError(CODE_INVALID_PARAM, "terminologyList 不是合法 JSON 数组")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ApiError(CODE_INVALID_PARAM, "terminologyList 必须是数组")
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def _detect_terms_translate(
    original_text: str,
    resolved: tuple[str, str] | None,
    request_terms: list[dict[str, str]],
    request_id: str,
) -> tuple[str, str, str, list[dict[str, Any]], str | None]:
    # 线程池里串起：语种识别（若 languageType 未显式传入）-> 术语合并/匹配 -> 后端翻译。
    # 三者放同一函数，是为了让识别耗时与翻译耗时共享外层单个 asyncio.wait_for(TIMEOUT) 预算。
    if resolved is not None:
        src_lang, tgt_lang = resolved
        detected_type: str | None = None
    else:
        detected_type = detect_language(original_text, request_id)  # 失败抛 LanguageDetectionError
        src_lang, tgt_lang = resolve_language_type(detected_type)  # 识别结果必在枚举内
    merged = term_service.build_termbase(request_terms, src_lang, tgt_lang, request_id)
    matched = term_service.match(original_text, merged)
    try:
        translation = backends.translate(original_text, src_lang, tgt_lang, matched)
    except Exception as exc:
        # 术语已在此算完；把真实匹配数带到异常上，让上层错误日志不至于记成 0。
        # （识别失败发生在匹配之前、无此属性 -> 上层取默认 0，正好是"未匹配"的真实值。）
        exc.matched_count = len(matched)  # type: ignore[attr-defined]
        raise
    # usage 必须在**同一线程**里取（thread-local），所以在这里读、随返回值带出去。
    return translation, src_lang, tgt_lang, matched, detected_type, backends.last_usage()


# ----------------------------------------------------------------------------
# 对外健康检查的内网地址脱敏
# ----------------------------------------------------------------------------
_INTERNAL_MASK = "<内部地址>"


def _mask_internal(text: str | None, raw_url: str) -> str | None:
    # 把 detail 里出现的后端地址（完整 URL 与 host:port 两种形态）替换成占位符。
    # reachable() 失败时会把 URL 拼进 detail（"…/models 返回 HTTP 503"），
    # 那正是调用方最可能读到这个字段的时刻，只打 base_url 等于没打。
    if not text or not raw_url:
        return text
    out = text.replace(raw_url, _INTERNAL_MASK)
    host = raw_url.split("//", 1)[-1].split("/", 1)[0]
    return out.replace(host, _INTERNAL_MASK) if host else out


def _public_backend_view(info: dict[str, Any], detail: str | None) -> tuple[dict[str, Any], str | None]:
    """/health 是免鉴权的对外端点，后端地址属内网拓扑，不随健康检查外泄。

    接口文档里这个字段本身就是打码的（"base_url":"<内部地址>"），此处让实际响应与
    文档示例逐字对齐。需要真实地址排障时用 /health/deep（内部监控专用、不在对外文档里）。
    """
    masked = dict(info)
    raw_url = str(info.get("base_url") or "")
    if raw_url:
        masked["base_url"] = _INTERNAL_MASK
    return masked, _mask_internal(detail, raw_url)


# ----------------------------------------------------------------------------
# 接口 4：GET /health（不鉴权）
# ----------------------------------------------------------------------------
@app.get("/health")
async def health():
    """契约端点。**永远 HTTP 200、永远 code:0**，探测失败也不例外。

    国创的集成测试可能把非 200 当失败，一次后端抖动就会让他们的用例红掉——
    那是拿契约行为换可观测性。所以这里只**增加**两个字段，不改状态码、不改 code。
    需要"不通就红"的语义，用 /health/deep（内部监控专用，不写进对外文档）。
    """
    backend = backends.get_backend()
    ok, detail = await run_in_threadpool(backend.reachable, 2.0)
    info, detail = _public_backend_view(backend.info(), detail)
    return json_ok({
        "status": "ok",
        "backend": CONFIG.BACKEND,
        "backend_info": info,
        # configured 只说明配置填没填；backend_reachable 才说明此刻能不能用。
        # 2026-07-28 后端消失 5 天而 /health 一直 200，就是因为只有前者。
        "backend_reachable": ok,
        "backend_check_detail": detail,
        "backend_checked_at": utc_now(),
        "law_path": CONFIG.LAW_PATH,
        "supported_language_types": SUPPORTED_LANGUAGE_TYPES,
        "max_text_chars": CONFIG.MAX_TEXT_CHARS,
    })


@app.get("/health/deep")
async def health_deep():
    """深检：后端不通就返回 **HTTP 503**。内部监控专用，不写进给国创的接口文档。

    与 /health 的分工：/health 守契约（永远 200），/health/deep 守真相（不通就红）。
    地址**不脱敏**：这个端点不对外、不在文档里，排障就是要看见后端到底指着哪个地址
    （07-28 那次静默中断就是靠它定位的）。对外脱敏在 /health，别把这里也一起打码。
    """
    backend = backends.get_backend()
    ok, detail = await run_in_threadpool(backend.reachable, 2.0)
    payload = {
        "status": "ok" if ok else "backend_unreachable",
        "backend": CONFIG.BACKEND,
        "backend_info": backend.info(),
        "backend_reachable": ok,
        "backend_check_detail": detail,
        "backend_checked_at": utc_now(),
    }
    if ok:
        return json_ok(payload)
    return JSONResponse(status_code=503,
                        content={"code": CODE_INTERNAL, "msg": f"后端不可达：{detail}",
                                 "data": payload})


# ----------------------------------------------------------------------------
# 接口 1：标准法规翻译 POST {LAW_PATH}
# ----------------------------------------------------------------------------
@app.post(CONFIG.LAW_PATH)
async def translate_law(request: Request):
    request_id = uuid.uuid4().hex[:12]
    started = time.time()
    require_bearer(request)

    fields = await _parse_law_request(request)
    translate_type = fields["translateType"]
    language_type = fields["languageType"]

    # translateType 是字符串 "1"/"2"
    if translate_type is None:
        raise ApiError(CODE_INVALID_PARAM, "缺少 translateType（字符串 '1' 文本翻译 / '2' 文档翻译）")
    translate_type = str(translate_type)
    if translate_type not in {"1", "2"}:
        raise ApiError(CODE_INVALID_PARAM, f"translateType 只支持 '1'（文本）或 '2'（文档），收到 {translate_type!r}")

    # languageType 现在选填：显式传入即校验映射，未知取值 422 且列出枚举；
    # 缺省（None/空）留到文本路径里做识别，此处不报错。
    resolved = resolve_language_type(language_type) if language_type else None
    if language_type and resolved is None:
        raise ApiError(
            CODE_INVALID_PARAM,
            f"不支持的 languageType={language_type!r}，支持的枚举：{SUPPORTED_LANGUAGE_TYPES}",
        )

    if translate_type == "2":
        # multipart / base64 两种入口都收下并校验参数，但本期返回 404。
        # 文档路径无正文可识别；languageType 缺省与否都不影响本期未开放响应。
        if not fields["file_present"]:
            raise ApiError(CODE_INVALID_PARAM, "translateType='2' 需要上传 originalFile（multipart）或 originalFileBase64（JSON）")
        _validate_doc_payload(fields)
        _log_request(request_id, CONFIG.LAW_PATH, translate_type, language_type, 0, 0, started, "doc_not_open")
        raise ApiError(CODE_NOT_FOUND, "文档翻译暂未开放，当前仅支持文本翻译")

    # ---- translateType == "1"：文本翻译 ----
    original_text = fields["originalText"]
    if original_text is None or str(original_text).strip() == "":
        raise ApiError(CODE_INVALID_PARAM, "translateType='1' 时 originalText 不能为空")
    original_text = str(original_text)
    # 顺序：先做长度上限校验，再做语种识别——不给超长文本白跑一趟识别。
    if len(original_text) > CONFIG.MAX_TEXT_CHARS:
        raise ApiError(
            CODE_INVALID_PARAM,
            f"originalText 长度 {len(original_text)} 超过上限 {CONFIG.MAX_TEXT_CHARS} 字符（本期不做切分）",
        )

    # terminologyList 选填，缺省空数组（字段可不传）。
    request_terms = fields["terminologyList"] or []

    # 识别（若需）-> 术语合并 -> 匹配 -> 翻译 全部放同一线程池调用，由单个 asyncio.wait_for(TIMEOUT)
    # 兜底：识别耗时计入同一预算、不单独计时。实测 dashscope SDK 的 timeout 入参不生效，本层硬超时才是真兜底；
    # 超时后本请求立即返回干净 code:500，事件循环与连接释放，底层线程自行跑完并丢弃结果，不阻塞新请求。
    try:
        translation, src_lang, tgt_lang, matched, detected_type, usage = await asyncio.wait_for(
            run_in_threadpool(
                _detect_terms_translate, original_text, resolved, request_terms, request_id,
            ),
            timeout=CONFIG.TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("translation timeout request_id=%s timeout=%ss src_len=%s",
                     request_id, CONFIG.TIMEOUT, len(original_text))
        _log_request(request_id, CONFIG.LAW_PATH, translate_type, language_type,
                     len(original_text), 0, started, "timeout",
                     source_text=original_text)
        raise ApiError(CODE_INTERNAL, f"翻译超时：超过 {CONFIG.TIMEOUT}s 未返回，请缩短文本或稍后重试")
    except LanguageDetectionError as exc:
        # 识别失败：绝不静默 fallback 到 EN-CN（会让本地术语库按错误 source_lang 静默丢术语）。
        logger.warning("language detection failed request_id=%s %s", request_id, exc)
        _log_request(request_id, CONFIG.LAW_PATH, translate_type, language_type,
                     len(original_text), 0, started, "lang_undetected",
                     source_text=original_text)
        raise ApiError(CODE_INVALID_PARAM, str(exc))
    except TranslationTruncated as exc:
        # 译文被截断：绝不静默返回半截译文，明确报错。
        logger.error("translation truncated request_id=%s %s", request_id, exc)
        _log_request(request_id, CONFIG.LAW_PATH, translate_type, language_type,
                     len(original_text), getattr(exc, "matched_count", 0), started, "truncated",
                     source_text=original_text)
        raise ApiError(CODE_INTERNAL, f"译文超长被截断: {exc}")
    except Exception as exc:
        # 区分超时与其它错误：超时给明确中文 msg，并在日志打 status=timeout。
        low = str(exc).lower()
        is_timeout = ("timeout" in low) or ("timed out" in low) or ("超时" in str(exc))
        status = "timeout" if is_timeout else "error"
        logger.exception("translate %s request_id=%s", status, request_id)
        _log_request(request_id, CONFIG.LAW_PATH, translate_type, language_type,
                     len(original_text), getattr(exc, "matched_count", 0), started, status,
                     source_text=original_text)
        if is_timeout:
            raise ApiError(
                CODE_INTERNAL,
                f"翻译超时：后端在 {CONFIG.TIMEOUT}s×{CONFIG.RETRIES} 次尝试内未返回，请缩短文本或稍后重试",
            )
        raise ApiError(CODE_INTERNAL, f"翻译失败: {exc}")

    term_service.verify_targets(translation, matched, request_id)
    # detectedLanguageType：显式传入回显其枚举原形（" en-cn " -> "EN-CN"，不原样退回
    # 调用方的大小写/空格）；未传则回显识别结果。两条路径都保证落在对外公布的枚举里。
    echo_type = canonical_language_type(language_type) if resolved is not None else detected_type
    _log_request(request_id, CONFIG.LAW_PATH, translate_type, echo_type,
                 len(original_text), len(matched), started, "ok",
                 source_text=original_text, usage=usage)
    return json_ok({"translateText": translation, "detectedLanguageType": echo_type})


def _validate_doc_payload(fields: dict[str, Any]) -> None:
    # 文档入口即便本期不翻译，也把参数校验做扎实，方便国创验证上传通道。
    if fields["file_source"] == "base64":
        b64 = fields.get("_file_b64")
        try:
            base64.b64decode(str(b64), validate=True)
        except Exception:
            raise ApiError(CODE_INVALID_PARAM, "originalFileBase64 不是合法 base64")


# ----------------------------------------------------------------------------
# 接口 2：术语库列表 GET {TERMINOLOGY_LIST_PATH}
# ----------------------------------------------------------------------------
@app.get(CONFIG.TERMINOLOGY_LIST_PATH)
async def terminology_list(request: Request, languageType: str | None = None, limit: int | None = None):
    require_bearer(request)
    rows = read_csv(CONFIG.TERMBASE_PATH)

    wanted = resolve_language_type(languageType) if languageType else None
    items: list[dict[str, Any]] = []
    for row in rows:
        src = str(row.get("source_lang") or "").strip().lower()
        tgt = str(row.get("target_lang") or "").strip().lower()
        if wanted and (src, tgt) != wanted:
            continue
        items.append({
            "terminology": row.get("target_term", ""),                 # 中文
            "terminologyType": f"{src.upper()}-CN" if src else "",      # 语种类型
            "terminologyEn": row.get("source_term", ""),               # 外文
            "terminologyRemark": row.get("note", ""),                  # 说明
        })
    if limit and limit > 0:
        items = items[:limit]

    if CONFIG.TERMINOLOGY_LIST_AS_OBJECT:
        # 配置开关：切回单对象（文档响应示例是单对象）
        return json_ok(items[0] if items else None)
    return json_ok(items)


# ----------------------------------------------------------------------------
# 接口 3：其余接口占位（企标编写 / PPT 生成 / 术语提取）
# ----------------------------------------------------------------------------
def _not_implemented():
    return json_result(CODE_NOT_FOUND, "接口尚未实现", None)


# 占位接口同样鉴权：对外文档写的是"/health 免鉴权，其余业务接口均需携带"。
# 带上 token 后仍返 code:404「接口尚未实现」，与文档的占位状态表一致。
@app.api_route("/openApi/standard/write", methods=["GET", "POST"])
async def standard_write(request: Request):
    require_bearer(request)
    return _not_implemented()


@app.api_route("/openApi/ppt/generate", methods=["GET", "POST"])
async def ppt_generate(request: Request):
    require_bearer(request)
    return _not_implemented()


@app.api_route("/openApi/terminology/extract", methods=["GET", "POST"])
async def terminology_extract(request: Request):
    require_bearer(request)
    return _not_implemented()


# ----------------------------------------------------------------------------
# 结构化请求日志
# ----------------------------------------------------------------------------
def _log_request(request_id, interface, translate_type, language_type,
                 src_len, term_count, started, status, source_text=None, usage=None):
    elapsed_ms = int((time.time() - started) * 1000)
    # prompt/completion_tokens 只进日志，不进响应体（对外契约无 token 字段）。
    # 延迟表与容量规划要它：字符数与 token 数不是线性关系，各语种膨胀率也不同，
    # 只看字符数推不出 max_tokens 余量。
    u = usage or {}
    logger.info(
        "request_id=%s interface=%s translateType=%s languageType=%s src_len=%s "
        "matched_terms=%s prompt_tokens=%s completion_tokens=%s elapsed_ms=%s status=%s src=%r",
        request_id, interface, translate_type, language_type, src_len,
        term_count, u.get("prompt_tokens"), u.get("completion_tokens"), elapsed_ms, status,
        clip_source(source_text) if source_text is not None else "",
    )
