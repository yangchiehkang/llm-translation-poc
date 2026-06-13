import csv
import re
import sys
from pathlib import Path

BASE_PATH = Path("termbase/auto_regulation_terms_v0.2.csv")

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

DEFAULT_INPUT_BY_LANG = {
    "en": Path("termbase/manual_extracted_terms_v0.2.csv"),
    "ru": Path("termbase/manual_extracted_ru_terms_v0.2.csv"),
    "es": Path("termbase/manual_extracted_es_terms_v0.2.csv"),
    "fr": Path("termbase/manual_extracted_fr_terms_v0.2.csv"),
    "de": Path("termbase/manual_extracted_de_terms_v0.2.csv"),
    "it": Path("termbase/manual_extracted_it_terms_v0.2.csv"),
    "no": Path("termbase/manual_extracted_no_terms_v0.2.csv"),
}

VALID_PRIORITY = {"high", "medium", "low"}
VALID_STATUS = {"active", "review", "deprecated"}

HIGH_DOMAINS = {
    "general_regulation",
    "vehicle_general",
    "vehicle_safety",
    "vehicle_regulation",
    "vehicle_inspection",
    "vehicle_approval",
    "vehicle_dimensions",
    "vehicle_powertrain",
    "vehicle_environment",
    "vehicle_lighting",
    "vehicle_equipment",
    "vehicle_identification",
    "vehicle_incentive",
    "vehicle_category",
    "vehicle_emissions",
    "vehicle_insurance",
    "vehicle_registration",
    "vehicle_technical",
    "vehicle_repair",
    "vehicle_enforcement",
    "road_traffic",
    "road_infrastructure",
    "road_transport",
    "road_enforcement",
    "road_violation",
    "road_safety",
    "road_crime",
    "road_data",
    "road_authority",
    "road_accident",
    "road_penalty",
    "road_maintenance",
    "driver_license",
    "driver_training",
    "transport_general",
    "transport_labor",
    "parking",
    "dui",
    "data_protection",
    "labor_protection",
    "seatbelt_restraint",
    "seat_headrest",
    "seatbelt_reminder",
    "ev_safety",
    "defrost_demisting",
    "hvac",
    "anti_theft",
    "adas",
    "vehicle_market",
    "transport_tachograph",
    "metrology",
    "environment_waste",
}

MEDIUM_DOMAINS = {
    "testing",
    "legal_expression",
}

LOW_TERMS = {
    # en
    "appendix",
    "paragraph",
    "scope",
    "may",
    "not obliged to",
    "not compulsory",
    "warning",
    "ventilation",
    "cooling system",

    # ru
    "таблица",
    "рисунок",
    "угол 180°",
    "этиловый спирт",
    "раствор аммиака",
    "капот",
    "дверь",
    "окно",
    "восковой карандаш",
    "латунь",
    "интервал времени",
    "пол",
    "диаметр отверстия",
    "толщина стенки",

    # es
    "punto final",
    "punto y coma",
    "frase",
    "software de diseño",
    "página web",
    "s.r.r.v.",
    "objetivos",

    # fr
    "deux minutes par jour",
    "sept jours",
    "chef du service",
    "par empêchement",

    # it
    "gara atletica",
}

def clean(value):
    if value is None:
        return ""
    return str(value).strip()

def normalize_space(value):
    return re.sub(r"\s+", " ", clean(value))

def normalize_key(row):
    return (
        clean(row.get("source_lang")).lower(),
        clean(row.get("target_lang")).lower(),
        normalize_space(row.get("source_term")).lower(),
    )

def detect_next_id(rows, lang):
    max_id = 0
    pattern = re.compile(rf"^{re.escape(lang)}_(\d+)$")

    for row in rows:
        term_id = clean(row.get("term_id"))
        match = pattern.match(term_id)
        if match:
            max_id = max(max_id, int(match.group(1)))

    return max_id + 1

