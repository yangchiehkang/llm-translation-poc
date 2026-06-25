import csv
from pathlib import Path
from collections import Counter, defaultdict


TERMBASE_PATH = Path("termbase/auto_regulation_terms_v0.2.csv")
CORE_PATH = Path("termbase/core_high_terms_v0.3_candidate.csv")

OUTPUT_MAIN = Path("termbase/termbase_v0.3_candidate_updates.csv")
OUTPUT_ALIAS = Path("termbase/alias_additions_v0.3_candidate.csv")
OUTPUT_BAD_TARGET = Path("termbase/bad_target_term_fixes_v0.3_candidate.csv")
OUTPUT_BROAD = Path("termbase/broad_term_review_v0.3_candidate.csv")


MAIN_FIELDS = [
    "candidate_id",
    "term_id",
    "source_lang",
    "target_lang",
    "source_term",
    "current_target_term",
    "domain",
    "priority",
    "status",
    "current_alias",
    "current_note",
    "problem_type",
    "evidence_source",
    "frequency",
    "suggested_action",
    "suggested_target_term",
    "suggested_alias",
    "suggested_priority",
    "suggested_status",
    "suggested_note",
    "tcr_scope",
    "acceptance_scope",
    "owner",
    "decision_status",
]

ALIAS_FIELDS = [
    "candidate_id",
    "term_id",
    "source_lang",
    "source_term",
    "target_term",
    "current_alias",
    "suggested_alias",
    "reason",
    "evidence_source",
    "decision_status",
]

BAD_TARGET_FIELDS = [
    "candidate_id",
    "term_id",
    "source_lang",
    "source_term",
    "current_target_term",
    "suggested_target_term",
    "problem_type",
    "reason",
    "evidence_source",
    "decision_status",
]

BROAD_FIELDS = [
    "candidate_id",
    "term_id",
    "source_lang",
    "source_term",
    "current_target_term",
    "domain",
    "current_priority",
    "suggested_priority",
    "suggested_status",
    "reason",
    "exclude_from_core_high_terms",
    "decision_status",
]


