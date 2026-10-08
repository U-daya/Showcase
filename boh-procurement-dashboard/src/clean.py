"""Clean the raw purchase-order export.

Every step adds an entry to a cleaning log (step name, row count, note) so the
dashboard can show exactly what was fixed.

Run:  python src/clean.py
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "data" / "raw" / "raw_equipment_pos.csv"
CLEAN_PATH = ROOT / "data" / "clean" / "clean_equipment_pos.csv"
LOG_PATH = ROOT / "data" / "clean" / "cleaning_log.json"

DATE_COLS = ["Order Date", "Promised Date", "Delivered Date"]
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%b %d %Y"]

# Vendor name "keys" (lowercase, no punctuation, no Inc/LLC) -> canonical name
VENDOR_ALIASES = {
    "northline foodservice": "Northline Foodservice",
    "keystone kitchen supply": "Keystone Kitchen Supply",
    "keystone kitchen sup": "Keystone Kitchen Supply",
    "harbor restaurant equipment": "Harbor Restaurant Equipment",
    "harbor rest equip": "Harbor Restaurant Equipment",
    "allied commercial": "Allied Commercial",
    "metro fse": "Metro FSE",
    "summit equipment co": "Summit Equipment Co",
}


class CleaningLog:
    def __init__(self):
        self.steps = []

    def add(self, step, rows, note, value=None):
        """value is the headline number the dashboard shows for this step."""
        self.steps.append({"step": step, "rows": int(rows), "value": value, "note": note})
        print(f"  {step:<30} {rows:>6,} rows   {note}")


# ---------- individual steps (small functions so tests can call them) ----------

def load_raw(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def drop_duplicates(df):
    out = df.drop_duplicates().reset_index(drop=True)
    return out, len(df) - len(out)


def vendor_key(name):
    key = re.sub(r"[.,]", "", str(name)).lower()
    key = re.sub(r"\s+", " ", key).strip()
    key = re.sub(r"\s+(inc|llc)$", "", key)
    return key


def normalize_vendors(df):
    out = df.copy()
    spellings = out["Vendor"].nunique()
    keys = out["Vendor"].map(vendor_key)
    unknown = sorted(set(keys) - set(VENDOR_ALIASES))
    if unknown:
        raise ValueError(f"Unknown vendor spellings, add them to VENDOR_ALIASES: {unknown}")
    out["Vendor"] = keys.map(VENDOR_ALIASES)
    return out, spellings, out["Vendor"].nunique()


def normalize_category(name):
    """'WALK-IN COOLER' -> 'Walk-in Cooler' (lowercase after a hyphen)."""
    words = re.sub(r"\s+", " ", str(name)).strip().split(" ")
    fixed = []
    for word in words:
        parts = word.split("-")
        fixed.append("-".join([parts[0].capitalize()] + [p.lower() for p in parts[1:]]))
    return " ".join(fixed)


def normalize_categories(df):
    out = df.copy()
    before = out["Equipment Category"]
    out["Equipment Category"] = before.map(normalize_category)
    return out, int((before != out["Equipment Category"]).sum())


def parse_price(text):
    cleaned = re.sub(r"[$,]|USD", "", str(text)).strip()
    return float(cleaned) if cleaned else float("nan")


def parse_prices(df):
    out = df.copy()
    out["Unit Price"] = out["Unit Price"].map(parse_price)
    return out


def parse_date_column(series):
    """Try each known format and keep whichever one matches."""
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    text = series.astype(str).str.strip()
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        result = result.fillna(parsed)
    return result


def parse_dates(df):
    out = df.copy()
    unparsed = 0
    for col in DATE_COLS:
        out[col] = parse_date_column(out[col])
        nonblank = df[col].astype(str).str.strip() != ""
        unparsed += int((out[col].isna() & nonblank).sum())
    return out, unparsed


def drop_zero_qty(df):
    out = df.copy()
    out["Qty"] = pd.to_numeric(out["Qty"], errors="coerce")
    keep = out["Qty"] > 0
    out = out[keep].reset_index(drop=True)
    out["Qty"] = out["Qty"].astype(int)
    return out, int((~keep).sum())


def fix_extra_zero_prices(df, threshold=4.0):
    """A price more than 4x the category/year median is almost always a typo
    with one extra zero, so divide it by 10."""
    out = df.copy()
    year = out["Order Date"].dt.year
    median = out.groupby([out["Equipment Category"], year])["Unit Price"].transform("median")
    typo = out["Unit Price"] > threshold * median
    out.loc[typo, "Unit Price"] = (out.loc[typo, "Unit Price"] / 10).round(2)
    return out, int(typo.sum())


# ---------- full pipeline ----------

def clean(raw_path=RAW_PATH):
    log = CleaningLog()

    df = load_raw(raw_path)
    log.add("Load raw export", len(df), "Raw rows read from the purchasing export, all as text", len(df))

    df, n_dupes = drop_duplicates(df)
    log.add("Drop duplicate rows", len(df), "Exact duplicate rows removed (re-exported POs)", n_dupes)

    df, n_spellings, n_vendors = normalize_vendors(df)
    log.add("Merge vendor names", len(df),
            f"{n_spellings} spellings merged into {n_vendors} vendors", n_spellings)

    df, n_cats = normalize_categories(df)
    log.add("Fix category names", len(df), "Category names in ALL CAPS set to standard casing", n_cats)

    df = parse_prices(df)
    log.add("Parse unit prices", len(df), "Prices like \"$12,450.00\" and \"12,450 USD\" turned into numbers", len(df))

    df, n_bad_dates = parse_dates(df)
    log.add("Parse dates", len(df),
            f"3 date columns in 3 formats parsed ({n_bad_dates} values could not be read)", len(df) * 3)

    df, n_zero = drop_zero_qty(df)
    log.add("Remove zero-quantity rows", len(df), "Rows with Qty of 0 or less removed", n_zero)

    df, n_typos = fix_extra_zero_prices(df)
    log.add("Fix extra-zero price typos", len(df),
            "Prices over 4x the category/year median divided by 10", n_typos)

    n_missing = int(df["Promised Date"].isna().sum())
    log.add("Flag missing promised dates", len(df),
            "Kept for pricing, left out of on-time %", n_missing)

    log.add("Clean rows ready for analysis", len(df), "Final clean purchase orders", len(df))
    return df, log


def main():
    print("Cleaning raw purchase orders")
    df, log = clean()
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for col in DATE_COLS:
        out[col] = out[col].dt.strftime("%Y-%m-%d")
    out.to_csv(CLEAN_PATH, index=False)
    LOG_PATH.write_text(json.dumps(log.steps, indent=2))
    print(f"Wrote {len(df):,} clean rows to {CLEAN_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
