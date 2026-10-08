"""Generate a messy, sample purchase-order export for BOH kitchen equipment.

This is SAMPLE data. It is made up to look like a real procurement export
(mixed formats, typos, duplicate rows). No real company data is used.

Run:  python src/generate_sample_data.py
"""
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "raw" / "raw_equipment_pos.csv"

N_ORDERS = 1150
N_DUPLICATES = 38
START = date(2024, 1, 1)
END = date(2026, 6, 30)

# category: (base unit price, base lead time in days, yearly price increase)
CATEGORIES = {
    "Combi Oven": (18500, 42, 0.06),
    "Fryer": (4200, 21, 0.04),
    "Exhaust Hood": (9800, 56, 0.08),
    "Walk-in Cooler": (24000, 63, 0.07),
    "Reach-in Refrigerator": (5200, 18, 0.03),
    "Dish Machine": (11500, 35, 0.05),
    "Ice Machine": (3900, 14, 0.03),
    "Induction Range": (7600, 28, 0.02),
    "Electrical Panel": (6300, 49, 0.10),
    "Stainless Prep Table": (1150, 10, 0.02),
}
BIG_ITEMS = {"Walk-in Cooler", "Exhaust Hood", "Combi Oven"}

# vendor: (price factor, on-time probability, typical days late when late)
VENDORS = {
    "Northline Foodservice": (1.00, 0.91, 4),
    "Keystone Kitchen Supply": (0.95, 0.72, 11),
    "Harbor Restaurant Equipment": (1.04, 0.95, 3),
    "Allied Commercial": (0.92, 0.64, 16),
    "Metro FSE": (0.99, 0.84, 7),
    "Summit Equipment Co": (1.07, 0.97, 2),
}

# The different ways each vendor name shows up in the export (21 total)
VENDOR_SPELLINGS = {
    "Northline Foodservice": ["Northline Foodservice", "NORTHLINE FOODSERVICE",
                              "Northline Foodservice Inc.", "Northline  Foodservice "],
    "Keystone Kitchen Supply": ["Keystone Kitchen Supply", "KEYSTONE KITCHEN SUPPLY",
                                "Keystone Kitchen Supply LLC", "Keystone Kitchen Sup."],
    "Harbor Restaurant Equipment": ["Harbor Restaurant Equipment", "Harbor Rest. Equip.",
                                    "HARBOR RESTAURANT EQUIPMENT"],
    "Allied Commercial": ["Allied Commercial", "ALLIED COMMERCIAL",
                          "Allied Commercial Inc.", "Allied Commercial "],
    "Metro FSE": ["Metro FSE", "METRO FSE", "Metro FSE LLC"],
    "Summit Equipment Co": ["Summit Equipment Co", "SUMMIT EQUIPMENT CO", "Summit Equipment Co."],
}

SITES = ["NJ-Union", "NY-Manhattan", "NJ-Paramus", "PA-King of Prussia",
         "NY-Westchester", "MA-Burlington"]


def bulk_discount(qty):
    if qty >= 10:
        return 0.13
    if qty >= 5:
        return 0.08
    if qty >= 3:
        return 0.02
    return 0.0


def pick_qty(category):
    if category in BIG_ITEMS:
        return random.choices([1, 2, 3, 4, 5, 6], weights=[26, 24, 17, 13, 11, 9])[0]
    band = random.choices(["1-2", "3-4", "5-9", "10+"], weights=[34, 18, 24, 24])[0]
    return {"1-2": lambda: random.randint(1, 2),
            "3-4": lambda: random.randint(3, 4),
            "5-9": lambda: random.randint(5, 9),
            "10+": lambda: random.randint(10, 24)}[band]()


def fmt_price(value):
    style = random.random()
    if style < 0.4:
        return f"${value:,.2f}"
    if style < 0.75:
        return f"{value:.2f}"
    return f"{value:,.0f} USD"


def fmt_date(d):
    style = random.random()
    if style < 0.5:
        return d.strftime("%Y-%m-%d")
    if style < 0.8:
        return d.strftime("%m/%d/%Y")
    return d.strftime("%b %d %Y")


def make_order():
    span = (END - START).days
    order_date = START + timedelta(days=random.randint(0, span))
    category = random.choice(list(CATEGORIES))
    vendor = random.choice(list(VENDORS))
    base_price, base_lead, yearly_inc = CATEGORIES[category]
    price_factor, on_time_p, typical_late = VENDORS[vendor]

    qty = pick_qty(category)
    years = (order_date - START).days / 365.25
    price = (base_price * (1 + yearly_inc) ** years * price_factor
             * (1 - bulk_discount(qty)) * (1 + random.uniform(-0.05, 0.05)))

    lead = max(3, round(random.gauss(base_lead, base_lead * 0.18)))
    promised = order_date + timedelta(days=lead)
    if random.random() < on_time_p:
        delivered = promised - timedelta(days=random.randint(0, 3))
    else:
        delivered = promised + timedelta(days=max(1, math.ceil(random.expovariate(1 / typical_late))))

    return {
        "PO Number": "",
        "Vendor": vendor,
        "Equipment Category": category,
        "Qty": qty,
        "Unit Price": round(price, 2),
        "Order Date": order_date,
        "Promised Date": promised,
        "Delivered Date": delivered,
        "Site": random.choice(SITES),
    }


def make_messy(order):
    """Turn one clean order into the way it looks in a real export."""
    row = dict(order)
    row["Vendor"] = random.choice(VENDOR_SPELLINGS[order["Vendor"]])
    if random.random() < 0.08:
        row["Equipment Category"] = order["Equipment Category"].upper()
    price = order["Unit Price"]
    if random.random() < 0.012:
        price = price * 10  # someone typed an extra zero
    row["Unit Price"] = fmt_price(price)
    if random.random() < 0.008:
        row["Qty"] = 0
    row["Order Date"] = fmt_date(order["Order Date"])
    row["Promised Date"] = "" if random.random() < 0.015 else fmt_date(order["Promised Date"])
    row["Delivered Date"] = fmt_date(order["Delivered Date"])
    return row


def main():
    orders = [make_order() for _ in range(N_ORDERS)]
    orders.sort(key=lambda o: o["Order Date"])
    for i, order in enumerate(orders, start=1):
        order["PO Number"] = f"PO-{order['Order Date']:%y}-{i:05d}"
    rows = [make_messy(o) for o in orders]

    # Re-exported rows: exact copies dropped back into the file
    for dup in random.sample(rows, N_DUPLICATES):
        rows.insert(random.randint(0, len(rows)), dict(dup))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} raw rows to {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
