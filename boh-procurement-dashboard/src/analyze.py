"""Compute every number the dashboard shows and write dashboard_data.json.

Run:  python src/analyze.py   (after clean.py)
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN_PATH = ROOT / "data" / "clean" / "clean_equipment_pos.csv"
LOG_PATH = ROOT / "data" / "clean" / "cleaning_log.json"
RAW_PATH = ROOT / "data" / "raw" / "raw_equipment_pos.csv"
OUT_PATH = ROOT / "dashboard" / "dashboard_data.json"

ALL = "All equipment"
BANDS = ["1-2", "3-4", "5-9", "10+"]
ON_TIME_TARGET = 90.0


def r(x, digits=1):
    """Round for JSON, turning NaN into None."""
    return None if pd.isna(x) else round(float(x), digits) + 0.0  # + 0.0 turns -0.0 into 0.0


def qty_band(qty):
    if qty <= 2:
        return "1-2"
    if qty <= 4:
        return "3-4"
    if qty <= 9:
        return "5-9"
    return "10+"


def add_fields(df):
    df = df.copy()
    for col in ["Order Date", "Promised Date", "Delivered Date"]:
        df[col] = pd.to_datetime(df[col])
    df["Spend"] = df["Qty"] * df["Unit Price"]
    df["Year"] = df["Order Date"].dt.year
    df["Quarter"] = df["Order Date"].dt.to_period("Q").astype(str)
    df["Lead Days"] = (df["Delivered Date"] - df["Order Date"]).dt.days
    df["Quoted Days"] = (df["Promised Date"] - df["Order Date"]).dt.days
    df["Days Late"] = (df["Delivered Date"] - df["Promised Date"]).dt.days
    # NaN when there is no promised date, so those rows drop out of on-time %
    df["On Time"] = (df["Days Late"] <= 0).where(df["Days Late"].notna())
    df["Qty Band"] = df["Qty"].map(qty_band)

    # Reference price = median unit price of 1-2 unit orders, same category and year
    small = df[df["Qty"] <= 2]
    ref = small.groupby(["Equipment Category", "Year"])["Unit Price"].median().rename("Ref Price")
    df = df.join(ref, on=["Equipment Category", "Year"])
    df["Price vs Ref"] = df["Unit Price"] / df["Ref Price"] - 1
    return df


def on_time_pct(df):
    return df["On Time"].dropna().astype(float).mean() * 100


def kpis(df):
    return {
        "po_count": int(len(df)),
        "total_spend": r(df["Spend"].sum(), 0),
        "on_time_pct": r(on_time_pct(df)),
        "lead_median": r(df["Lead Days"].median(), 0),
        "lead_p90": r(df["Lead Days"].quantile(0.9), 0),
    }


def price_trend(df):
    """Quarterly price index from 1-2 unit orders only. Each order is indexed
    against its own category's first-quarter median, then we take the
    quarterly median and rescale so the first quarter is exactly 100."""
    small = df[df["Qty"] <= 2].copy()
    first_q = small["Quarter"].min()
    base = small[small["Quarter"] == first_q].groupby("Equipment Category")["Unit Price"].median()
    small["Index"] = small["Unit Price"] / small["Equipment Category"].map(base) * 100
    by_q = small.dropna(subset=["Index"]).groupby("Quarter")["Index"].agg(["median", "count"])
    by_q["median"] = by_q["median"] / by_q["median"].iloc[0] * 100
    return [{"quarter": q.replace("Q", " Q"), "index": r(row["median"]), "orders": int(row["count"])}
            for q, row in by_q.iterrows()]


def bulk_thresholds(df):
    out = []
    for band in BANDS:
        sub = df[df["Qty Band"] == band]
        disc = -sub["Price vs Ref"].median() * 100 if len(sub) else None
        out.append({"band": band, "discount_pct": r(disc), "orders": int(len(sub))})
    return out


def vendor_scorecard(df):
    rows = []
    for vendor, sub in df.groupby("Vendor"):
        late = sub[sub["On Time"] == False]  # noqa: E712 (NaN must not count as late)
        rows.append({
            "vendor": vendor,
            "pos": int(len(sub)),
            "spend": r(sub["Spend"].sum(), 0),
            "on_time_pct": r(on_time_pct(sub)),
            "avg_days_late": r(late["Days Late"].mean()),
            "median_lead": r(sub["Lead Days"].median(), 0),
            "price_vs_ref_pct": r(sub["Price vs Ref"].median() * 100),
        })
    return sorted(rows, key=lambda v: -(v["on_time_pct"] or 0))


def lead_times(df, by):
    rows = []
    for name, sub in df.groupby(by):
        rows.append({
            "name": name,
            "quoted_median": r(sub["Quoted Days"].median(), 0),
            "actual_median": r(sub["Lead Days"].median(), 0),
            "actual_p90": r(sub["Lead Days"].quantile(0.9), 0),
            "orders": int(len(sub)),
        })
    return sorted(rows, key=lambda x: -x["actual_p90"])


def money(x):
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:,.0f}K"


def findings(view):
    """Plain-English findings for an estimator, built from the numbers."""
    out = []
    trend = view["price_trend"]
    first, last = trend[0], trend[-1]
    change = last["index"] - 100
    direction = "up" if change >= 0 else "down"
    out.append({
        "title": f"Prices are {direction} {abs(change):.1f}% since {first['quarter']}",
        "body": (f"Small-order unit prices moved from 100 in {first['quarter']} to {last['index']:.1f} "
                 f"in {last['quarter']}. An estimate built on a quote from {first['quarter']} will come in "
                 f"about {abs(change):.0f}% {'low' if change >= 0 else 'high'}, so refresh old quotes before using them."),
    })

    bands = [b for b in view["bulk"] if b["discount_pct"] is not None and b["orders"] >= 3]
    if len(bands) >= 2:
        jumps = [(bands[i]["discount_pct"] - bands[i - 1]["discount_pct"], bands[i - 1], bands[i])
                 for i in range(1, len(bands))]
        jump, before, after = max(jumps, key=lambda j: j[0])
        view["bulk_jump_band"] = after["band"]
        out.append({
            "title": f"The big discount starts at {after['band']} units",
            "body": (f"Discount vs a 1-2 unit order goes from {before['discount_pct']:.1f}% at "
                     f"{before['band']} units to {after['discount_pct']:.1f}% at {after['band']} units "
                     f"(+{jump:.1f} points). If an order is just under {after['band'].rstrip('+').split('-')[0]} units, compare "
                     f"the cost of one extra unit against the savings, or combine orders across sites."),
        })
    else:
        view["bulk_jump_band"] = None
        out.append({"title": "Not enough order sizes to find a bulk threshold",
                    "body": "This category is almost always bought one or two at a time."})

    vendors = [v for v in view["vendors"] if v["on_time_pct"] is not None]
    cheapest = min(vendors, key=lambda v: v["price_vs_ref_pct"])
    reliable = max(vendors, key=lambda v: (v["on_time_pct"], -v["price_vs_ref_pct"]))
    late = (f", about {cheapest['avg_days_late']:.0f} days late when late"
            if cheapest["avg_days_late"] is not None else "")
    cheap_side = "under" if cheapest["price_vs_ref_pct"] < 0 else "over"
    if cheapest["vendor"] == reliable["vendor"]:
        out.append({
            "title": f"{cheapest['vendor']} is cheapest and most reliable here",
            "body": (f"{cheapest['vendor']} is {abs(cheapest['price_vs_ref_pct']):.1f}% {cheap_side} typical "
                     f"price and {cheapest['on_time_pct']:.1f}% on time for this category."),
        })
    else:
        out.append({
            "title": "The cheapest vendor is not the most reliable",
            "body": (f"{cheapest['vendor']} is {abs(cheapest['price_vs_ref_pct']):.1f}% {cheap_side} typical "
                     f"price but only {cheapest['on_time_pct']:.1f}% on time{late}. "
                     f"{reliable['vendor']} is {reliable['on_time_pct']:.1f}% on time at "
                     f"{reliable['price_vs_ref_pct']:+.1f}%. For critical-path items the reliable vendor "
                     f"may cost less overall once a delayed opening is counted."),
        })

    lt = view["lead_times"]
    worst = max(lt, key=lambda x: x["actual_p90"] - x["quoted_median"])
    gap = worst["actual_p90"] - worst["quoted_median"]
    out.append({
        "title": "Plan to the p90, not the quote",
        "body": (f"{worst['name']} orders are quoted at {worst['quoted_median']:.0f} days, but 1 in 10 orders "
                 f"takes {worst['actual_p90']:.0f} days or more ({gap:.0f} days past the quote). "
                 f"Plan to the p90, not the quote."),
    })
    return out


def build_view(df, by_category):
    view = {
        "kpis": kpis(df),
        "price_trend": price_trend(df),
        "bulk": bulk_thresholds(df),
        "vendors": vendor_scorecard(df),
        "lead_by": "Equipment Category" if by_category else "Vendor",
        "lead_times": lead_times(df, "Equipment Category" if by_category else "Vendor"),
    }
    view["findings"] = findings(view)
    return view


def main():
    df = add_fields(pd.read_csv(CLEAN_PATH))
    raw_rows = sum(1 for _ in open(RAW_PATH)) - 1
    categories = sorted(df["Equipment Category"].unique())

    views = {ALL: build_view(df, by_category=True)}
    for cat in categories:
        views[cat] = build_view(df[df["Equipment Category"] == cat], by_category=False)

    data = {
        "meta": {
            "raw_rows": raw_rows,
            "clean_rows": int(len(df)),
            "first_order": df["Order Date"].min().strftime("%Y-%m-%d"),
            "last_order": df["Order Date"].max().strftime("%Y-%m-%d"),
            "on_time_target": ON_TIME_TARGET,
        },
        "cleaning_log": json.loads(LOG_PATH.read_text()),
        "categories": [ALL] + categories,
        "views": views,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=1))

    k = views[ALL]["kpis"]
    print(f"Analyzed {k['po_count']:,} POs, {money(k['total_spend'])} spend, "
          f"{k['on_time_pct']}% on time, lead {k['lead_median']:.0f}d median / {k['lead_p90']:.0f}d p90")
    for f in views[ALL]["findings"]:
        print(f"  - {f['title']}: {f['body']}")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
