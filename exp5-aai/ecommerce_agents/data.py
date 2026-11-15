"""Product catalog used by the experiment.

Three independent catalog sources are simulated so that the Search Agents can run
in parallel and the Supervisor can demonstrate synchronization and conflict
resolution. Some listings intentionally contain conflicting or missing values.
"""
from __future__ import annotations

import copy

# Lower trust_priority = more trusted. Used for conflict resolution.
SOURCES: dict[str, dict] = {
    "A": {"name": "Official Brand Store API", "trust_priority": 1},
    "B": {"name": "Marketplace Catalog", "trust_priority": 2},
    "C": {"name": "Price Aggregator Feed", "trust_priority": 3},
}

SUPPORTED_CATEGORIES = ("laptop", "smartphone", "tablet")

# Canonical product facts. Individual sources may override some fields.
_BASE: dict[str, dict] = {
    # ---------------- Laptops ----------------
    "L001": dict(name="Lenovo IdeaPad Slim 5", brand="Lenovo", category="laptop", price=64990, ram_gb=16, storage_gb=512, rating=4.4, in_stock=True, processor="AMD Ryzen 7 7730U", display='14" WUXGA OLED'),
    "L002": dict(name="HP Pavilion 15", brand="HP", category="laptop", price=62499, ram_gb=16, storage_gb=512, rating=4.3, in_stock=True, processor="Intel Core i5-1335U", display='15.6" FHD IPS'),
    "L003": dict(name="ASUS Vivobook 16X", brand="ASUS", category="laptop", price=67990, ram_gb=16, storage_gb=1024, rating=4.2, in_stock=True, processor="Intel Core i7-12650H", display='16" WUXGA'),
    "L004": dict(name="Acer Aspire 7", brand="Acer", category="laptop", price=58990, ram_gb=16, storage_gb=512, rating=4.1, in_stock=True, processor="AMD Ryzen 5 5625U", display='15.6" FHD'),
    "L005": dict(name="Dell Inspiron 14", brand="Dell", category="laptop", price=72490, ram_gb=16, storage_gb=512, rating=4.5, in_stock=True, processor="Intel Core i7-1355U", display='14" FHD+'),
    "L006": dict(name="MSI Modern 15", brand="MSI", category="laptop", price=54990, ram_gb=8, storage_gb=512, rating=4.0, in_stock=True, processor="Intel Core i5-1235U", display='15.6" FHD'),
    "L007": dict(name="Lenovo LOQ 15", brand="Lenovo", category="laptop", price=69990, ram_gb=16, storage_gb=512, rating=4.5, in_stock=True, processor="Intel Core i5-12450HX + RTX 3050", display='15.6" FHD 144Hz'),
    "L008": dict(name="ASUS TUF Gaming F15", brand="ASUS", category="laptop", price=66990, ram_gb=16, storage_gb=512, rating=4.4, in_stock=True, processor="Intel Core i5-11400H + RTX 3050", display='15.6" FHD 144Hz'),
    "L009": dict(name="HP Victus 16", brand="HP", category="laptop", price=73990, ram_gb=16, storage_gb=1024, rating=4.4, in_stock=True, processor="AMD Ryzen 7 7840HS", display='16.1" FHD 144Hz'),
    "L010": dict(name="Acer Swift Go 14", brand="Acer", category="laptop", price=65990, ram_gb=16, storage_gb=512, rating=4.3, in_stock=True, processor="Intel Core Ultra 5 125H", display='14" 2.8K OLED'),
    "L011": dict(name="Infinix INBook X3 Slim", brand="Infinix", category="laptop", price=39990, ram_gb=16, storage_gb=512, rating=4.2, in_stock=True, processor="Intel Core i5-1235U", display='14" FHD'),
    "L012": dict(name="Apple MacBook Air M2", brand="Apple", category="laptop", price=89900, ram_gb=8, storage_gb=256, rating=4.7, in_stock=True, processor="Apple M2", display='13.6" Liquid Retina'),
    "L013": dict(name="Samsung Galaxy Book3", brand="Samsung", category="laptop", price=61990, ram_gb=16, storage_gb=256, rating=4.3, in_stock=True, processor="Intel Core i5-1335U", display='15.6" FHD'),
    "L014": dict(name="Dell Vostro 3520", brand="Dell", category="laptop", price=52990, ram_gb=16, storage_gb=512, rating=4.3, in_stock=True, processor="Intel Core i5-1235U", display='15.6" FHD 120Hz'),
    "L015": dict(name="Lenovo ThinkPad E14", brand="Lenovo", category="laptop", price=79990, ram_gb=16, storage_gb=512, rating=4.6, in_stock=True, processor="Intel Core i7-1355U", display='14" WUXGA'),
    "L016": dict(name="HP Envy x360", brand="HP", category="laptop", price=69990, ram_gb=16, storage_gb=512, rating=4.5, in_stock=False, processor="AMD Ryzen 5 7530U", display='15.6" FHD Touch'),
    # ---------------- Smartphones ----------------
    "P001": dict(name="Samsung Galaxy S23 FE", brand="Samsung", category="smartphone", price=39999, ram_gb=8, storage_gb=128, rating=4.3, in_stock=True, processor="Exynos 2200", display='6.4" AMOLED 120Hz'),
    "P002": dict(name="OnePlus 12R", brand="OnePlus", category="smartphone", price=42999, ram_gb=16, storage_gb=256, rating=4.5, in_stock=True, processor="Snapdragon 8 Gen 2", display='6.78" AMOLED 120Hz'),
    "P003": dict(name="Google Pixel 8a", brand="Google", category="smartphone", price=52999, ram_gb=8, storage_gb=128, rating=4.4, in_stock=True, processor="Tensor G3", display='6.1" OLED 120Hz'),
    "P004": dict(name="iQOO Neo 9 Pro", brand="iQOO", category="smartphone", price=36999, ram_gb=12, storage_gb=256, rating=4.4, in_stock=True, processor="Snapdragon 8 Gen 2", display='6.78" AMOLED 144Hz'),
    "P005": dict(name="Redmi Note 13 Pro", brand="Xiaomi", category="smartphone", price=25999, ram_gb=8, storage_gb=256, rating=4.2, in_stock=True, processor="Snapdragon 7s Gen 2", display='6.67" AMOLED 120Hz'),
    "P006": dict(name="Nothing Phone (2a)", brand="Nothing", category="smartphone", price=23999, ram_gb=12, storage_gb=256, rating=4.4, in_stock=True, processor="Dimensity 7200 Pro", display='6.7" AMOLED 120Hz'),
    # ---------------- Tablets ----------------
    "T001": dict(name="Apple iPad (10th Gen)", brand="Apple", category="tablet", price=34900, ram_gb=4, storage_gb=64, rating=4.6, in_stock=True, processor="A14 Bionic", display='10.9" Liquid Retina'),
    "T002": dict(name="Samsung Galaxy Tab S9 FE", brand="Samsung", category="tablet", price=36999, ram_gb=8, storage_gb=128, rating=4.4, in_stock=True, processor="Exynos 1380", display='10.9" LCD 90Hz'),
    "T003": dict(name="Lenovo Tab P12", brand="Lenovo", category="tablet", price=26999, ram_gb=8, storage_gb=128, rating=4.2, in_stock=True, processor="Dimensity 7050", display='12.7" 3K LCD'),
    "T004": dict(name="Xiaomi Pad 6", brand="Xiaomi", category="tablet", price=24999, ram_gb=8, storage_gb=256, rating=4.4, in_stock=True, processor="Snapdragon 870", display='11" 2.8K 144Hz'),
}

