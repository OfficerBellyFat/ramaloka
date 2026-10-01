"""RAMALOKA dead-stock warning utilities.

Pure functions only — no Streamlit imports here.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

REQUIRED_STOCK_COLUMNS = ["product", "stock_qty", "expiry_date"]

RISK_ORDER = ["High", "Medium", "Low"]


def validate_stock(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and clean a stock CSV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Raw stock data from the uploaded CSV.

    Returns
    -------
    pd.DataFrame
        Cleaned DataFrame.

    Raises
    ------
    ValueError
        If required columns are missing or no valid rows remain.
    """
    if df is None or df.empty:
        raise ValueError("File stok kosong. Mohon unggah CSV yang berisi data stok.")

    missing = [col for col in REQUIRED_STOCK_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            f"Kolom wajib tidak ditemukan pada file stok: {', '.join(missing)}. "
            f"Kolom yang tersedia: {', '.join(df.columns)}."
        )

    df = df.copy()
    df["expiry_date"] = pd.to_datetime(df["expiry_date"], errors="coerce", format="%Y-%m-%d")
    df["product"] = df["product"].astype(str).str.strip()

    df["stock_qty"] = pd.to_numeric(df["stock_qty"], errors="coerce")

    # Drop rows with missing product
    bad_product = df["product"].isna() | (df["product"] == "")
    if bad_product.all():
        raise ValueError("Tidak ada nama produk yang valid pada file stok.")
    df = df.loc[~bad_product].copy()

    # Drop rows with unparseable expiry date
    bad_expiry = df["expiry_date"].isna()
    if bad_expiry.any():
        # Keep cleaning but raise only if nothing left.
        df = df.loc[~bad_expiry].copy()

    # Treat missing/negative stock as 0
    df["stock_qty"] = df["stock_qty"].fillna(0).clip(lower=0).astype(int)

    if df.empty:
        raise ValueError(
            "Tidak ada data stok yang valid setelah pembersihan. Mohon periksa file CSV Anda."
        )

    # Keep only the last row per product if duplicates exist.
    df = df.drop_duplicates(subset=["product"], keep="last")

    return df[["product", "stock_qty", "expiry_date"]].reset_index(drop=True)


def assess_dead_stock(
    stock_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    today: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Assess dead-stock risk by comparing stock and expiry against forecast demand.

    Parameters
    ----------
    stock_df : pd.DataFrame
        Cleaned stock DataFrame from ``validate_stock``.
    forecast_df : pd.DataFrame
        Forecast DataFrame from ``forecast_demand``.
    today : Optional[pd.Timestamp]
        Reference date. Defaults to today (date only, normalized to midnight).

    Returns
    -------
    pd.DataFrame
        Risk assessment sorted High -> Medium -> Low.
    """
    if today is None:
        today = pd.Timestamp.now().normalize()
    else:
        today = pd.Timestamp(today).normalize()

    stock_df = stock_df.copy()
    stock_df["expiry_date"] = pd.to_datetime(stock_df["expiry_date"]).dt.normalize()

    # Average forecast per product and confidence lookup.
    forecast_summary = (
        forecast_df.groupby("product")
        .agg(avg_daily_demand=("forecast_qty", "mean"), confidence=("confidence", "first"))
        .reset_index()
    )

    merged = stock_df.merge(forecast_summary, on="product", how="left")
    merged["avg_daily_demand"] = merged["avg_daily_demand"].fillna(0.0)
    merged["confidence"] = merged["confidence"].fillna(0.0)

    rows: list[dict] = []
    for _, row in merged.iterrows():
        product = row["product"]
        stock_qty = int(row["stock_qty"])
        expiry_date = row["expiry_date"]
        avg_demand = float(row["avg_daily_demand"])
        confidence = float(row["confidence"])
        low_confidence_note = " Perkiraan rendah, peringatan ini perlu dicek ulang." if confidence < 0.4 else ""

        days_until_expiry = (expiry_date - today).days

        if avg_demand <= 0:
            days_to_sell = float("inf")
        else:
            days_to_sell = stock_qty / avg_demand

        # Determine risk and suggested action.
        if days_until_expiry < 0:
            risk = "High"
            action = f"Produk sudah kedaluwarsa. Pertimbangkan buang atau donasikan.{low_confidence_note}"
        elif avg_demand <= 0 and stock_qty > 0:
            risk = "High"
            action = f"Tidak ada permintaan yang diprediksi. Pertimbangkan diskon besar atau bundling.{low_confidence_note}"
        elif days_to_sell > days_until_expiry:
            risk = "High"
            action = f"Stok kemungkinan tidak habis sebelum kedaluwarsa. Pertimbangkan diskon atau promo bundling.{low_confidence_note}"
        elif days_to_sell > 0.7 * days_until_expiry:
            risk = "Medium"
            action = f"Stok mulai menumpuk. Kurangi pembelian berikutnya dan pantau penjualan.{low_confidence_note}"
        else:
            risk = "Low"
            action = f"Stok aman.{low_confidence_note}"

        potential_wasted = max(0.0, stock_qty - avg_demand * days_until_expiry)

        rows.append({
            "product": product,
            "stock_qty": stock_qty,
            "expiry_date": expiry_date.date(),
            "days_until_expiry": days_until_expiry,
            "avg_daily_demand": round(avg_demand, 2),
            "days_to_sell": round(days_to_sell, 2) if np.isfinite(days_to_sell) else -1.0,
            "risk": risk,
            "suggested_action": action.strip(),
            "potential_units_wasted": round(potential_wasted, 2),
            "forecast_confidence": confidence,
        })

    result = pd.DataFrame(rows)

    # Products in sales history but missing stock are intentionally not reported here.
    # Products in stock but missing from forecast (no sales history) get a special flag.
    no_history_mask = result["avg_daily_demand"] == 0
    if no_history_mask.any():
        # Only flag as "No sales history" when confidence is 0 and demand is 0.
        result.loc[no_history_mask, "risk"] = "High"
        result.loc[no_history_mask, "suggested_action"] = (
            "Tidak ada riwayat penjualan. Periksa secara manual sebelum memesan ulang."
        )

    # Sort by risk severity.
    result["risk_sort"] = result["risk"].map({r: i for i, r in enumerate(RISK_ORDER)})
    result = result.sort_values(["risk_sort", "days_until_expiry"]).drop(columns=["risk_sort"])

    return result.reset_index(drop=True)