def assign_priority(row):
    source_term = normalize_space(row.get("source_term")).lower()
    domain = clean(row.get("domain")).lower()
    current = clean(row.get("priority")).lower()

    if source_term in LOW_TERMS:
        return "low"

    if current in VALID_PRIORITY:
        return current

    if domain in MEDIUM_DOMAINS:
        return "medium"

    if domain in HIGH_DOMAINS:
        return "high"

    return "medium"

def normalize_term_id(row, next_id_by_lang):
    source_lang = clean(row.get("source_lang")).lower()
    target_lang = clean(row.get("target_lang")).lower()

    if target_lang != "zh":
        return clean(row.get("term_id"))

    if source_lang not in next_id_by_lang:
        next_id_by_lang[source_lang] = 1

    term_id = f"{source_lang}_{next_id_by_lang[source_lang]:04d}"
    next_id_by_lang[source_lang] += 1

    return term_id

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()

        for row in rows:
            writer.writerow({
                field: clean(row.get(field))
                for field in FIELDS
            })

def validate_header(rows, path):
    if not rows:
        raise ValueError(f"empty input file: {path}")

    missing = [
        field for field in FIELDS
        if field not in rows[0]
    ]

    if missing:
        raise ValueError(f"missing fields in {path}: {missing}")

def resolve_input_path():
    if len(sys.argv) >= 2:
        arg = sys.argv[1].strip()

        if arg in DEFAULT_INPUT_BY_LANG:
            return DEFAULT_INPUT_BY_LANG[arg]

        return Path(arg)

    return DEFAULT_INPUT_BY_LANG["no"]

def main():
    input_path = resolve_input_path()

    if not BASE_PATH.exists():
        raise FileNotFoundError(BASE_PATH)

    if not input_path.exists():
        raise FileNotFoundError(input_path)

    base_rows = read_csv(BASE_PATH)
    new_rows = read_csv(input_path)

    validate_header(base_rows, BASE_PATH)
    validate_header(new_rows, input_path)

    existing_keys = {
        normalize_key(row)
        for row in base_rows
    }

    langs = sorted({
        clean(row.get("source_lang")).lower()
        for row in new_rows
        if clean(row.get("source_lang"))
    })

    next_id_by_lang = {
        lang: detect_next_id(base_rows, lang)
        for lang in langs
    }

    appended = []
    skipped = []

    for row in new_rows:
        source_lang = clean(row.get("source_lang")).lower()
        target_lang = clean(row.get("target_lang")).lower()
        source_term = normalize_space(row.get("source_term"))
        target_term = normalize_space(row.get("target_term"))

        if not source_lang or not target_lang or not source_term or not target_term:
            skipped.append((source_term, "missing_required_field"))
            continue

        key = normalize_key(row)

        if key in existing_keys:
            skipped.append((source_term, "duplicate_source_term"))
            continue

        normalized = {
            "term_id": normalize_term_id(row, next_id_by_lang),
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

        if normalized["priority"] not in VALID_PRIORITY:
            normalized["priority"] = "medium"

        if normalized["status"] not in VALID_STATUS:
            normalized["status"] = "active"

        appended.append(normalized)
        existing_keys.add(key)

    final_rows = base_rows + appended
    write_csv(BASE_PATH, final_rows)

    print("input_path:", input_path)
    print("base_rows:", len(base_rows))
    print("new_rows:", len(new_rows))
    print("appended:", len(appended))
    print("skipped:", len(skipped))
    print("final_rows:", len(final_rows))

    priority_count = {}
    status_count = {}
    lang_count = {}

    for row in final_rows:
        priority = clean(row.get("priority"))
        status = clean(row.get("status"))
        lang = clean(row.get("source_lang"))

        priority_count[priority] = priority_count.get(priority, 0) + 1
        status_count[status] = status_count.get(status, 0) + 1
        lang_count[lang] = lang_count.get(lang, 0) + 1

    print("priority_count:", priority_count)
    print("status_count:", status_count)
    print("source_lang_count:", lang_count)

    if skipped:
        print("skipped_items:")
        for item in skipped[:100]:
            print(item)

if __name__ == "__main__":
    main()