# Which products each source lists, plus per-source deviations (conflicts / gaps).
_LISTINGS: dict[str, dict[str, dict]] = {
    "A": {
        "L001": {}, "L002": {}, "L004": {}, "L005": {}, "L008": {}, "L012": {},
        "L015": {}, "L016": {}, "P001": {}, "P003": {}, "T001": {}, "T002": {},
    },
    "B": {
        "L001": {"rating": 4.1},          # conflict with A (4.4) -> trusted source A wins
        "L003": {}, "L005": {}, "L007": {}, "L011": {}, "L013": {},
        "P002": {}, "P004": {}, "P006": {},
        "T002": {"price": 35999},          # minor price conflict with A
        "T003": {},
    },
    "C": {
        "L002": {"price": 61999},          # minor price conflict with A
        "L006": {}, "L007": {"price": 68990},  # minor price conflict with B
        "L008": {"storage_gb": None},      # gap filled from trusted source A
        "L009": {}, "L010": {"rating": None},  # missing rating -> rejected by Filter Agent
        "L014": {}, "P005": {}, "P006": {}, "T004": {},
    },
}

KNOWN_BRANDS = sorted({p["brand"] for p in _BASE.values()}, key=str.lower)


def get_source_catalog(source: str) -> list[dict]:
    """Return a deep copy of the listings exposed by one catalog source."""
    if source not in _LISTINGS:
        raise KeyError(f"Unknown catalog source '{source}'")
    records = []
    for pid, overrides in _LISTINGS[source].items():
        rec = {"product_id": pid, **copy.deepcopy(_BASE[pid]), **copy.deepcopy(overrides), "source": source}
        records.append(rec)
    return records


def all_products() -> list[dict]:
    """Canonical catalog (used only for reference views and tests)."""
    return [{"product_id": pid, **copy.deepcopy(p)} for pid, p in _BASE.items()]
