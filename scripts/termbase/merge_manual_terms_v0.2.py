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
}

HIGH_DOMAINS = {
    "general_regulation",
    "vehicle_general",
    "vehicle_safety",
    "seatbelt_restraint",
    "seat_headrest",
    "seatbelt_reminder",
    "ev_safety",
    "defrost_demisting",
    "hvac",
    "anti_theft",
    "adas",
    "vehicle_market",
}

MEDIUM_DOMAINS = {
    "testing",
    "legal_expression",
}

HIGH_TERMS = {
    # en
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

    # ru
    "гост",
    "межгосударственный стандарт",
    "технические требования",
    "методы испытаний",
    "приложение",
    "транспортное средство",
    "автотранспортное средство",
    "легковой автомобиль",
    "категория m1",
    "категории m и n",
    "пассажирское помещение",
    "тип транспортного средства",
    "бортовая электронная система",
    "главное коммутационное устройство",
    "аккумуляторная батарея",
    "частота вращения двигателя",
    "оценка соответствия",
    "техническое описание",
    "идентификационный номер транспортного средства",
    "водитель",
    "пассажир",
    "сиденье",
    "ветровое стекло",
    "лобовое стекло",
    "наружная поверхность ветрового стекла",
    "внутренняя поверхность ветрового стекла",
    "обмерзание",
    "оттаивание",
    "система оттаивания",
    "зона оттаивания",
    "запотевание",
    "удаление запотевания",
    "система удаления запотевания",
    "зона удаления запотевания",
    "конденсация влаги",
    "стеклоочиститель",
    "зона а",
    "зона в",
    "поле обзора",
    "процедура обледенения",
    "испытание на оттаивание ветрового стекла",
    "испытание на удаление запотевания ветрового стекла",
    "обдув ветрового стекла",
    "обитаемое помещение",
    "рабочее место водителя",
    "электрический отопитель",
    "топливный отопитель",
    "система отопления",
    "отопление",
    "система вентиляции",
    "вентиляция",
    "система кондиционирования",
    "кондиционирование",
    "система климат-контроля",
    "головная зона",
    "зона дыхания",
    "поясная зона",
    "ножная зона",
    "установившаяся температура",
    "подача свежего воздуха",
    "воздухообмен",
    "расход воздуха",
    "скорость воздушного потока",
    "распределение воздушного потока",
    "резервная система отопления",
    "аварийная система отопления",
    "температура поверхности",
    "температура воздуха на выходе",
    "температурный градиент",
    "принудительная вентиляция",
    "кондиционер",
    "индивидуальный воздуховод",
    "понижение температуры",
    "относительная влажность",
    "хладагент",
    "озоноразрушающее вещество",
    "компрессор",
    "теплопроизводительность",
    "испытание системы отопления",
    "испытание системы вентиляции",
    "испытание системы кондиционирования",
    "климатическое исполнение",
    "органы управления",
    "холодная камера",
    "климатическая камера",
    "выдержка",
    "парообразователь",
    "генератор пара",
    "производительность парообразователя",
    "калибровка",
    "условия испытаний",
    "технически исправное состояние",
    "режим движения",
    "динамометрический стенд",
    "солнечная радиация",
    "точка измерения",

    # es general regulation
    "decreto",
    "resolución",
    "resolución exenta",
    "ministerio de transportes y telecomunicaciones",
    "subsecretaría de transportes",
    "diario oficial",
    "ley de tránsito",
    "decreto supremo",
    "decreto con fuerza de ley",
    "fecha de publicación",
    "fecha de promulgación",
    "entrará en vigencia",
    "vigencia",
    "artículo",
    "artículo único",
    "artículo transitorio",
    "anexo",
    "modifícase",
    "reemplázase",
    "agrégase",
    "incorpórase",
    "cuerpo normativo",
    "normativa",
    "normativa técnica",
    "norma internacional",
    "norma técnica internacional",
    "reglamento",
    "reglamento nº 116",
    "comisión económica de las naciones unidas para europa",
    "cepe",
    "cepe/onu",
    "un-ece",
    "type approval",
    "homologación",
    "homologación de modelos",
    "modelos homologados",
    "acreditar",
    "certificado",
    "cumplir con los requisitos",
    "requisitos establecidos",
    "disposiciones",
    "deberán",
    "será obligatorio",
    "centro de control y certificación vehicular",
    "3cv",
    "antecedentes técnicos",
    "informe técnico",
    "código de informe técnico",
    "marca de verificación",
    "rótulo",
    "gb",
    "gb/t",
    "estándar nacional de la república popular china",
    "gb/t 25985-2010",
    "normativa internacional",
    "criterios de evaluación",
    "métodos de ensayo",
    "organismo rector nacional de tránsito",
    "sin perjuicio de",
    "publicación en el diario oficial",
    "fecha de publicación en el diario oficial",

    # es vehicle general / market
    "vehículo",
    "vehículo motorizado",
    "vehículo motorizado nuevo",
    "vehículo nuevo",
    "vehículos livianos",
    "vehículos livianos de pasajeros",
    "vehículos comerciales",
    "furgón",
    "minibús",
    "camioneta",
    "camioneta con cabina avanzada",
    "cabina avanzada",
    "habitáculo",
    "peso bruto vehicular",
    "comercializar",
    "comercialización",
    "ingresar al país",
    "primera venta al por menor",
    "fabricante",
    "armador",
    "importador",
    "representante",
    "modelo",
    "motor",

    # es safety
    "rótulo de elementos de seguridad optativos",
    "elementos de seguridad",
    "elementos de seguridad optativos",
    "elementos de seguridad obligatorios",
    "provisto de",
    "cuenta con",
    "no está provisto de",
    "parabrisas",
    "sistema de bolsa de aire",
    "air bags",
    "bolsa de aire",
    "bolsas de aire laterales de cuerpo",
    "bolsas de aire laterales de cabeza",
    "cinturón de seguridad",
    "anclaje de cinturón de seguridad",
    "vidrios de seguridad",
    "retrovisor",
    "espejo retrovisor",
    "asiento",
    "dispositivo de dirección",
    "sistema de frenos",
    "frenado",
    "control electrónico de estabilidad",
    "reglamento nº 13-h",
    "reglamento nº 140",
    "reglamento nº 14",
    "reglamento nº 16",
    "características técnicas de construcción",
    "condiciones de seguridad",
    "sistemas y/o componentes del vehículo",
    "componentes del vehículo",
    "seguridad vehicular",

    # es anti theft
    "protección contra la utilización no autorizada",
    "utilización no autorizada",
    "uso no autorizado",
    "dispositivo de protección",
    "dispositivo contra la utilización no autorizada",
    "inmovilizador",
    "theft protection",
    "arranque",
    "accionamiento",
    "evitando su accionamiento",
    "suministro de combustible",
    "sistema de inyección",
    "sistema de ignición",
    "unidad de control electrónico",
    "ecu",
    "desenergizar la unidad de control electrónico",
    "propia fuerza motriz",
    "activar",
    "desactivar",
    "control único",
    "equipamiento original",
    "equipamiento certificado por el fabricante",
    "bloqueado",
    "desmontado",
    "herramientas especiales",
    "neutralizarse",
    "accionamiento accidental",
    "motor en marcha",
    "bloqueo",
    "medidas de protección",

    # es adas
    "sistema avanzado de frenado de emergencia",
    "aeb",
    "detector de punto ciego",
    "bsd",
    "punto ciego",
    "asistente de velocidad inteligente",
    "isa",
    "asistente de mantenimiento de carril",
    "lka",
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
        m = pattern.match(term_id)
        if m:
            max_id = max(max_id, int(m.group(1)))
    return max_id + 1

def assign_priority(row):
    source_term = normalize_space(row.get("source_term")).lower()
    domain = clean(row.get("domain")).lower()
    current = clean(row.get("priority")).lower()

    if source_term in HIGH_TERMS:
        return "high"

    if source_term in LOW_TERMS:
        return "low"

    if domain == "testing":
        if (
            "испытание" in source_term
            or "испытаний" in source_term
            or "ensayo" in source_term
            or "método" in source_term
            or "test" in source_term
            or source_term.endswith("test")
        ):
            return "high"
        if current == "low":
            return "low"
        return "medium"

    if domain == "legal_expression":
        if source_term in {"shall", "must", "mandatory"}:
            return "high"
        return "medium"

    if domain in {
        "defrost_demisting",
        "hvac",
        "anti_theft",
        "adas",
        "vehicle_market",
    }:
        if current == "low":
            return "low"
        if current == "medium":
            return "medium"
        return "high"

    if domain in HIGH_DOMAINS:
        if current == "low":
            return "low"
        if current == "medium":
            return "medium"
        return "high"

    if current in {"high", "medium", "low"}:
        return current

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
            writer.writerow({field: clean(row.get(field)) for field in FIELDS})

def validate_header(rows, path):
    if not rows:
        raise ValueError(f"empty input file: {path}")

    missing = [field for field in FIELDS if field not in rows[0]]
    if missing:
        raise ValueError(f"missing fields in {path}: {missing}")

def resolve_input_path():
    if len(sys.argv) >= 2:
        arg = sys.argv[1].strip()

        if arg in DEFAULT_INPUT_BY_LANG:
            return DEFAULT_INPUT_BY_LANG[arg]

        return Path(arg)

    return DEFAULT_INPUT_BY_LANG["es"]

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

    existing_keys = {normalize_key(row) for row in base_rows}

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

        if normalized["priority"] not in {"high", "medium", "low"}:
            normalized["priority"] = "medium"

        if normalized["status"] not in {"active", "review", "deprecated"}:
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
        p = clean(row.get("priority"))
        s = clean(row.get("status"))
        lang = clean(row.get("source_lang"))

        priority_count[p] = priority_count.get(p, 0) + 1
        status_count[s] = status_count.get(s, 0) + 1
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