BROAD_TERMS = {
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


BAD_TARGET_PATTERNS = {
    "应",
    "可",
    "可以",
    "必须",
    "宜",
    "车辆",
    "系统",
    "部件",
    "零件",
    "装置",
    "附件",
    "附录",
    "段落",
    "表",
    "图",
    "要求",
    "标准",
}


PROMPT_RIGID_PATTERNS = {
    "shall",
    "may",
    "must",
    "should",
    "requirement",
    "requirements",
    "provision",
    "provisions",
}


def read_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def norm(value):
    return str(value or "").strip()


def lower(value):
    return norm(value).lower()


def make_candidate_id(prefix, index):
    return f"{prefix}-{index:04d}"


def load_core_scope():
    core_rows = read_csv(CORE_PATH)
    scope_map = {}
    for row in core_rows:
        term_id = norm(row.get("term_id"))
        scope_map[term_id] = {
            "tcr_scope": norm(row.get("tcr_scope")),
            "acceptance_scope": norm(row.get("acceptance_scope")),
        }
    return scope_map


def classify_problem(row):
    source = lower(row.get("source_term"))
    target = norm(row.get("target_term"))
    alias = norm(row.get("alias"))
    priority = lower(row.get("priority"))

    if source in BROAD_TERMS:
        return "broad term"

    if target in BAD_TARGET_PATTERNS:
        return "bad_target_term"

    if source in PROMPT_RIGID_PATTERNS and priority == "high":
        return "prompt_rigid"

    if "；" in target or ";" in target or "/" in target:
        return "partial_match"

    if len(source.split()) >= 4 and not alias:
        return "partial_match"

    if priority == "high" and not alias:
        return "missing"

    return ""


def suggest_action(problem_type):
    mapping = {
        "missing": "check injection / add alias / adjust prompt strategy",
        "partial_match": "add alias or split long multi-word term",
        "wrong_translation": "review and correct target_term if needed",
        "bad_target_term": "fix target_term",
        "prompt_rigid": "lower priority or adjust note to avoid rigid injection",
        "broad term": "downgrade priority / exclude from core high terms / mark review",
        "statistical_false_positive": "add acceptable translation to alias or adjust matching rule",
    }
    return mapping.get(problem_type, "")


def main():
    termbase_rows = read_csv(TERMBASE_PATH)
    core_scope = load_core_scope()

    candidate_rows = []
    alias_rows = []
    bad_target_rows = []
    broad_rows = []

    index = 1
    alias_index = 1
    bad_index = 1
    broad_index = 1

    for row in termbase_rows:
        source_lang = lower(row.get("source_lang"))
        target_lang = lower(row.get("target_lang"))
        status = lower(row.get("status"))
        priority = lower(row.get("priority"))
        source_term = norm(row.get("source_term"))

        if target_lang != "zh":
            continue

        if status not in {"active", "review"}:
            continue

        problem_type = classify_problem(row)

        if not problem_type:
            continue

        candidate_id = make_candidate_id("TBV03", index)
        index += 1

        term_id = norm(row.get("term_id"))
        scope = core_scope.get(term_id, {})

        suggested_priority = ""
        suggested_status = ""
        suggested_note = ""

        if problem_type == "broad term":
            suggested_priority = "low"
            suggested_status = "review"
            suggested_note = "Broad or structural term; exclude from external core high term acceptance."
        elif problem_type == "prompt_rigid":
            suggested_priority = "medium"
            suggested_status = "review"
            suggested_note = "Avoid rigid terminology injection when context requires natural translation."
        elif problem_type == "bad_target_term":
            suggested_status = "review"
            suggested_note = "Current target term appears too broad, structural, or unnatural."
        elif problem_type == "partial_match":
            suggested_status = "review"
            suggested_note = "Check whether alias should be added or long term should be split."
        elif problem_type == "missing":
            suggested_status = "review"
            suggested_note = "Check whether missing is caused by injection failure, alias gap, or prompt behavior."

        main_row = {
            "candidate_id": candidate_id,
            "term_id": term_id,
            "source_lang": source_lang,
            "target_lang": "zh",
            "source_term": source_term,
            "current_target_term": norm(row.get("target_term")),
            "domain": norm(row.get("domain")),
            "priority": priority,
            "status": status,
            "current_alias": norm(row.get("alias")),
            "current_note": norm(row.get("note")),
            "problem_type": problem_type,
            "evidence_source": "termbase_v0.2_static_scan",
            "frequency": "",
            "suggested_action": suggest_action(problem_type),
            "suggested_target_term": "",
            "suggested_alias": "",
            "suggested_priority": suggested_priority,
            "suggested_status": suggested_status,
            "suggested_note": suggested_note,
            "tcr_scope": scope.get("tcr_scope", ""),
            "acceptance_scope": scope.get("acceptance_scope", ""),
            "owner": "杨杰康",
            "decision_status": "candidate",
        }

        candidate_rows.append(main_row)

        if problem_type in {"missing", "partial_match", "statistical_false_positive"}:
            alias_rows.append({
                "candidate_id": make_candidate_id("ALIAS", alias_index),
                "term_id": term_id,
                "source_lang": source_lang,
                "source_term": source_term,
                "target_term": norm(row.get("target_term")),
                "current_alias": norm(row.get("alias")),
                "suggested_alias": "",
                "reason": suggest_action(problem_type),
                "evidence_source": "termbase_v0.2_static_scan",
                "decision_status": "candidate",
            })
            alias_index += 1

        if problem_type == "bad_target_term":
            bad_target_rows.append({
                "candidate_id": make_candidate_id("BADTARGET", bad_index),
                "term_id": term_id,
                "source_lang": source_lang,
                "source_term": source_term,
                "current_target_term": norm(row.get("target_term")),
                "suggested_target_term": "",
                "problem_type": problem_type,
                "reason": "Current target term appears broad, structural, or unsuitable as a terminology target.",
                "evidence_source": "termbase_v0.2_static_scan",
                "decision_status": "candidate",
            })
            bad_index += 1

        if problem_type == "broad term":
            broad_rows.append({
                "candidate_id": make_candidate_id("BROAD", broad_index),
                "term_id": term_id,
                "source_lang": source_lang,
                "source_term": source_term,
                "current_target_term": norm(row.get("target_term")),
                "domain": norm(row.get("domain")),
                "current_priority": priority,
                "suggested_priority": "low",
                "suggested_status": "review",
                "reason": "Broad or structural term; not suitable for strict core high term acceptance.",
                "exclude_from_core_high_terms": "yes",
                "decision_status": "candidate",
            })
            broad_index += 1

    write_csv(OUTPUT_MAIN, MAIN_FIELDS, candidate_rows)
    write_csv(OUTPUT_ALIAS, ALIAS_FIELDS, alias_rows)
    write_csv(OUTPUT_BAD_TARGET, BAD_TARGET_FIELDS, bad_target_rows)
    write_csv(OUTPUT_BROAD, BROAD_FIELDS, broad_rows)

    print("Generated:")
    print(f"- {OUTPUT_MAIN}: {len(candidate_rows)} rows")
    print(f"- {OUTPUT_ALIAS}: {len(alias_rows)} rows")
    print(f"- {OUTPUT_BAD_TARGET}: {len(bad_target_rows)} rows")
    print(f"- {OUTPUT_BROAD}: {len(broad_rows)} rows")

    counter = Counter(row["problem_type"] for row in candidate_rows)
    print()
    print("Problem type counts:")
    for k, v in counter.most_common():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
