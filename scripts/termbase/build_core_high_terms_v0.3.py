import pandas as pd
from pathlib import Path


INPUT_PATH = Path("termbase/auto_regulation_terms_v0.2.csv")
OUTPUT_PATH = Path("termbase/core_high_terms_v0.3_candidate.csv")


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
    "tcr_scope",
    "acceptance_scope",
]


RFP_LANGS = {
    "en",
    "ru",
    "es",
    "de",
    "fr",
    "th",
    "ar",
}


CORE_DOMAINS_STRICT = {
    "vehicle_approval",
    "vehicle_regulation",
    "general_regulation",
    "road_regulation",
    "conformity_assessment",
    "conformity_of_production",
    "testing",
    "vehicle_testing",
    "vehicle_safety",
    "vehicle_inspection",
    "vehicle_category",
    "vehicle_identification",
    "vehicle_dimensions",
    "vehicle_weight",
    "vehicle_structure",
    "vehicle_performance",
    "vehicle_documentation",
    "braking",
    "steering",
    "wheel_tire",
    "vehicle_lighting",
    "seatbelt_restraint",
    "seatbelt_anchorage",
    "seat_headrest",
    "adas",
    "autonomous_driving",
    "ev_general",
    "ev_regulation",
    "ev_powertrain",
    "ev_safety",
    "ev_charging",
    "ev_performance",
    "battery_safety",
    "battery_testing",
    "battery_regulation",
    "battery_general",
    "fuel_system",
    "emissions",
    "noise",
    "environment_energy",
    "energy_consumption",
    "standards",
    "standardization",
    "regulatory_authority",
    "government_agency",
    "market_surveillance",
    "customs",
    "labelling",
}


CORE_DOMAINS_RELAXED = CORE_DOMAINS_STRICT | {
    "vehicle_general",
    "vehicle_powertrain",
    "vehicle_equipment",
    "vehicle_geometry",
    "vehicle_interior",
    "vehicle_control",
    "vehicle_environment",
    "road_safety",
    "road_authority",
    "international_regulation",
    "international_trade",
    "supply_chain",
    "consumer_protection",
    "emergency_response",
    "after_sales",
    "metrology",
    "emc",
    "engine",
    "powertrain",
    "environment",
}


EXCLUDED_SOURCE_TERMS = {
    "shall",
    "must",
    "may",
    "should",
    "vehicle",
    "vehicles",
    "motor vehicle",
    "system",
    "systems",
    "part",
    "parts",
    "device",
    "devices",
    "component",
    "components",
    "test",
    "tests",
    "standard",
    "standards",
    "requirement",
    "requirements",
    "annex",
    "appendix",
    "paragraph",
    "section",
    "article",
    "chapter",
    "table",
    "figure",
    "scope",
    "general",
    "other",
    "others",
}


EXCLUDED_TARGET_TERMS = {
    "应",
    "必须",
    "可",
    "可以",
    "宜",
    "车辆",
    "机动车",
    "系统",
    "部件",
    "零件",
    "装置",
    "组件",
    "试验",
    "测试",
    "标准",
    "要求",
    "附件",
    "附录",
    "段落",
    "条",
    "章节",
    "表",
    "图",
    "范围",
    "其他",
}


STRICT_KEYWORDS = [
    "approval",
    "homologation",
    "conformity",
    "certificate",
    "certification",
    "regulation",
    "regulatory",
    "technical regulation",
    "type approval",
    "test procedure",
    "test method",
    "test report",
    "inspection",
    "verification",
    "assessment",
    "safety requirement",
    "braking",
    "steering",
    "seat belt",
    "seatbelt",
    "airbag",
    "lighting",
    "rear-view mirror",
    "mirror",
    "tyre",
    "tire",
    "emission",
    "noise",
    "electric vehicle",
    "battery",
    "reess",
    "charging",
    "charger",
    "connector",
    "high voltage",
    "electric shock",
    "insulation resistance",
    "overcharge",
    "short circuit",
    "thermal shock",
    "vibration test",
    "adas",
    "aebs",
    "ldws",
    "esc",
    "vin",
]


def norm(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def norm_lower(value):
    return norm(value).lower()


def contains_strict_keyword(source_term, target_term, alias):
    text = " ".join([
        norm_lower(source_term),
        norm_lower(target_term),
        norm_lower(alias),
    ])
    return any(keyword in text for keyword in STRICT_KEYWORDS)


def is_excluded(row):
    source = norm_lower(row.get("source_term"))
    target = norm(row.get("target_term")).strip()

    if source in EXCLUDED_SOURCE_TERMS:
        return True

    if target in EXCLUDED_TARGET_TERMS:
        return True

    if len(source) <= 2 and source.isalpha():
        return True

    return False


def assign_tcr_scope(row):
    domain = norm_lower(row.get("domain"))

    if is_excluded(row):
        return ""

    if domain in CORE_DOMAINS_STRICT:
        return "strict"

    if contains_strict_keyword(
        row.get("source_term"),
        row.get("target_term"),
        row.get("alias"),
    ):
        return "strict"

    if domain in CORE_DOMAINS_RELAXED:
        return "relaxed"

    return ""


def main():
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig", dtype=str).fillna("")

    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    base = df[
        (df["priority"] == "high")
        & (df["status"] == "active")
        & (df["target_lang"] == "zh")
    ].copy()

    base["tcr_scope"] = base.apply(assign_tcr_scope, axis=1)

    result = base[base["tcr_scope"].isin(["strict", "relaxed"])].copy()

    result["acceptance_scope"] = result["tcr_scope"].map({
        "strict": "external_acceptance",
        "relaxed": "internal_diagnosis",
    })

    result = result[FIELDS].sort_values(
        by=["source_lang", "tcr_scope", "domain", "source_term"]
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print("input:", INPUT_PATH)
    print("output:", OUTPUT_PATH)
    print("v0.2 rows:", len(df))
    print("high active zh rows:", len(base))
    print("core candidate rows:", len(result))
    print()
    print("count by source_lang:")
    print(result["source_lang"].value_counts().to_string())
    print()
    print("count by tcr_scope:")
    print(result["tcr_scope"].value_counts().to_string())
    print()
    print("RFP language rows:")
    print(result[result["source_lang"].isin(RFP_LANGS)]["source_lang"].value_counts().to_string())


if __name__ == "__main__":
    main()
