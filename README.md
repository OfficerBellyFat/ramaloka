# RAMALOKA
An AI-powered, CSV-based stock forecasting and deadstock warning system for small businesses in the F&B.

## Tentang Proyek

RAMALOKA adalah aplikasi web sederhana berbasis Streamlit yang membantu pemilik bisnis F&B (kafe, restoran, usaha kuliner kecil) di Indonesia membuat prakiraan permintaan jangka pendek dan mendeteksi stok yang berisiko mati atau kedaluwarsa. Aplikasi ini dibuat sebagai "walking skeleton" untuk keperluan bootcamp universitas.

## Cara Menjalankan

1. Buat virtual environment dan install dependensi:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Jalankan aplikasi Streamlit:
   ```bash
   streamlit run app.py
   ```

3. Buka URL yang muncul di terminal, biasanya `http://localhost:8501`.

## Format File CSV Input

### Penjualan (`sales.csv`)

| Kolom      | Keterangan                    |
|------------|-------------------------------|
| `date`     | Tanggal transaksi (YYYY-MM-DD)|
| `product`  | Nama produk                   |
| `qty_sold` | Jumlah terjual (bilangan bulat)|

### Stok (`stock.csv`)

| Kolom         | Keterangan                         |
|---------------|------------------------------------|
| `product`     | Nama produk                        |
| `stock_qty`   | Jumlah stok saat ini (bilangan bulat)|
| `expiry_date` | Tanggal kedaluwarsa (YYYY-MM-DD)   |

## Cara Kerja

### Prakiraan Permintaan

- Data penjualan diagregasi menjadi total harian per produk. Hari tanpa transaksi diisi dengan nol.
- Prakiraan untuk beberapa hari ke depan dihitung dengan **rata-rata bergerak** dari beberapa hari terakhir.
- Setiap produk mendapat **skor kepercayaan** 0 sampai 1 berdasarkan:
  - Lama riwayat penjualan: semakin panjang data, semakin tinggi kepercayaannya.
  - Variabilitas penjualan harian (koefisien variasi): semakin berfluktuasi, semakin rendah kepercayaannya.
- Label kepercayaan:
  - High: skor >= 0,7
  - Medium: skor 0,4 sampai 0,7
  - Low: skor < 0,4
- Produk dengan kurang dari 3 hari data tetap diprakirakan, tetapi kepercayaannya sangat rendah.

### Peringatan Stok Mati

- Aplikasi membandingkan stok saat ini dan tanggal kedaluwarsa dengan rata-rata permintaan harian dari hasil prakiraan.
- Beberapa metrik yang dihitung:
  - `avg_daily_demand`: rata-rata prakiraan permintaan harian.
  - `days_to_sell`: estimasi hari stok habis (`stok / rata-rata harian`).
  - `days_until_expiry`: sisa hari hingga kedaluwarsa.
- Tingkat risiko:
  - **High**: sudah kedaluwarsa, stok tidak habis sebelum kedaluwarsa, atau tidak ada permintaan namun stok masih ada.
  - **Medium**: stok habis melebihi 70% masa simpan.
  - **Low**: stok cukup aman.
- Produk yang ada di stok tetapi tidak ada di riwayat penjualan akan ditandai **High** dengan catatan "Tidak ada riwayat penjualan".

## Batasan yang Diketahui

- **Cold start**: produk dengan riwayat penjualan singkat memiliki kepercayaan rendah.
- **Kualitas data**: hasil sangat bergantung pada keakuratan dan kelengkapan data yang diunggah pengguna.
- **Tidak ada integrasi supplier**: aplikasi hanya memberikan rekomendasi, tidak terhubung ke sistem pemasok.
- **Rata-rata bergerak sederhana**: belum memperhitungkan hari libur, musim, promo mendadak, atau lonjakan permintaan tak terduga.
- Semua keputusan akhir tetap menjadi tanggung jawab pemilik bisnis.

## Struktur Folder

```
ramaloka/
├── app.py                 # Aplikasi Streamlit (UI dan orkestrasi)
├── requirements.txt       # Daftar dependensi
├── requirements-dev.txt   # Dependensi pengembangan (opsional)
├── README.md              # Dokumentasi proyek
├── core/
│   ├── __init__.py
│   ├── forecast.py        # Logika prakiraan permintaan
│   └── deadstock.py       # Logika peringatan stok mati
├── demo/
│   ├── generate_demo_data.py  # Skrip untuk membuat data contoh
│   ├── sales_sample.csv
│   ├── stock_sample.csv
│   └── output_sample.json
└── tests/
    └── test_core.py       # Unit test dengan pytest
```

## Lisensi

Proyek ini dibuat untuk keperluan edukasi bootcamp.
