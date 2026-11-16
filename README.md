# Shopee BW

Streamlit untuk sheet BW Comm Shopee x WEI: gabung konten Mandatory + Kompetisi, konten Event, dan raw GMV affiliate.
Tiap menu dua langkah: **Cek dulu** (hanya baca) lalu **Terapkan ke Sheet** (menulis, setelah dicentang).

## Menu
- **Mandatory + Kompetisi** (`gabung_konten_bw.py`): form Mandatory/Kompetisi + link di Docs/Sheet peserta -> tab RAW dan Raw Content, satu link per baris, tanpa dobel. Baris sumber yang sudah masuk diwarnai oranye. Username yang belum ada di tab brand ditambahkan.
- **Event** (`gabung_event_bw.py`): SoW gathering/event. Event baru: tambah satu baris di `EVENTS`.
- **GMV Raw Affiliate** (`shopee_raw_to_sheet.py`): upload raw affiliate -> tab Raw, creator baru ke tab brand, tally, performa creator.

## Jalan lokal
`pip install -r requirements.txt`, taruh `credentials.json` (service account) di folder ini, lalu dobel klik `jalankan.bat`.

## Deploy (Streamlit Cloud)
Main file `app.py`. Isi Secrets dari `.streamlit/secrets.toml.example`: `[auth]` (login Google, hanya @warnaemasindonesia.com) dan `[gcp_service_account]` (isi credentials.json). Tambahkan `https://NAMA-APP.streamlit.app/oauth2callback` ke Authorized redirect URIs OAuth client.
Service account harus Editor di Super Sheet, BW Comm, sheet Event; Viewer di sheet event sumber.

## Tes
`python test_gabung_konten_bw.py` dan `python test_app.py` (hanya baca).
