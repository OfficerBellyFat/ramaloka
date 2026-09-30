"""RAMALOKA demand forecasting utilities.

Pure functions only — no Streamlit imports here.
"""

from __future__ import annotations

import warnings
from typing import Tuple

import numpy as np
import pandas as pd

REQUIRED_SALES_COLUMNS = ["date", "product", "qty_sold"]


def validate_sales(df: pd.DataFrame) -> Tuple[pd.DataFrame, list[str]]:
    """Validate and clean a sales CSV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Raw sales data from the uploaded CSV.

    Returns
    -------
    Tuple[pd.DataFrame, list[str]]
        Cleaned DataFrame and a list of human-readable warnings.

    Raises
    ------
    ValueError
        If required columns are missing.
    """
    if df is None or df.empty:
        raise ValueError("File penjualan kosong. Mohon unggah CSV yang berisi data penjualan.")

    missing = [col for col in REQUIRED_SALES_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            f"Kolom wajib tidak ditemukan pada file penjualan: {', '.join(missing)}. "
            f"Kolom yang tersedia: {', '.join(df.columns)}."
        )

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="%Y-%m-%d")
    initial_rows = len(df)

    warnings_list: list[str] = []

    # Drop rows with unparseable dates
    bad_date = df["date"].isna()
    if bad_date.any():
        warnings_list.append(
            f"{bad_date.sum()} baris memiliki tanggal yang tidak valid dan diabaikan."
        )
        df = df.loc[~bad_date].copy()

    # Coerce qty_sold to numeric
    df["qty_sold"] = pd.to_numeric(df["qty_sold"], errors="coerce")

    # Drop rows with missing product
    missing_product = df["product"].isna() | (df["product"].astype(str).str.strip() == "")
    if missing_product.any():
        warnings_list.append(
            f"{missing_product.sum()} baris memiliki nama produk kosong dan diabaikan."
        )
        df = df.loc[~missing_product].copy()

    # Drop rows with missing quantity
    missing_qty = df["qty_sold"].isna()
    if missing_qty.any():
        warnings_list.append(
            f"{missing_qty.sum()} baris memiliki jumlah terjual kosong dan diabaikan."
        )
        df = df.loc[~missing_qty].copy()

    # Flag negative quantities
    negative_qty = df["qty_sold"] < 0
    if negative_qty.any():
        warnings_list.append(
            f"{negative_qty.sum()} baris memiliki nilai negatif pada qty_sold dan diabaikan."
        )
        df = df.loc[~negative_qty].copy()

    if df.empty:
        raise ValueError(
            "Tidak ada data penjualan yang valid setelah pembersihan. Mohon periksa file CSV Anda."
        )

    dropped = initial_rows - len(df)
    if dropped and not warnings_list:
        warnings_list.append(f"{dropped} baris dibersihkan dari data asli.")

    df["qty_sold"] = df["qty_sold"].astype(int)
    df["product"] = df["product"].astype(str).str.strip()
    return df[["date", "product", "qty_sold"]].reset_index(drop=True), warnings_list


def _confidence_from_history(days_of_history: int) -> float:
    """Return a 0-1 history-confidence score.

    - >= 28 days -> 1.0
    - >= 14 days -> 0.8
    - >= 7 days  -> 0.5
    - >= 3 days  -> 0.3
    - < 3 days   -> 0.1 (cold start)
    """
    if days_of_history >= 28:
        return 1.0
    if days_of_history >= 14:
        return 0.8
    if days_of_history >= 7:
        return 0.5
    if days_of_history >= 3:
        return 0.3
    return 0.1


def _confidence_from_variability(values: np.ndarray) -> float:
    """Return a 0-1 variability-confidence score from recent daily sales.

    Uses coefficient of variation (CV = std / mean). Higher variance -> lower confidence.
    - CV <= 0.25 -> 1.0
    - CV <= 0.50 -> 0.7
    - CV <= 1.00 -> 0.4
    - CV >  1.00 -> 0.2
    - All zeros or mean <= 0 -> 0.3
    """
    mean = np.mean(values)
    if mean <= 0:
        # No sales recently; we have little signal but not necessarily invalid.
        return 0.3
    std = np.std(values, ddof=0)
    cv = std / mean
    if cv <= 0.25:
        return 1.0
    if cv <= 0.50:
        return 0.7
    if cv <= 1.00:
        return 0.4
    return 0.2


def _combine_confidence(history_conf: float, variability_conf: float) -> float:
    """Combine history and variability confidence into a single 0-1 score.

    Formula: weighted average 60% history, 40% variability, then rounded to 3 decimals.
    """
    return round(0.6 * history_conf + 0.4 * variability_conf, 3)


def _confidence_label(score: float) -> str:
    """Label confidence score."""
    if score >= 0.7:
        return "High"
    if score >= 0.4:
        return "Medium"
    return "Low"


def forecast_demand(
    sales_df: pd.DataFrame,
    horizon: int = 7,
    window: int = 7,
) -> pd.DataFrame:
    """Forecast demand for each product using a simple moving average.

    Parameters
    ----------
    sales_df : pd.DataFrame
        Cleaned sales DataFrame from ``validate_sales``.
    horizon : int, optional
        Number of future days to forecast. Default is 7.
    window : int, optional
        Days of history used for the moving average. Default is 7.

    Returns
    -------
    pd.DataFrame
        Forecast DataFrame with columns: product, date, forecast_qty, confidence, label.
    """
    if horizon <= 0 or window <= 0:
        raise ValueError("horizon dan window harus lebih besar dari 0.")

    sales_df = sales_df.copy()
    sales_df["date"] = pd.to_datetime(sales_df["date"])

    # Daily totals per product, filling missing days with 0.
    start_date = sales_df["date"].min()
    end_date = sales_df["date"].max()

    results: list[pd.DataFrame] = []

    for product, group in sales_df.groupby("product", sort=True):
        daily = (
            group.groupby("date")["qty_sold"]
            .sum()
            .reindex(pd.date_range(start=start_date, end=end_date, freq="D"), fill_value=0)
        )

        days_of_history = int((daily.index.max() - daily.index.min()).days + 1)
        recent_values = daily.values[-window:] if len(daily) >= window else daily.values
        moving_avg = float(np.mean(recent_values)) if len(recent_values) else 0.0

        history_conf = _confidence_from_history(days_of_history)
        variability_conf = _confidence_from_variability(recent_values)
        confidence = _combine_confidence(history_conf, variability_conf)
        label = _confidence_label(confidence)

        forecast_dates = pd.date_range(
            start=end_date + pd.Timedelta(days=1), periods=horizon, freq="D"
        )
        product_forecast = pd.DataFrame({
            "product": product,
            "date": forecast_dates,
            "forecast_qty": [max(0.0, round(moving_avg, 2))] * horizon,
            "confidence": confidence,
            "label": label,
        })
        results.append(product_forecast)

    if not results:
        return pd.DataFrame(columns=["product", "date", "forecast_qty", "confidence", "label"])

    forecast = pd.concat(results, ignore_index=True)
    forecast["date"] = pd.to_datetime(forecast["date"]).dt.date
    return forecast[["product", "date", "forecast_qty", "confidence", "label"]]
