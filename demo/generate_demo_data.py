"""Generate deterministic demo data for RAMALOKA.

Reference date: data dihasilkan relatif terhadap tanggal hari ini.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make core importable regardless of cwd.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.forecast import forecast_demand, validate_sales
from core.deadstock import assess_dead_stock, validate_stock

RNG = np.random.default_rng(seed=42)

PRODUCTS = [
    "Nasi Goreng",
    "Ayam Geprek",
    "Roti Bakar",
    "Kopi Susu",
    "Es Teh Manis",
    "Mie Goreng",
    "Sate Taichan",
    "Bakso Cup",
    "Pisang Goreng",
    "Donat Kentang",
]

N_DAYS = 60
TODAY = pd.Timestamp.now().normalize()
HISTORY_START = TODAY - pd.Timedelta(days=N_DAYS - 1)
HISTORY_DATES = pd.date_range(start=HISTORY_START, periods=N_DAYS, freq="D")

# Base daily demand and weekend uplift factor for each product.
PRODUCT_PARAMS = {
    "Nasi Goreng": (25, 1.4),
    "Ayam Geprek": (18, 1.3),
    "Roti Bakar": (12, 1.5),
    "Kopi Susu": (30, 1.2),
    "Es Teh Manis": (35, 1.1),
    "Mie Goreng": (15, 1.3),
    "Sate Taichan": (10, 1.6),
    "Bakso Cup": (8, 1.4),
    "Pisang Goreng": (5, 1.5),   # cold start, only last 5 days
    "Donat Kentang": (0, 1.0),    # zero recent sales
}


def generate_sales() -> pd.DataFrame:
    rows = []
    for product, (base, weekend_factor) in PRODUCT_PARAMS.items():
        if product == "Pisang Goreng":
            product_dates = HISTORY_DATES[-5:]
        else:
            product_dates = HISTORY_DATES

        for date in product_dates:
            is_weekend = date.weekday() >= 5
            mean = base * (weekend_factor if is_weekend else 1.0)
            if product == "Donat Kentang":
                qty = 0
            else:
                # Poisson-like integer noise, floored at 0.
                qty = max(0, int(RNG.poisson(mean) + RNG.normal(0, max(1, mean * 0.15))))
            rows.append({"date": date.strftime("%Y-%m-%d"), "product": product, "qty_sold": qty})

    return pd.DataFrame(rows)


def generate_stock() -> pd.DataFrame:
    """Design stock so that the pipeline yields >=2 High, >=2 Medium, >=2 Low risks."""
    stock_specs = [
        # High risk: already expired.
        {"product": "Sate Taichan", "stock_qty": 20, "days_to_expiry": -2},
        # High risk: zero demand with stock remaining (no recent sales -> flagged no history).
        {"product": "Donat Kentang", "stock_qty": 50, "days_to_expiry": 14},
        # Medium risk: days_to_sell > 0.7 * days_until_expiry.
        {"product": "Ayam Geprek", "stock_qty": 160, "days_to_expiry": 10},
        {"product": "Es Teh Manis", "stock_qty": 350, "days_to_expiry": 12},
        # Low risk: safe stock.
        {"product": "Nasi Goreng", "stock_qty": 30, "days_to_expiry": 14},
        {"product": "Kopi Susu", "stock_qty": 40, "days_to_expiry": 14},
        # Low risk / cold start with low confidence.
        {"product": "Pisang Goreng", "stock_qty": 10, "days_to_expiry": 14},
        # Low risk.
        {"product": "Mie Goreng", "stock_qty": 25, "days_to_expiry": 14},
        # Low risk.
        {"product": "Roti Bakar", "stock_qty": 50, "days_to_expiry": 10},
        # Low risk.
        {"product": "Bakso Cup", "stock_qty": 25, "days_to_expiry": 10},
    ]

    rows = []
    for spec in stock_specs:
        expiry = TODAY + pd.Timedelta(days=spec["days_to_expiry"])
        rows.append({
            "product": spec["product"],
            "stock_qty": spec["stock_qty"],
            "expiry_date": expiry.strftime("%Y-%m-%d"),
        })

    return pd.DataFrame(rows)


def main() -> None:
    demo_dir = Path(__file__).parent
    demo_dir.mkdir(exist_ok=True)

    sales_path = demo_dir / "sales_sample.csv"
    stock_path = demo_dir / "stock_sample.csv"
    output_path = demo_dir / "output_sample.json"

    sales_df = generate_sales()
    stock_df = generate_stock()

    sales_df.to_csv(sales_path, index=False)
    stock_df.to_csv(stock_path, index=False)

    # Run pipeline with today's date.
    cleaned_sales, sales_warnings = validate_sales(sales_df)
    cleaned_stock = validate_stock(stock_df)
    forecast = forecast_demand(cleaned_sales, horizon=7, window=7)
    warnings = assess_dead_stock(cleaned_stock, forecast, today=TODAY)

    risk_counts = warnings["risk"].value_counts().reindex(["High", "Medium", "Low"], fill_value=0).to_dict()
    print("Risk distribution:", risk_counts)

    output = {
        "reference_date": TODAY.strftime("%Y-%m-%d"),
        "sales_warnings": sales_warnings,
        "forecast": json.loads(forecast.to_json(orient="records", date_format="iso")),
        "warnings": json.loads(warnings.to_json(orient="records", date_format="iso")),
        "risk_distribution": risk_counts,
    }

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {sales_path}")
    print(f"Wrote {stock_path}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
