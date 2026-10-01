"""RAMALOKA Streamlit app.

This module contains only UI and orchestration logic. Business rules live in
``core.forecast`` and ``core.deadstock``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core.forecast import forecast_demand, validate_sales
from core.deadstock import assess_dead_stock, validate_stock

# Constants
DEMO_DIR = Path(__file__).parent / "demo"
SALES_SAMPLE = DEMO_DIR / "sales_sample.csv"
STOCK_SAMPLE = DEMO_DIR / "stock_sample.csv"

RISK_COLORS = {
    "High": "🔴",
    "Medium": "🟡",
    "Low": "🟢",
}


def _risk_badge(risk: str) -> str:
    return f"{RISK_COLORS.get(risk, '⚪')} {risk}"


@st.cache_data(show_spinner=False)
def load_demo_sales() -> pd.DataFrame:
    return pd.read_csv(SALES_SAMPLE)


@st.cache_data(show_spinner=False)
def load_demo_stock() -> pd.DataFrame:
    return pd.read_csv(STOCK_SAMPLE)


def _init_session_state() -> None:
    """Ensure session state keys exist."""
    defaults = {
        "page": "upload",
        "forecast_df": None,
        "warnings_df": None,
        "sales_warnings": [],
        "pipeline_error": None,
        "last_input_signature": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _get_input_signature(sales_file, stock_file, horizon: int):
    """Create a hashable signature to detect when input truly changes."""
    if sales_file is None or stock_file is None:
        return None
    sales_sig = hash(bytes(pd.util.hash_pandas_object(sales_file).values))
    stock_sig = hash(bytes(pd.util.hash_pandas_object(stock_file).values))
    return (sales_sig, stock_sig, horizon)


def run_pipeline(sales_df: pd.DataFrame, stock_df: pd.DataFrame, horizon: int):
    """Run forecast and dead-stock assessment. Return (forecast, warnings, error)."""
    try:
        cleaned_sales, sales_warnings = validate_sales(sales_df)
    except ValueError as exc:
        return None, None, str(exc)

    try:
        cleaned_stock = validate_stock(stock_df)
    except ValueError as exc:
        return None, None, str(exc)

    forecast = forecast_demand(cleaned_sales, horizon=horizon, window=7)
    warnings = assess_dead_stock(cleaned_stock, forecast)

    return forecast, warnings, sales_warnings


def _render_upload_page() -> None:
    """Render the upload page: first screen users see."""
    st.image("resources/logo.png", width=55)
    st.title("RAMALOKA")
    st.caption("Prediksi permintaan & peringatan stok mati untuk bisnis F&B Indonesia")

    st.markdown("### Langkah 1: Unggah Data")
    st.info(
        "Aplikasi membutuhkan dua file CSV: data penjualan harian dan data stok saat ini. "
        "Anda juga boleh menggunakan data contoh untuk mencoba."
    )

    use_demo = st.checkbox("Gunakan data contoh", value=False)

    sales_file = None
    stock_file = None
    if use_demo:
        if SALES_SAMPLE.exists() and STOCK_SAMPLE.exists():
            sales_file = load_demo_sales()
            stock_file = load_demo_stock()
            st.success("Data contoh dimuat.")
        else:
            st.error("File contoh belum tersedia di folder demo/.")

    uploaded_sales = st.file_uploader(
        "Unggah CSV Penjualan", type=["csv"], disabled=use_demo
    )
    uploaded_stock = st.file_uploader(
        "Unggah CSV Stok", type=["csv"], disabled=use_demo 
    )

    if uploaded_sales is not None:
        sales_file = pd.read_csv(uploaded_sales)
    if uploaded_stock is not None:
        stock_file = pd.read_csv(uploaded_stock)

    horizon = st.slider("Jumlah hari prediksi", min_value=3, max_value=30, value=7)

    if st.button("Hitung Prediksi", type="primary", width="stretch"):
        if sales_file is None or stock_file is None:
            st.error("Mohon unggah file penjualan dan stok, atau centang \"Gunakan data contoh\".")
            st.session_state["pipeline_error"] = "missing_input"
            st.session_state["forecast_df"] = None
            st.session_state["warnings_df"] = None
            st.session_state["last_input_signature"] = None
        else:
            st.session_state["pipeline_error"] = None
            current_sig = _get_input_signature(sales_file, stock_file, horizon)
            if current_sig != st.session_state["last_input_signature"]:
                forecast_df, warnings_df, sales_warnings = run_pipeline(
                    sales_file, stock_file, horizon
                )
                st.session_state["forecast_df"] = forecast_df
                st.session_state["warnings_df"] = warnings_df
                st.session_state["sales_warnings"] = sales_warnings or []
                st.session_state["last_input_signature"] = current_sig
            st.session_state["page"] = "results"
            st.rerun()


def _render_results_page() -> None:
    """Render the results page with forecast and dead-stock tables."""
    st.image("resources/logo.png", width=55)
    st.title("RAMALOKA")
    st.caption("Hasil prediksi permintaan & peringatan stok mati")

    if st.button("← Kembali ke Unggah Data", type="secondary"):
        st.session_state["page"] = "upload"
        st.rerun()

    forecast_df = st.session_state["forecast_df"]
    warnings_df = st.session_state["warnings_df"]

    if st.session_state["pipeline_error"] == "missing_input" or forecast_df is None or warnings_df is None:
        st.warning("Belum ada hasil. Silakan kembali dan unggah data terlebih dahulu.")
        return

    # Display any validation warnings once.
    if st.session_state["sales_warnings"]:
        for warning in st.session_state["sales_warnings"]:
            st.warning(warning)

    tab_forecast, tab_deadstock, tab_notes = st.tabs(
        ["Prediksi Permintaan", "Peringatan Stok Mati", "Catatan & Batasan"]
    )

    # Notes tab is static.
    with tab_notes:
        st.subheader("Catatan & Batasan")
        st.info(
            """
            RAMALOKA adalah alat bantu rekomendasi, bukan keputusan akhir.

            - Akurasi prediksi sangat bergantung pada kualitas dan kelengkapan data penjualan Anda.
            - Disarankan memiliki minimal beberapa minggu riwayat penjualan untuk hasil yang lebih baik.
            - Metode yang digunakan adalah rata-rata bergerak sederhana, sehingga belum memperhitungkan
              hari libur, promo mendadak, atau perubahan musim.
            - Selalu lakukan pengecekan manual sebelum membuat keputusan pembelian atau pembuangan stok.
            """
        )

    # Forecast tab
    with tab_forecast:
        st.subheader("Prediksi Permintaan")

        if forecast_df.empty:
            st.warning("Tidak ada produk untuk diprediksi.")
        else:
            confidence_view = (
                forecast_df[["product", "confidence", "label"]]
                .drop_duplicates()
                .sort_values("product")
                .reset_index(drop=True)
            )
            confidence_view["badge"] = confidence_view["label"].apply(
                lambda x: _risk_badge(x)
            )

            # Aggregate forecast to one row per product.
            product_forecast_summary = (
                forecast_df.groupby("product", as_index=False)
                .agg(total_prediksi=("forecast_qty", "sum"))
                .sort_values("product")
                .reset_index(drop=True)
            )

            cols = st.columns([2, 1])
            with cols[0]:
                st.markdown("**Tabel Prediksi**")
                st.dataframe(
                    product_forecast_summary.rename(
                        columns={
                            "product": "Produk",
                            "total_prediksi": "Total Prediksi Terjual",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )
            with cols[1]:
                st.markdown("**Tabel Tingkat Kepercayaan Prediksi Model**")
                st.dataframe(
                    confidence_view[["product", "confidence"]].rename(
                        columns={
                            "product": "Produk",
                            "confidence": "Skor Prediksi (0 - 1)",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )

    # Dead-stock tab
    with tab_deadstock:
        st.subheader("Peringatan Stok Mati")

        if warnings_df.empty:
            st.warning("Tidak ada data stok untuk dievaluasi.")
        else:
            counts = warnings_df["risk"].value_counts().reindex(["High", "Medium", "Low"], fill_value=0)
            metric_cols = st.columns(3)
            metric_cols[0].metric("Risiko Tinggi", int(counts["High"]))
            metric_cols[1].metric("Risiko Sedang", int(counts["Medium"]))
            metric_cols[2].metric("Risiko Rendah", int(counts["Low"]))

            st.divider()

            display_df = warnings_df.copy()
            display_df["Tingkat Risiko"] = display_df["risk"].apply(_risk_badge)
            display_df = display_df.rename(
                columns={
                    "product": "Produk",
                    "stock_qty": "Stok Saat Ini",
                    "expiry_date": "Tanggal Kedaluwarsa",
                    "days_until_expiry": "Hari Hingga Kedaluwarsa",
                    "avg_daily_demand": "Rata-rata Harian",
                    "days_to_sell": "Estimasi Hari Habis",
                    "suggested_action": "Saran Tindakan",
                    "potential_units_wasted": "Estimasi Sia-sia (unit)",
                }
            )

            st.dataframe(
                display_df[
                    [
                        "Tingkat Risiko",
                        "Produk",
                        "Stok Saat Ini",
                        "Tanggal Kedaluwarsa",
                        "Hari Hingga Kedaluwarsa",
                        "Rata-rata Harian",
                        "Estimasi Hari Habis",
                        "Estimasi Sia-sia (unit)",
                        "Saran Tindakan",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )

            st.divider()
            st.markdown("**Grafik Tingkat Risiko per Produk**")
            chart_df = (
                display_df[["Produk", "risk"]]
                .drop_duplicates()
                .sort_values("Produk")
                .reset_index(drop=True)
            )
            risk_score_map = {"Low": 1, "Medium": 2, "High": 3}
            chart_df["Skor Risiko"] = chart_df["risk"].map(risk_score_map)
            st.bar_chart(
                chart_df.set_index("Produk")[["Skor Risiko"]],
                color="#D4A065",
            )

            csv = warnings_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Unduh Tabel Peringatan (CSV)",
                data=csv,
                file_name="ramaloka_warning.csv",
                mime="text/csv",
            )


def main() -> None:
    st.set_page_config(page_title="RAMALOKA", page_icon="resources/logo.png", layout="wide")

    _init_session_state()

    if st.session_state["page"] == "upload":
        _render_upload_page()
    else:
        _render_results_page()


if __name__ == "__main__":
    main()
