"""Unit tests for RAMALOKA core modules."""

from __future__ import annotations

import pandas as pd
import pytest

from core.forecast import forecast_demand, validate_sales
from core.deadstock import assess_dead_stock, validate_stock


# ---------------------------------------------------------------------------
# Forecast validation tests
# ---------------------------------------------------------------------------

def test_validate_sales_missing_columns_raises():
    df = pd.DataFrame({"tanggal": ["2024-01-01"], "produk": ["A"], "jumlah": [5]})
    with pytest.raises(ValueError, match="Kolom wajib tidak ditemukan"):
        validate_sales(df)


def test_validate_sales_drops_invalid_rows():
    df = pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "bad-date", "2024-01-04"],
        "product": ["A", "A", "A", "A"],
        "qty_sold": [10, -2, 5, 8],
    })
    cleaned, warnings = validate_sales(df)
    assert list(cleaned["qty_sold"]) == [10, 8]
    assert len(warnings) > 0


def test_validate_sales_empty_raises():
    df = pd.DataFrame(columns=["date", "product", "qty_sold"])
    with pytest.raises(ValueError, match="kosong"):
        validate_sales(df)


# ---------------------------------------------------------------------------
# Forecast demand tests
# ---------------------------------------------------------------------------

def _make_daily_sales(product: str, dates, values) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "product": product, "qty_sold": values})


def test_forecast_output_shape_and_confidence_range():
    dates = pd.date_range("2024-01-01", periods=30, freq="D").strftime("%Y-%m-%d").tolist()
    values = [10 + i % 5 for i in range(30)]
    sales = _make_daily_sales("A", dates, values)
    cleaned, _ = validate_sales(sales)
    forecast = forecast_demand(cleaned, horizon=7, window=7)

    assert set(forecast.columns) >= {"product", "date", "forecast_qty", "confidence", "label"}
    assert len(forecast) == 7
    assert forecast["product"].unique()[0] == "A"
    assert 0.0 <= forecast["confidence"].iloc[0] <= 1.0


def test_forecast_cold_start_low_confidence():
    # Fewer than 7 days + high variability should push confidence below 0.4.
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    sales = _make_daily_sales("Cold", dates, [1, 10, 2, 12])
    cleaned, _ = validate_sales(sales)
    forecast = forecast_demand(cleaned, horizon=7, window=7)
    assert forecast["label"].iloc[0] == "Low"
    assert forecast["confidence"].iloc[0] < 0.4


def test_forecast_all_zeros():
    dates = pd.date_range("2024-01-01", periods=14, freq="D").strftime("%Y-%m-%d").tolist()
    sales = _make_daily_sales("Zero", dates, [0] * 14)
    cleaned, _ = validate_sales(sales)
    forecast = forecast_demand(cleaned, horizon=7, window=7)
    assert (forecast["forecast_qty"] == 0.0).all()


# ---------------------------------------------------------------------------
# Dead-stock validation tests
# ---------------------------------------------------------------------------

def test_validate_stock_missing_columns_raises():
    df = pd.DataFrame({"produk": ["A"], "jumlah": [10]})
    with pytest.raises(ValueError, match="Kolom wajib tidak ditemukan"):
        validate_stock(df)


def test_validate_stock_cleans_negative_stock():
    df = pd.DataFrame({
        "product": ["A", "B"],
        "stock_qty": [10, -5],
        "expiry_date": ["2024-12-31", "2024-12-31"],
    })
    cleaned = validate_stock(df)
    assert list(cleaned["stock_qty"]) == [10, 0]


# ---------------------------------------------------------------------------
# Dead-stock assessment tests
# ---------------------------------------------------------------------------

def _make_forecast(product: str, horizon: int, avg: float, confidence: float) -> pd.DataFrame:
    dates = pd.date_range("2024-06-01", periods=horizon, freq="D")
    return pd.DataFrame({
        "product": [product] * horizon,
        "date": dates.date,
        "forecast_qty": [avg] * horizon,
        "confidence": confidence,
        "label": "Medium",
    })


def test_deadstock_risk_high_expired():
    forecast = _make_forecast("Expired", 7, 5.0, 0.6)
    stock = pd.DataFrame({
        "product": ["Expired"],
        "stock_qty": [10],
        "expiry_date": ["2024-05-01"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert result.iloc[0]["risk"] == "High"


def test_deadstock_risk_high_wont_sell_in_time():
    forecast = _make_forecast("Slow", 7, 1.0, 0.6)
    stock = pd.DataFrame({
        "product": ["Slow"],
        "stock_qty": [20],
        "expiry_date": ["2024-06-10"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert result.iloc[0]["risk"] == "High"


def test_deadstock_risk_medium():
    forecast = _make_forecast("Medium", 7, 2.0, 0.6)
    stock = pd.DataFrame({
        "product": ["Medium"],
        "stock_qty": [14],
        "expiry_date": ["2024-06-10"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert result.iloc[0]["risk"] == "Medium"


def test_deadstock_risk_low():
    forecast = _make_forecast("Safe", 7, 5.0, 0.8)
    stock = pd.DataFrame({
        "product": ["Safe"],
        "stock_qty": [10],
        "expiry_date": ["2024-06-20"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert result.iloc[0]["risk"] == "Low"


def test_deadstock_zero_demand_high():
    forecast = _make_forecast("NoDemand", 7, 0.0, 0.6)
    stock = pd.DataFrame({
        "product": ["NoDemand"],
        "stock_qty": [10],
        "expiry_date": ["2024-06-20"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert result.iloc[0]["risk"] == "High"


def test_deadstock_no_sales_history_flagged_high():
    forecast = _make_forecast("Known", 7, 2.0, 0.6)
    stock = pd.DataFrame({
        "product": ["Unknown"],
        "stock_qty": [10],
        "expiry_date": ["2024-06-20"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert result.iloc[0]["risk"] == "High"
    assert "Tidak ada riwayat penjualan" in result.iloc[0]["suggested_action"]


def test_deadstock_sorted_high_first():
    forecast = pd.concat([
        _make_forecast("LowRisk", 7, 10.0, 0.8),
        _make_forecast("HighRisk", 7, 0.0, 0.6),
    ], ignore_index=True)
    stock = pd.DataFrame({
        "product": ["LowRisk", "HighRisk"],
        "stock_qty": [5, 10],
        "expiry_date": ["2024-06-20", "2024-06-20"],
    })
    today = pd.Timestamp("2024-06-01")
    result = assess_dead_stock(validate_stock(stock), forecast, today=today)
    assert list(result["risk"]) == ["High", "Low"]
