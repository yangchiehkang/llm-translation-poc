import argparse
import csv
import hashlib
import json
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_OUTPUT = Path("outputs/translation_concurrent_poc_results.csv")
DEFAULT_REQUEST_LOG = Path("outputs/translation_concurrent_poc_request_log.csv")
DEFAULT_CACHE = Path("outputs/translation_concurrent_poc_cache.jsonl")
DEFAULT_SUMMARY = Path("outputs/translation_concurrent_poc_summary.json")


RESULT_FIELDS = [
    "request_id",
    "sample_id",
    "cache_key",
    "model",
    "prompt_version",
    "termbase_version",
    "source_lang",
    "target_lang",
    "source_text",
    "translation",
    "injected_terms",
    "cache_hit",
    "latency_ms",
    "attempt_count",
    "status",
    "error_type",
    "error_message",
    "created_at",
]

REQUEST_LOG_FIELDS = [
    "request_id",
    "sample_id",
    "cache_key",
    "cache_hit",
    "model",
    "prompt_version",
    "termbase_version",
    "source_lang",
    "target_lang",
    "source_text_hash",
    "injected_terms_hash",
    "worker_id",
    "attempt",
    "request_start_time",
    "request_end_time",
    "latency_ms",
    "status",
    "error_type",
    "error_message",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def stable_json_hash(obj):
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_terms(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    text = str(value).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    return [item.strip() for item in text.replace("；", ";").split(";") if item.strip()]


def build_cache_key(row, model, prompt_version, termbase_version):
    source_text = row.get("source_text", "")
    injected_terms = normalize_terms(row.get("injected_terms", ""))

    payload = {
        "model": model,
        "prompt_version": prompt_version,
        "termbase_version": termbase_version,
        "source_lang": row.get("source_lang", ""),
        "target_lang": row.get("target_lang", "zh"),
        "source_text_hash": sha256_text(source_text),
        "injected_terms_hash": stable_json_hash(injected_terms),
    }

    return stable_json_hash(payload), payload


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_cache(path):
    path = Path(path)
    cache = {}

    if not path.exists():
        return cache

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                cache[row["cache_key"]] = row
            except Exception:
                continue

    return cache


def mock_translate(source_text):
    time.sleep(random.uniform(0.2, 0.8))
    return f"[MOCK_ZH] {source_text}"


def call_translation_api(row, args):
    if args.mock:
        return mock_translate(row.get("source_text", ""))

    raise RuntimeError(
        "Real API call is not implemented in this POC. "
        "Integrate provider SDK or HTTP client on server."
    )


def translate_with_retry(row, args, cache_key, cache_payload, worker_id):
    request_id = str(uuid.uuid4())
    start_all = time.time()
    request_logs = []

    max_retries = args.max_retries
    backoff_base = args.backoff_base

    for attempt in range(1, max_retries + 1):
        request_start = now_iso()
        t0 = time.time()

        try:
            translation = call_translation_api(row, args)
            latency_ms = int((time.time() - t0) * 1000)
            request_end = now_iso()

            request_logs.append({
                "request_id": request_id,
                "sample_id": row.get("sample_id", ""),
                "cache_key": cache_key,
                "cache_hit": "false",
                "model": args.model,
                "prompt_version": args.prompt_version,
                "termbase_version": args.termbase_version,
                "source_lang": row.get("source_lang", ""),
                "target_lang": row.get("target_lang", "zh"),
                "source_text_hash": cache_payload["source_text_hash"],
                "injected_terms_hash": cache_payload["injected_terms_hash"],
                "worker_id": worker_id,
                "attempt": attempt,
                "request_start_time": request_start,
                "request_end_time": request_end,
                "latency_ms": latency_ms,
                "status": "success",
                "error_type": "",
                "error_message": "",
            })

            result = {
                "request_id": request_id,
                "sample_id": row.get("sample_id", ""),
                "cache_key": cache_key,
                "model": args.model,
                "prompt_version": args.prompt_version,
                "termbase_version": args.termbase_version,
                "source_lang": row.get("source_lang", ""),
                "target_lang": row.get("target_lang", "zh"),
                "source_text": row.get("source_text", ""),
                "translation": translation,
                "injected_terms": row.get("injected_terms", ""),
                "cache_hit": "false",
                "latency_ms": int((time.time() - start_all) * 1000),
                "attempt_count": attempt,
                "status": "success",
                "error_type": "",
                "error_message": "",
                "created_at": now_iso(),
            }

            return result, request_logs

        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            request_end = now_iso()
            error_type = type(exc).__name__
            error_message = str(exc)

            request_logs.append({
                "request_id": request_id,
                "sample_id": row.get("sample_id", ""),
                "cache_key": cache_key,
                "cache_hit": "false",
                "model": args.model,
                "prompt_version": args.prompt_version,
                "termbase_version": args.termbase_version,
                "source_lang": row.get("source_lang", ""),
                "target_lang": row.get("target_lang", "zh"),
                "source_text_hash": cache_payload["source_text_hash"],
                "injected_terms_hash": cache_payload["injected_terms_hash"],
                "worker_id": worker_id,
                "attempt": attempt,
                "request_start_time": request_start,
                "request_end_time": request_end,
                "latency_ms": latency_ms,
                "status": "retry" if attempt < max_retries else "failed",
                "error_type": error_type,
                "error_message": error_message,
            })

            if attempt < max_retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
            else:
                result = {
                    "request_id": request_id,
                    "sample_id": row.get("sample_id", ""),
                    "cache_key": cache_key,
                    "model": args.model,
                    "prompt_version": args.prompt_version,
                    "termbase_version": args.termbase_version,
                    "source_lang": row.get("source_lang", ""),
                    "target_lang": row.get("target_lang", "zh"),
                    "source_text": row.get("source_text", ""),
                    "translation": "",
                    "injected_terms": row.get("injected_terms", ""),
                    "cache_hit": "false",
                    "latency_ms": int((time.time() - start_all) * 1000),
                    "attempt_count": attempt,
                    "status": "failed",
                    "error_type": error_type,
                    "error_message": error_message,
                    "created_at": now_iso(),
                }
                return result, request_logs


def build_sample_rows():
    return [
        {
            "sample_id": f"sample_{i:03d}",
            "source_lang": "en",
            "target_lang": "zh",
            "source_text": text,
            "injected_terms": "",
        }
        for i, text in enumerate([
            "The vehicle shall comply with the type approval requirements.",
            "The braking system shall meet the technical regulation.",
            "The REESS shall be protected against electric shock.",
            "The charging connector shall comply with applicable standards.",
            "The manufacturer shall submit the test report.",
            "The approval authority may request additional documents.",
            "The battery system shall pass the vibration test.",
            "The steering system shall operate normally.",
            "The lighting device shall be installed correctly.",
            "The conformity of production shall be verified.",
        ], start=1)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--request-log", default=str(DEFAULT_REQUEST_LOG))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--model", default="poc-model")
    parser.add_argument("--prompt-version", default="prompt_v3")
    parser.add_argument("--termbase-version", default="termbase_v0.3_candidate")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--backoff-base", type=float, default=2.0)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()

    if args.input:
        rows = read_csv(args.input)
    else:
        rows = build_sample_rows()

    rows = rows[: args.limit]

    cache = load_cache(args.cache)

    results = []
    request_logs = []
    pending = []

    total_start = time.time()

    for row in rows:
        cache_key, cache_payload = build_cache_key(
            row,
            args.model,
            args.prompt_version,
            args.termbase_version,
        )
        row["_cache_key"] = cache_key
        row["_cache_payload"] = cache_payload

        if cache_key in cache:
            cached = cache[cache_key]
            results.append({
                "request_id": cached.get("request_id", ""),
                "sample_id": row.get("sample_id", ""),
                "cache_key": cache_key,
                "model": args.model,
                "prompt_version": args.prompt_version,
                "termbase_version": args.termbase_version,
                "source_lang": row.get("source_lang", ""),
                "target_lang": row.get("target_lang", "zh"),
                "source_text": row.get("source_text", ""),
                "translation": cached.get("translation", ""),
                "injected_terms": row.get("injected_terms", ""),
                "cache_hit": "true",
                "latency_ms": 0,
                "attempt_count": 0,
                "status": "success",
                "error_type": "",
                "error_message": "",
                "created_at": now_iso(),
            })
        else:
            pending.append(row)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {}

        for idx, row in enumerate(pending, start=1):
            future = executor.submit(
                translate_with_retry,
                row,
                args,
                row["_cache_key"],
                row["_cache_payload"],
                idx % args.workers,
            )
            future_map[future] = row

        for future in as_completed(future_map):
            result, logs = future.result()
            results.append(result)
            request_logs.extend(logs)

            if result["status"] == "success":
                append_jsonl(args.cache, result)

    total_time_sec = round(time.time() - total_start, 3)

    write_csv(args.output, RESULT_FIELDS, results)
    write_csv(args.request_log, REQUEST_LOG_FIELDS, request_logs)

    completed = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    cache_hits = sum(1 for r in results if r["cache_hit"] == "true")
    cache_misses = len(rows) - cache_hits

    summary = {
        "total_samples": len(rows),
        "completed_samples": completed,
        "failed_samples": failed,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "total_time_sec": total_time_sec,
        "throughput_samples_per_min": round((completed / total_time_sec) * 60, 3) if total_time_sec else 0,
        "workers": args.workers,
        "max_retries": args.max_retries,
        "model": args.model,
        "prompt_version": args.prompt_version,
        "termbase_version": args.termbase_version,
        "mock": args.mock,
        "created_at": now_iso(),
    }

    Path(args.summary).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
