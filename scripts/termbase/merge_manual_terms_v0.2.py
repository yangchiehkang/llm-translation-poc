import csv
import re
from pathlib import Path

BASE_PATH = Path("termbase/auto_regulation_terms_v0.2.csv")
NEW_PATH = Path("termbase/manual_extracted_terms_v0.2.csv")
OUT_PATH = BASE_PATH

FIELDS = [
    "term_id",
    "source_lang",
    "target_lang",
    "source_term",
    "target_term",
    "domain",
    "priority",
    "alias",
    "note",
    "status",
]

HIGH_DOMAINS = {
    "general_regulation",
    "vehicle_general",
    "vehicle_safety",
    "seatbelt_restraint",
    "seat_headrest",
    "seatbelt_reminder",
    "ev_safety",
}

MEDIUM_DOMAINS = {
    "testing",
    "legal_expression",
}

HIGH_TERMS = {
    "un regulation",
    "type approval",
    "approval mark",
    "contracting party",
    "technical service",
    "type approval authority",
    "conformity of production",
    "transitional provisions",
    "series of amendments",
    "requirements",
    "test procedure",
    "shall",
    "mandatory",
    "vehicle",
    "vehicle category",
    "occupant",
    "driver",
    "safety-belt",
    "seat-belt",
    "restraint system",
    "child restraint system",
    "isofix child restraint system",
    "i-size child restraint system",
    "safety-belt reminder",
    "webbing",
    "buckle",
    "anchorage",
    "three-point belt",
    "retractor",
    "emergency locking retractor",
    "pre-loading device",
    "dynamic test",
    "sled test",
    "dummy",
    "manikin",
    "airbag",
    "rearward-facing child restraint",
    "seat",
    "seat assembly",
    "seat anchorage",
    "seat-back",
    "head restraint",
    "h-point",
    "r-point",
    "injury criteria",
    "electric power train",
    "rechargeable electrical energy storage system",
    "reess",
    "high voltage",
    "high voltage bus",
    "live part",
    "direct contact",
    "indirect contact",
    "protection against electrical shock",
    "isolation resistance",
    "working voltage",
    "charging interlock",
    "active driving possible mode",
    "state of charge",
    "thermal runaway",
    "thermal propagation",
    "thermal event warning",
    "external short circuit",
    "overcharge protection",
    "over-discharge protection",
    "over-temperature protection",
    "overcurrent protection",
    "electrolyte leakage",
}

LOW_TERMS = {
    "appendix",
    "paragraph",
    "scope",
    "may",
    "not obliged to",
    "not compulsory",
    "warning",
    "ventilation",
    "cooling system",
}

def clean(value):
    if value is None:
        return ""
    return str(value).strip()

def normalize_key(row):
    return (
        clean(row.get("source_lang")).lower(),
        clean(row.get("target_lang")).lower(),
        clean(row.get("source_term")).lower(),
    )

def detect_next_en_id(rows):
    max_id = 0
    pattern = re.compile(r"^en_(\d+)$")
    for row in rows:
        term_id = clean(row.get("term_id"))
        m = pattern.match(term_id)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id + 1

def assign_priority(row):
    source_term = clean(row.get("source_term")).lower()
    domain = clean(row.get("domain")).lower()
    current = clean(row.get("priority")).lower()

    if source_term in HIGH_TERMS:
        return "high"

    if source_term in LOW_TERMS:
        return "low"

    if domain == "testing":
        if source_term.endswith("test") or " test" in source_term:
            return "high"
        return "medium"

    if domain == "legal_expression":
        if source_term in {"shall", "must", "mandatory"}:
            return "high"
        return "medium"

    if domain in HIGH_DOMAINS:
        if current == "medium":
            return "medium"
        return "high"

    if current in {"high", "medium", "low"}:
        return current

    return "medium"

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: clean(row.get(field)) for field in FIELDS})

def main():
    if not BASE_PATH.exists():
        raise FileNotFoundError(BASE_PATH)

    if not NEW_PATH.exists():
        raise FileNotFoundError(NEW_PATH)

    base_rows = read_csv(BASE_PATH)
    new_rows = read_csv(NEW_PATH)

    existing_keys = {normalize_key(row) for row in base_rows}
    next_id = detect_next_en_id(base_rows)

    appended = []
    skipped = []

    for row in new_rows:
        source_lang = clean(row.get("source_lang")).lower()
        target_lang = clean(row.get("target_lang")).lower()
        source_term = clean(row.get("source_term"))
        target_term = clean(row.get("target_term"))

        if not source_lang or not target_lang or not source_term or not target_term:
            skipped.append((source_term, "missing_required_field"))
            continue

        key = normalize_key(row)
        if key in existing_keys:
            skipped.append((source_term, "duplicate_source_term"))
            continue

        normalized = {
            "term_id": f"en_{next_id:04d}" if source_lang == "en" and target_lang == "zh" else clean(row.get("term_id")),
            "source_lang": source_lang,
            "target_lang": target_lang,
            "source_term": source_term,
            "target_term": target_term,
            "domain": clean(row.get("domain")),
            "priority": assign_priority(row),
            "alias": clean(row.get("alias")),
            "note": clean(row.get("note")),
            "status": clean(row.get("status")).lower() or "active",
        }

        if normalized["status"] not in {"active", "review", "deprecated"}:
            normalized["status"] = "active"

        appended.append(normalized)
        existing_keys.add(key)
        if source_lang == "en" and target_lang == "zh":
            next_id += 1

    final_rows = base_rows + appended
    write_csv(OUT_PATH, final_rows)

    print("base_rows:", len(base_rows))
    print("new_rows:", len(new_rows))
    print("appended:", len(appended))
    print("skipped:", len(skipped))
    print("final_rows:", len(final_rows))

    priority_count = {}
    for row in final_rows:
        p = clean(row.get("priority"))
        priority_count[p] = priority_count.get(p, 0) + 1

    print("priority_count:", priority_count)

    if skipped:
        print("skipped_items:")
        for item in skipped[:50]:
            print(item)

if __name__ == "__main__":
    main()
