"""Pure, deterministic business logic exposed to agents through registered tools."""
from __future__ import annotations

import re

from . import data
from .errors import InvalidInputError

MAX_QUERY_LEN = 500
REQUIRED_PRODUCT_FIELDS = ("name", "brand", "price", "ram_gb", "storage_gb", "rating")
MERGE_FIELDS = ("name", "brand", "category", "price", "ram_gb", "storage_gb", "rating",
                "in_stock", "processor", "display")
OVERRIDABLE_KEYS = ("category", "max_price", "min_ram_gb", "min_storage_gb", "min_rating", "brands")


# ============================================================== formatting
def fmt_inr(value: float | int | None) -> str:
    """Indian digit grouping, e.g. 100000 -> ₹1,00,000."""
    if value is None:
        return "—"
    v = int(round(value))
    s = str(abs(v))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return ("-" if v < 0 else "") + "₹" + s


# ============================================================ query parsing
_CATEGORY_SYNONYMS = {
    "laptop": ("laptop", "laptops", "notebook", "notebooks", "ultrabook", "ultrabooks"),
    "smartphone": ("smartphone", "smartphones", "phone", "phones", "mobile", "mobiles"),
    "tablet": ("tablet", "tablets", "ipad", "ipads"),
}

INJECTION_PATTERNS = (
    r"\bignore\b", r"\bdisregard\b", r"\bforget\s+(?:the|all|your|previous|any)\b", r"\boverride\b",
    r"\bbypass\b", r"\bmost\s+expensive\b", r"\bhighest[\s-]+pric", r"\bpriciest\b",
    r"\bsystem\s+prompt\b", r"\byou\s+are\s+now\b", r"\bact\s+as\b", r"\bjailbreak\b",
    r"\badmin\s+mode\b", r"\bdeveloper\s+mode\b",
    r"\b(?:change|set|increase|raise|remove)\s+(?:the\s+|my\s+)?budget\b",
)

