import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import clean  # noqa: E402


def test_exact_duplicates_removed():
    df = pd.DataFrame({"PO Number": ["PO-1", "PO-1", "PO-2"], "Qty": ["1", "1", "1"]})
    out, removed = clean.drop_duplicates(df)
    assert removed == 1
    assert list(out["PO Number"]) == ["PO-1", "PO-2"]


def test_vendor_variants_map_to_one_name():
    df = pd.DataFrame({"Vendor": [
        "Harbor Restaurant Equipment", "HARBOR RESTAURANT EQUIPMENT", "Harbor Rest. Equip.",
        "Northline  Foodservice ", "Northline Foodservice Inc.", "Metro FSE LLC",
    ]})
    out, spellings, vendors = clean.normalize_vendors(df)
    assert spellings == 6
    assert vendors == 3
    assert set(out["Vendor"]) == {"Harbor Restaurant Equipment", "Northline Foodservice", "Metro FSE"}


def test_unknown_vendor_raises():
    with pytest.raises(ValueError):
        clean.normalize_vendors(pd.DataFrame({"Vendor": ["Some New Vendor"]}))


def test_category_casing():
    assert clean.normalize_category("WALK-IN COOLER") == "Walk-in Cooler"
    assert clean.normalize_category("REACH-IN REFRIGERATOR") == "Reach-in Refrigerator"
    assert clean.normalize_category("Combi Oven") == "Combi Oven"


@pytest.mark.parametrize("text", ["$12,450.00", "12,450 USD", "12450.00"])
def test_price_formats_parse(text):
    assert clean.parse_price(text) == 12450.0


def test_mixed_date_formats_parse():
    s = pd.Series(["2025-03-14", "03/14/2025", "Mar 14 2025", ""])
    out = clean.parse_date_column(s)
    assert (out.iloc[:3] == pd.Timestamp("2025-03-14")).all()
    assert pd.isna(out.iloc[3])


def test_zero_quantity_rows_dropped():
    df = pd.DataFrame({"Qty": ["2", "0", "5", "-1"]})
    out, removed = clean.drop_zero_qty(df)
    assert removed == 2
    assert list(out["Qty"]) == [2, 5]


def test_extra_zero_price_typo_corrected():
    df = pd.DataFrame({
        "Equipment Category": ["Fryer"] * 5,
        "Order Date": pd.to_datetime(["2025-01-10"] * 5),
        "Unit Price": [4200.0, 4300.0, 4150.0, 4250.0, 42500.0],
    })
    out, fixed = clean.fix_extra_zero_prices(df)
    assert fixed == 1
    assert out["Unit Price"].iloc[4] == 4250.0
    assert out["Unit Price"].iloc[:4].tolist() == [4200.0, 4300.0, 4150.0, 4250.0]