_CLAUSE_SPLIT = re.compile(r"(?<=[.!?;])\s+|,\s+|\s+but\s+|\n+", re.IGNORECASE)
_AMOUNT = r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?)?\b(?!\s*(?:gb|tb|inch|\"))"
_BUDGET_RE = re.compile(
    r"(?:under|below|less\s+than|within|up\s*to|upto|max(?:imum)?|not\s+more\s+than|cheaper\s+than"
    r"|budget(?:\s+of|\s+is)?|<=?)\s*" + _AMOUNT, re.IGNORECASE)
_RAM_RES = (
    re.compile(r"(\d+)\s*gb\s*(?:of\s*)?(?:ram|memory)\b", re.IGNORECASE),
    re.compile(r"\b(?:ram|memory)\s*(?:of\s*|:\s*)?(?:at\s*least\s*|min(?:imum)?\s*|>=\s*)?(\d+)\s*gb", re.IGNORECASE),
)
_STORAGE_RES = (
    re.compile(r"(\d+(?:\.\d+)?)\s*(gb|tb)\s*(?:of\s*)?(?:ssd|storage|hdd|rom|internal|disk)\b", re.IGNORECASE),
    re.compile(r"\b(?:storage|ssd|rom)\s*(?:of\s*|:\s*)?(?:at\s*least\s*|min(?:imum)?\s*|>=\s*)?(\d+(?:\.\d+)?)\s*(gb|tb)", re.IGNORECASE),
)
_RATING_RES = (
    re.compile(r"\b(?:rating|rated|ratings)\s*(?:of\s*)?(?:above|over|at\s*least|more\s*than|greater\s*than"
               r"|min(?:imum)?(?:\s*of)?|>=|>)?\s*(\d(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"\b(\d(?:\.\d+)?)\s*\+?\s*(?:stars?|★)", re.IGNORECASE),
    re.compile(r"\b(\d\.\d+)\s*\+?\s*(?:rating|rated)\b", re.IGNORECASE),
)


def sanitize_query(query: object) -> str:
    if not isinstance(query, str):
        raise InvalidInputError("Query must be a text string")
    if len(query) > MAX_QUERY_LEN:
        raise InvalidInputError(f"Query exceeds {MAX_QUERY_LEN} characters")
    q = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", query)  # control chars
    q = re.sub(r"<[^>]*>", " ", q)  # strip HTML/script tags
    if not q.strip():
        raise InvalidInputError("Query is empty")
    return q.strip()


def _detect_category(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for cat, words in _CATEGORY_SYNONYMS.items():
        for w in words:
            m = re.search(rf"\b{w}\b", text, re.IGNORECASE)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), cat)
    return best[1] if best else None


def _parse_amount(num: str, unit: str | None) -> float:
    value = float(num.replace(",", ""))
    unit = (unit or "").lower()
    if unit in ("k", "thousand"):
        value *= 1_000
    elif unit.startswith("lakh") or unit.startswith("lac"):
        value *= 100_000
    return value


def validate_requirement_values(req: dict) -> None:
    if req.get("category") not in data.SUPPORTED_CATEGORIES:
        raise InvalidInputError(f"Unsupported category '{req.get('category')}'. "
                                f"Supported: {', '.join(data.SUPPORTED_CATEGORIES)}")
    checks = (("max_price", 1, 5_000_000, "Budget"), ("min_ram_gb", 1, 128, "RAM"),
              ("min_storage_gb", 1, 8192, "Storage"), ("min_rating", 0, 5, "Rating"))
    for key, lo, hi, label in checks:
        v = req.get(key)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise InvalidInputError(f"{label} must be numeric")
        if not lo <= v <= hi:
            raise InvalidInputError(f"{label} value {v} is outside the supported range [{lo}, {hi}]")
    brands = req.get("brands") or []
    if not isinstance(brands, list) or any(b not in data.KNOWN_BRANDS for b in brands):
        raise InvalidInputError(f"Unknown brand in {brands}")


def parse_query(query: str) -> dict:
    """Planner tool: convert natural language into structured, validated requirements.

    Clauses containing prompt-injection patterns are removed before any numeric
    constraint is extracted, so injected text cannot alter trusted requirements.
    """
    q = sanitize_query(query)
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(q) if c and c.strip()]
    safe, removed, flags = [], [], []
    for clause in clauses:
        hits = [p for p in INJECTION_PATTERNS if re.search(p, clause, re.IGNORECASE)]
        if hits:
            removed.append(clause)
            flags.append({"type": "PROMPT_INJECTION", "clause": clause,
                          "action": "Clause ignored; trusted requirement extraction and ranking logic enforced"})
        else:
            safe.append(clause)
    safe_text = re.sub(r"\s+", " ", " ".join(safe))

    # Category is a low-risk field; it may be detected from the full text.
    category = _detect_category(safe_text) or _detect_category(q)
    if category is None:
        raise InvalidInputError("Could not identify a supported product category "
                                f"({', '.join(data.SUPPORTED_CATEGORIES)}) in the query")

    req: dict = {"category": category, "max_price": None, "min_ram_gb": None, "min_storage_gb": None,
                 "min_rating": None, "brands": [], "excluded_product_ids": []}
    if m := _BUDGET_RE.search(safe_text):
        req["max_price"] = _parse_amount(m.group(1), m.group(2))
    for rx in _RAM_RES:
        if m := rx.search(safe_text):
            req["min_ram_gb"] = int(m.group(1))
            break
    for rx in _STORAGE_RES:
        if m := rx.search(safe_text):
            size = float(m.group(1))
            req["min_storage_gb"] = int(size * 1024) if m.group(2).lower() == "tb" else int(size)
            break
    for rx in _RATING_RES:
        if m := rx.search(safe_text):
            req["min_rating"] = float(m.group(1))
            break
    req["brands"] = [b for b in data.KNOWN_BRANDS if re.search(rf"\b{re.escape(b)}\b", safe_text, re.IGNORECASE)]
    if req["max_price"] is not None and req["max_price"].is_integer():
        req["max_price"] = int(req["max_price"])
    validate_requirement_values(req)
    return {"sanitized_query": safe_text, "removed_clauses": removed, "security_flags": flags, "requirements": req}


def describe_requirements(req: dict) -> list[dict]:
    rows = [{"Requirement": "Product Category", "Value": req["category"].title()}]
    rows.append({"Requirement": "Maximum Budget", "Value": fmt_inr(req["max_price"]) if req.get("max_price") else "Not specified"})
    rows.append({"Requirement": "Minimum RAM", "Value": f"{req['min_ram_gb']} GB" if req.get("min_ram_gb") else "Not specified"})
    rows.append({"Requirement": "Minimum Storage", "Value": f"{req['min_storage_gb']} GB" if req.get("min_storage_gb") else "Not specified"})
    rows.append({"Requirement": "Minimum Rating", "Value": str(req["min_rating"]) if req.get("min_rating") is not None else "Not specified"})
    if req.get("brands"):
        rows.append({"Requirement": "Preferred Brands", "Value": ", ".join(req["brands"])})
    if req.get("excluded_product_ids"):
        rows.append({"Requirement": "Excluded by Reviewer", "Value": ", ".join(req["excluded_product_ids"])})
    return rows


# =========================================================== synchronization
def _priority(src: str) -> int:
    return data.SOURCES.get(src, {}).get("trust_priority", 99)


def _conflict_severity(field: str, values: list) -> str:
    if field == "rating":
        return "HIGH" if max(values) - min(values) >= 0.3 else "LOW"
    if field == "price":
        return "HIGH" if (max(values) - min(values)) / min(values) > 0.05 else "LOW"
    if field in ("in_stock", "ram_gb", "storage_gb", "category"):
        return "HIGH"
    return "LOW"


def synchronize_results(results_by_source: dict) -> dict:
    """Merge parallel search outputs; resolve conflicts with trusted-source priority."""
    listings: dict[str, dict[str, dict]] = {}
    for src in sorted(results_by_source, key=_priority):
        for p in results_by_source[src]:
            listings.setdefault(p["product_id"], {})[src] = p
    merged, conflicts = [], []
    for pid in sorted(listings):
        by_src = listings[pid]
        srcs = sorted(by_src, key=_priority)
        rec = {"product_id": pid, "sources": srcs, "field_sources": {}}
        for f in MERGE_FIELDS:
            present = {s: by_src[s].get(f) for s in srcs if by_src[s].get(f) is not None}
            if not present:
                rec[f] = None
                continue
            chosen = next(s for s in srcs if s in present)
            rec[f] = present[chosen]
            rec["field_sources"][f] = chosen
            distinct = {repr(v) for v in present.values()}
            if len(distinct) > 1:
                conflicts.append({
                    "product_id": pid, "name": by_src[srcs[0]].get("name"), "field": f,
                    "values": present, "resolved_value": rec[f], "resolved_from": chosen,
                    "method": "Trusted-source priority (A: Official > B: Marketplace > C: Aggregator)",
                    "severity": _conflict_severity(f, list(present.values())),
                })
            elif len(present) < len(srcs):
                conflicts.append({
                    "product_id": pid, "name": by_src[srcs[0]].get("name"), "field": f,
                    "values": {s: by_src[s].get(f) for s in srcs}, "resolved_value": rec[f],
                    "resolved_from": chosen, "method": "Gap filled from source that reported the value",
                    "severity": "LOW",
                })
        merged.append(rec)
    return {"products": merged, "conflicts": conflicts, "sources_used": sorted(results_by_source, key=_priority)}


# ================================================================= filtering
def check_product(p: dict, req: dict) -> list[str]:
    """Return the list of constraint violations for a product (empty == passes)."""
    reasons = []
    for f in REQUIRED_PRODUCT_FIELDS:
        if p.get(f) is None:
            reasons.append(f"Missing product information: {f}")
    if p.get("category") != req["category"]:
        reasons.append(f"Category '{p.get('category')}' != '{req['category']}'")
    if p.get("in_stock") is not True:
        reasons.append("Out of stock")
    if req.get("max_price") is not None and p.get("price") is not None and p["price"] > req["max_price"]:
        reasons.append(f"Price {fmt_inr(p['price'])} exceeds budget {fmt_inr(req['max_price'])}")
    if req.get("min_ram_gb") is not None and p.get("ram_gb") is not None and p["ram_gb"] < req["min_ram_gb"]:
        reasons.append(f"RAM {p['ram_gb']} GB < required {req['min_ram_gb']} GB")
    if req.get("min_storage_gb") is not None and p.get("storage_gb") is not None and p["storage_gb"] < req["min_storage_gb"]:
        reasons.append(f"Storage {p['storage_gb']} GB < required {req['min_storage_gb']} GB")
    if req.get("min_rating") is not None and p.get("rating") is not None and p["rating"] < req["min_rating"]:
        reasons.append(f"Rating {p['rating']} < required {req['min_rating']}")
    if req.get("brands") and p.get("brand") not in req["brands"]:
        reasons.append(f"Brand {p.get('brand')} not in preferred brands")
    if p.get("product_id") in (req.get("excluded_product_ids") or []):
        reasons.append("Excluded by human reviewer (flagged as incorrect information)")
    return reasons


def filter_products(products: list, requirements: dict) -> dict:
    passed, rejected = [], []
    for p in products:
        reasons = check_product(p, requirements)
        if reasons:
            rejected.append({"product_id": p.get("product_id"), "name": p.get("name"), "reasons": reasons})
        else:
            passed.append(p)
    return {"passed": passed, "rejected": rejected}


# ================================================================ comparison
def compare_products(products: list, requirements: dict) -> dict:
    rows = []
    for p in products:
        rows.append({
            "product_id": p["product_id"], "name": p["name"], "brand": p["brand"], "price": p["price"],
            "ram_gb": p["ram_gb"], "storage_gb": p["storage_gb"], "rating": p["rating"],
            "processor": p.get("processor"), "display": p.get("display"),
            "budget_headroom": (requirements["max_price"] - p["price"]) if requirements.get("max_price") else None,
            "ram_margin_gb": (p["ram_gb"] - requirements["min_ram_gb"]) if requirements.get("min_ram_gb") else None,
            "storage_margin_gb": (p["storage_gb"] - requirements["min_storage_gb"]) if requirements.get("min_storage_gb") else None,
            "rating_margin": round(p["rating"] - requirements["min_rating"], 2) if requirements.get("min_rating") is not None else None,
        })
    best = {}
    if products:
        best = {
            "lowest_price": min(products, key=lambda p: (p["price"], p["product_id"]))["product_id"],
            "highest_rating": max(products, key=lambda p: (p["rating"], -p["price"]))["product_id"],
            "most_ram": max(products, key=lambda p: (p["ram_gb"], -p["price"]))["product_id"],
            "most_storage": max(products, key=lambda p: (p["storage_gb"], -p["price"]))["product_id"],
        }
    stats = {}
    for key in ("price", "ram_gb", "storage_gb", "rating"):
        vals = [p[key] for p in products]
        stats[key] = {"min": min(vals), "max": max(vals)} if vals else {"min": None, "max": None}
    return {"rows": rows, "best_in": best, "stats": stats, "count": len(products)}


# =================================================================== ranking
BASE_WEIGHTS = {"price": 0.30, "rating": 0.30, "ram": 0.20, "storage": 0.20}
_FACTOR_FIELD = {"price": "price", "rating": "rating", "ram": "ram_gb", "storage": "storage_gb"}
_FACTOR_REQ = {"price": "max_price", "rating": "min_rating", "ram": "min_ram_gb", "storage": "min_storage_gb"}
REQUIREMENT_BOOST = 1.5


def ranking_weights(requirements: dict) -> dict:
    """Requirement-aware weights: factors the customer explicitly asked for get boosted."""
    raw = {k: w * (REQUIREMENT_BOOST if requirements.get(_FACTOR_REQ[k]) is not None else 1.0)
           for k, w in BASE_WEIGHTS.items()}
    total = sum(raw.values())
    return {k: round(v / total, 4) for k, v in raw.items()}


def _normalize(value: float, lo: float, hi: float, invert: bool = False) -> float:
    if hi == lo:
        return 1.0
    x = (value - lo) / (hi - lo)
    return round(1 - x if invert else x, 4)


def score_from_components(components: dict, weights: dict) -> float:
    return round(100 * sum(weights[k] * components[k] for k in weights), 2)


def score_products(products: list, requirements: dict) -> list:
    """Transparent weighted scoring followed by deterministic sorting."""
    if not products:
        return []
    weights = ranking_weights(requirements)
    bounds = {k: (min(p[f] for p in products), max(p[f] for p in products)) for k, f in _FACTOR_FIELD.items()}
    scored = []
    for p in products:
        comps = {k: _normalize(p[f], *bounds[k], invert=(k == "price")) for k, f in _FACTOR_FIELD.items()}
        score = score_from_components(comps, weights)
        contributions = {k: round(100 * weights[k] * comps[k], 2) for k in weights}
        reasons = []
        if requirements.get("max_price"):
            reasons.append(f"{fmt_inr(requirements['max_price'] - p['price'])} under budget ({fmt_inr(p['price'])})")
        else:
            reasons.append(f"Price {fmt_inr(p['price'])}")
        reasons.append(f"{p['ram_gb']} GB RAM" + (f" (≥ {requirements['min_ram_gb']} GB required)" if requirements.get("min_ram_gb") else ""))
        reasons.append(f"{p['storage_gb']} GB storage" + (f" (≥ {requirements['min_storage_gb']} GB required)" if requirements.get("min_storage_gb") else ""))
        reasons.append(f"Rating {p['rating']}" + (f" (≥ {requirements['min_rating']} required)" if requirements.get("min_rating") is not None else ""))
        if p["price"] == bounds["price"][0] and len(products) > 1:
            reasons.append("Lowest price among qualifying products")
        if p["rating"] == bounds["rating"][1] and len(products) > 1:
            reasons.append("Highest rating among qualifying products")
        top_factor = max(contributions, key=contributions.get)
        reasons.append(f"Strongest factor: {top_factor} (+{contributions[top_factor]} pts)")
        scored.append({
            "product_id": p["product_id"], "name": p["name"], "brand": p["brand"], "price": p["price"],
            "ram_gb": p["ram_gb"], "storage_gb": p["storage_gb"], "rating": p["rating"],
            "processor": p.get("processor"), "display": p.get("display"), "sources": p.get("sources", []),
            "components": comps, "weights": weights, "contributions": contributions,
            "score": score, "reasons": reasons,
        })
    scored.sort(key=lambda r: (-r["score"], -r["rating"], r["price"], r["product_id"]))
    for i, r in enumerate(scored, 1):
        r["rank"] = i
    return scored


# ================================================================ validation
def _check(name: str, passed: bool, detail: str, product_id: str | None = None) -> dict:
    return {"check": name, "product_id": product_id, "passed": bool(passed), "detail": detail}


def validate_requirements(requirements: dict) -> dict:
    checks = [_check("Category identified", requirements.get("category") in data.SUPPORTED_CATEGORIES,
                     f"category={requirements.get('category')}")]
    try:
        validate_requirement_values(requirements)
        checks.append(_check("Requirement values in valid ranges", True, "All numeric constraints valid"))
    except InvalidInputError as e:
        checks.append(_check("Requirement values in valid ranges", False, str(e)))
    n = sum(requirements.get(k) is not None for k in ("max_price", "min_ram_gb", "min_storage_gb", "min_rating"))
    checks.append(_check("Constraints extracted", True, f"{n} numeric constraint(s) extracted"))
    return {"checkpoint": "Query Decomposition", "passed": all(c["passed"] for c in checks), "checks": checks}


def validate_filtered(filtered: list, requirements: dict) -> dict:
    checks = []
    for p in filtered:
        violations = check_product(p, requirements)
        checks.append(_check("Filtered product satisfies constraints", not violations,
                             "; ".join(violations) or "OK", p.get("product_id")))
    if not checks:
        checks.append(_check("Filtered product satisfies constraints", True, "No products passed filtering"))
    return {"checkpoint": "Product Filtering", "passed": all(c["passed"] for c in checks), "checks": checks,
            "count": len(filtered)}


def validate_recommendation(ranking: list, filtered: list, requirements: dict, integrity_ok: bool) -> dict:
    checks = [_check("Shared-state integrity (requirements unchanged)", integrity_ok,
                     "Requirements hash verified" if integrity_ok else "Requirements were modified outside the write API")]
    checks.append(_check("Recommendation available", len(ranking) > 0, f"{len(ranking)} ranked product(s)"))
    filtered_ids = {p["product_id"] for p in filtered}
    ranked_ids = [r["product_id"] for r in ranking]
    checks.append(_check("Ranked set equals filtered set", set(ranked_ids) == filtered_ids and len(ranked_ids) == len(set(ranked_ids)),
                         f"ranked={len(ranked_ids)}, filtered={len(filtered_ids)}"))
    for r in ranking:
        missing = [f for f in REQUIRED_PRODUCT_FIELDS if r.get(f) is None]
        checks.append(_check("Required product information present", not missing,
                             f"missing: {missing}" if missing else "OK", r["product_id"]))
        if not missing:
            probe = {**r, "category": requirements["category"], "in_stock": True}
            violations = [v for v in check_product(probe, requirements)]
            checks.append(_check("Budget / RAM / Storage / Rating compliance", not violations,
                                 "; ".join(violations) or "OK", r["product_id"]))
        recomputed = score_from_components(r["components"], r["weights"])
        checks.append(_check("Score consistent with components", abs(recomputed - r["score"]) < 0.011,
                             f"reported={r['score']}, recomputed={recomputed}", r["product_id"]))
    expected = score_products(filtered, requirements) if filtered else []
    expected_order = [e["product_id"] for e in expected]
    checks.append(_check("Ranking order independently reproduced", expected_order == ranked_ids,
                         f"expected={expected_order[:5]}..." if expected_order != ranked_ids else "Order verified"))
    ranks_ok = [r["rank"] for r in ranking] == list(range(1, len(ranking) + 1))
    sorted_ok = all(ranking[i]["score"] >= ranking[i + 1]["score"] for i in range(len(ranking) - 1))
    checks.append(_check("Ranks contiguous and scores descending", ranks_ok and sorted_ok, "OK" if ranks_ok and sorted_ok else "Ordering defect"))
    return {"checkpoint": "Final Recommendation", "passed": all(c["passed"] for c in checks), "checks": checks}
