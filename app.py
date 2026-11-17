"""Shopee BW: gabung konten Mandatory + Kompetisi, konten Event, dan raw GMV affiliate ke sheet BW Comm.

Tiga menu, satu login. Tiap menu dua langkah: "Cek dulu" (hanya baca, tidak menulis) lalu "Terapkan ke Sheet".
Cuma akun @warnaemasindonesia.com yang bisa masuk (login Google dari secrets [auth]). Akses sheet lewat credentials.json
kalau ada, selain itu [gcp_service_account] di Secrets. Service account harus Editor di semua sheet yang ditulis.

Lokal tanpa login:  dobel klik jalankan.bat
"""
import base64
import contextlib
import functools
import io
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from google.oauth2 import service_account

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent):  # modul inti: di folder ini (zip) atau di folder induk (pengembangan)
    if str(p) not in sys.path:
        sys.path.append(str(p))
import gabung_event_bw as ev  # noqa: E402
import gabung_konten_bw as kt  # noqa: E402
import shopee_raw_to_sheet as gmv  # noqa: E402

DOMAIN = 'warnaemasindonesia.com'
LOCAL_MODE = os.environ.get('SHOPEE_BW_LOKAL') == '1'  # hanya diset jalankan.bat; di server tidak ada, login tetap wajib
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.readonly']
MENU = {'konten': 'Mandatory + Kompetisi', 'event': 'Event', 'gmv': 'GMV Raw Affiliate'}

CSS = """<style>
:root{--bg:#f4f4f5;--panel:#fff;--muted:#6b6b6b;--line:#e4e4e7;--gold:#ffd700;
  --shadow:0 1px 2px rgba(16,16,16,.05),0 8px 24px rgba(16,16,16,.06)}
html,body,[data-testid="stApp"]{font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;font-variant-numeric:tabular-nums}
[data-testid="stApp"],[data-testid="stAppViewContainer"]{background:var(--bg)}
[data-testid="stHeader"]{background:transparent}
[data-testid="stToolbarActions"],[data-testid="stMainMenu"],[data-testid="stAppDeployButton"],[data-testid="stDecoration"],#MainMenu,footer{display:none}
.block-container{max-width:1280px;padding:28px 32px 64px}
section[data-testid="stSidebar"]{background:#000;width:250px !important;min-width:250px !important;border-right:1px solid rgba(255,255,255,.18)}
section[data-testid="stSidebar"] *{color:#fff}
section[data-testid="stSidebar"] .side-brand{color:#c6cbc7;font-size:13px;margin:10px 0 12px}
section[data-testid="stSidebar"] .side-label{color:#c6cbc7;font-size:12px;letter-spacing:.08em;text-transform:uppercase;margin:20px 0 6px}
section[data-testid="stSidebar"] .stButton button{background:transparent;border:1px solid rgba(255,255,255,.18);border-radius:6px;
  justify-content:flex-start;padding:10px 12px;min-height:44px;font-size:13px}
section[data-testid="stSidebar"] .stButton button:hover{background:rgba(255,255,255,.12)}
section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]{background:#fff;border-color:#fff}
section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] *{color:#000}
h1.ptitle{font-size:32px;line-height:1.1;margin:0 0 6px;letter-spacing:-.01em;padding:0}
.psub{margin:0 0 24px;color:var(--muted);font-size:16px}
.stMain [data-testid="stBaseButton-primary"]{background:var(--gold);color:#000;border:0;border-radius:6px;font-weight:700;min-height:44px}
.stMain [data-testid="stBaseButton-primary"] *{color:#000}
.stMain [data-testid="stBaseButton-primary"]:hover{filter:brightness(.95);background:var(--gold);color:#000}
.stMain [data-testid="stBaseButton-primary"]:disabled{opacity:.5}
[data-testid="stMetric"]{background:var(--panel);border-radius:10px;padding:16px 18px;box-shadow:var(--shadow)}
[data-testid="stMetricLabel"] *{color:var(--muted)}
[data-testid="stFileUploader"] section{background:#fff;border:1px dashed #000;border-radius:8px}
[data-testid="stDataFrame"],[data-testid="stDataEditor"]{border:1px solid var(--line);border-radius:8px}
.user{display:flex;gap:10px;align-items:center;min-width:0;padding-top:16px;border-top:1px solid rgba(255,255,255,.18);margin-top:24px}
.avatar{width:32px;height:32px;border-radius:50%;background:#fff;color:#000 !important;display:grid;place-items:center;font-weight:700;flex:none;overflow:hidden}
.avatar img{width:100%;height:100%;object-fit:cover}
.uname{font-weight:700;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.umail{color:#c6cbc7 !important;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.banner.bad{display:flex;border:1px solid #d03b3b;background:#fbe9e9;border-radius:8px;padding:12px 14px;margin:12px 0}
.st-key-login{background:var(--panel);border:1px solid #000;overflow:hidden;gap:0 !important}
.login-head{background:#000;padding:28px 24px}
.login-head img{height:56px;display:block}
.login-body{padding:24px 24px 8px}
.login-body h1{margin:0 0 6px;font-size:22px;padding:0}
.login-body p{margin:0 0 12px;color:#3d3d3d}
.st-key-login [data-testid="stElementContainer"]:has(.stButton){padding:0 24px 24px}
.st-key-login .stButton button{background:#000;color:#fff;border:0;border-radius:6px;min-height:44px;font-weight:700}
.st-key-login .stButton button *{color:#fff}
@media (max-width:720px){.block-container{padding:20px 16px 40px}h1.ptitle{font-size:25px}}
</style>"""


# ------------------------------------------------------------------ akses
def sa_credentials():
    key = next((p for p in (HERE / 'credentials.json', HERE.parent / 'credentials.json') if p.exists()), None)
    return (service_account.Credentials.from_service_account_file(str(key), scopes=SCOPES) if key else
            service_account.Credentials.from_service_account_info(dict(st.secrets['gcp_service_account']), scopes=SCOPES))


def allowed(email, verified, extra=()):
    """Email Google terverifikasi dengan domain persis domain perusahaan, atau ada di allowed_emails."""
    if not (verified and isinstance(email, str)):
        return False
    email = email.lower()
    return email.rsplit('@', 1)[-1] == DOMAIN or email in {str(e).strip().lower() for e in extra}


@functools.cache
def logo_uri():
    return 'data:image/png;base64,' + base64.b64encode((HERE / 'logo-wei.png').read_bytes()).decode()


def login_page(message=None, can_logout=False):
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div style="height:12vh"></div>', unsafe_allow_html=True)
        with st.container(key='login'):
            st.markdown(f'<div class="login-head"><img src="{logo_uri()}" alt="WEI"></div>'
                        f'<div class="login-body"><h1>Masuk</h1><p>Gunakan akun Google @{DOMAIN}.</p>'
                        + (f'<div class="banner bad">{message}</div>' if message else '') + '</div>', unsafe_allow_html=True)
            if can_logout:
                st.button('Keluar dan coba akun lain', on_click=st.logout, width='stretch')
            else:
                st.button('Masuk dengan Google', on_click=st.login, width='stretch')


def sidebar(email):
    with st.sidebar:
        st.markdown(f'<img src="{logo_uri()}" alt="WEI" style="height:32px"><div class="side-brand">Shopee BW</div>'
                    '<div class="side-label">Menu</div>', unsafe_allow_html=True)
        for page, text in MENU.items():
            if st.button(text, key=f'nav_{page}', width='stretch', type='primary' if st.session_state.page == page else 'secondary'):
                st.session_state.page = page
                st.rerun()
        if email:
            label = st.user.get('name') or email.split('@')[0]
            pic = st.user.get('picture')
            avatar = f'<img src="{pic}" alt="" referrerpolicy="no-referrer">' if pic else (label[:1] or '?').upper()
            st.markdown(f'<div class="user"><div class="avatar">{avatar}</div><div style="min-width:0">'
                        f'<div class="uname">{label}</div><div class="umail">{email}</div></div></div>', unsafe_allow_html=True)
            st.button('Keluar', key='logout', on_click=st.logout, width='stretch')
    return st.session_state.page


def header(title, sub):
    st.markdown(f'<h1 class="ptitle">{title}</h1><p class="psub">{sub}</p>', unsafe_allow_html=True)


def n(x):
    return f'{x:,}'.replace(',', '.')


# ------------------------------------------------------------------ helper jalan
def capture(fn, *args, **kw):
    """Jalankan fn, tangkap print-nya sebagai log. SystemExit (pesan ERROR dari skrip) jadi RuntimeError."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            res = fn(*args, **kw)
        except SystemExit as e:
            raise RuntimeError(str(e.code)) from None
    return res, buf.getvalue()


def google():
    """(sheets, drive, email) untuk skrip gabung, pakai credentials yang sama dengan alat GMV."""
    return kt.services(True, creds=sa_credentials())


def user_table(user_plan):
    return pd.DataFrame([{'Tab brand': tab, 'Baris': first + i, 'Username': u}
                         for tab, first, users, _ in user_plan for i, u in enumerate(users)])


def rows_table(rows):
    return pd.DataFrame([r[:9] for r in rows], columns=kt.HEADER)


def show_log(text, title='Log'):
    with st.expander(title):
        st.code(text or '(kosong)', language=None)


def apply_box(key, ready, label='Terapkan ke Sheet'):
    """Konfirmasi + tombol tulis. True hanya kalau dicentang dan tombol diklik."""
    ok = st.checkbox('Saya sudah cek ringkasan di atas dan siap menulis ke Google Sheets', key=f'ok_{key}')
    return st.button(label, key=f'apply_{key}', type='primary', disabled=not (ready and ok))


# ------------------------------------------------------------------ menu 1: Mandatory + Kompetisi
BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
SEMUA, HANYA = 'Semua baris', 'Hanya baris bulan ini'
BRANDS = list(kt.BRANDS.values())


@st.cache_data(ttl=300, show_spinner=False)
def super_sheet_tabs():
    sheets, _, _ = google()
    meta = sheets.get(spreadsheetId=kt.SHEET_ID, fields='sheets.properties.title').execute(num_retries=3)
    return [s['properties']['title'] for s in meta['sheets']]


def tab_month(title):
    return kt.month_no(title.split()[-1]) if title.split() else None


def tab_table(titles, bm):
    """Tab sumber di Super Sheet + usulan: tab bulan ini semua barisnya, tab bulan lalu hanya baris bertanggal bulan ini."""
    prev = (bm - 2) % 12 + 1
    rows = []
    for t in titles:
        low = t.lower()
        if 'penerima' in low or low.startswith('gabungan') or not (low.startswith(('raw', 'form')) or 'competition' in low):
            continue
        m = tab_month(t)
        tujuan_lama = low.startswith('raw ') and len(t.split()) == 2 and m != bm  # mis. "RAW OCT" = tujuan bulan lalu
        rank = 0 if m == bm else 1 if m == prev else 2
        rows.append((rank, {'Pakai': rank < 2 and not tujuan_lama, 'Tab': t, 'Bulan tab': BULAN[m - 1] if m else '?',
                            'Baris yang diambil': HANYA if m == prev else SEMUA}))
    return [r for _, r in sorted(rows, key=lambda x: (x[0], x[1]['Tab']))]


def page_konten():
    header('Mandatory + Kompetisi', 'Gabung form Mandatory dan Kompetisi (termasuk link di Docs/Sheet peserta) jadi satu link per baris.')
    try:
        titles = super_sheet_tabs()
    except Exception as e:  # noqa: BLE001
        st.error(f'Super Sheet tidak bisa dibaca: {e}')
        return
    st.markdown('**1. Pilih bulan**')
    bulan = st.selectbox('Bulan yang diproses', BULAN, index=date.today().month - 1, label_visibility='collapsed')
    bm = BULAN.index(bulan) + 1
    st.markdown('**2. Centang tab yang mau dibaca**')
    st.caption('Tab bulan ini dibaca semua barisnya. Tab bulan lalu hanya barisnya yang bertanggal bulan ini (form lama masih terisi). '
               'Tab lain, misalnya form Paid, bisa dicentang sendiri.')
    table = st.data_editor(pd.DataFrame(tab_table(titles, bm)), hide_index=True, key=f'tabs_{bm}', width='stretch',
                           disabled=['Tab', 'Bulan tab'],
                           column_config={'Pakai': st.column_config.CheckboxColumn(width='small'),
                                          'Baris yang diambil': st.column_config.SelectboxColumn(options=[SEMUA, HANYA])})
    pilih = table[table['Pakai']]
    pairs = [(r['Tab'], bm if r['Baris yang diambil'] == HANYA else None) for _, r in pilih.iterrows()]
    lama = [r['Tab'] for _, r in pilih.iterrows() if tab_month(r['Tab']) != bm and r['Baris yang diambil'] == SEMUA]
    if lama:
        st.warning('Diambil semua barisnya walau bukan tab bulan ini: ' + ', '.join(lama) +
                   '. Tanggal aslinya tetap, jadi minggu (W1-W4) di tab brand ikut tanggal itu.')
    with st.expander('Lanjutan: tab tujuan'):
        c1, c2 = st.columns(2)
        target0 = next((t for t in titles if t.lower().startswith('raw ') and len(t.split()) == 2 and tab_month(t) == bm), '')
        target = c1.text_input('Tab tujuan di Super Sheet', target0, key=f'target_{bm}')
        raw_tab = c2.text_input('Tab Raw Content di BW Comm', kt.RAW_TAB, key=f'rawtab_{bm}')
    argv = ['--bulan', bulan, '--target', target.strip(), '--raw-tab', raw_tab.strip(), '--ke-raw-content']
    sig = (tuple(pairs), tuple(argv))

    st.markdown('**3. Cek dulu**')
    if st.button('Cek dulu (tidak menulis)', key='cek_konten', type='primary', disabled=not (pairs and target.strip())):
        try:
            with st.spinner('Membaca form dan membuka Docs/Sheet peserta (bisa beberapa menit)...'):
                sheets, drive, email = google()
                a = kt.buat_parser().parse_args(argv)
                a.tabs_pilih = pairs
                plan, log = capture(kt.siapkan, a, sheets, drive, email)
            st.session_state.konten = (sig, plan, log)
        except Exception as e:  # noqa: BLE001
            st.session_state.pop('konten', None)
            st.error(f'Gagal: {e}')
    res = st.session_state.get('konten')
    if not res or res[0] != sig:
        return
    _, p, log = res
    users = sum(len(u) for _, _, u, _ in p.user_plan)
    warna = sum(map(len, p.per_tab.values()))
    st.markdown(f'**Kalau diterapkan:** {n(len(p.g_out))} baris baru masuk ke **{p.target}**, {n(len(p.r_out))} ke **{p.a.raw_tab}**, '
                f'{n(users)} username baru ditambah ke tab brand, dan kolom Username Shopee di {n(warna)} baris tab sumber diwarnai oranye (tanda sudah masuk).')
    baru = Counter(r[7] for r in p.g_out)
    st.dataframe(pd.DataFrame([{'Tab': t, 'Baris yang diambil': HANYA if m else SEMUA, 'Respons dibaca': kept,
                                'Link ditemukan': links, 'Baru masuk': baru.get(t, 0)} for t, m, total, kept, links in p.info]),
                 hide_index=True, width='stretch')
    if p.g_out:
        with st.expander(f'Lihat {n(len(p.g_out))} baris baru'):
            st.dataframe(rows_table(p.g_out[:2000]), hide_index=True)
            st.download_button('Unduh semua (CSV)', rows_table(p.g_out).to_csv(index=False).encode('utf-8-sig'),
                               'pratinjau_konten.csv', 'text/csv')
    else:
        st.info('Tidak ada baris baru.')
    if p.user_plan:
        st.subheader('Username yang belum ada di tab brand (akan ditambahkan)')
        st.dataframe(user_table(p.user_plan), hide_index=True)
    show_log(log, 'Detail proses')
    st.markdown('**4. Terapkan**')
    if apply_box('konten', bool(p.g_out or p.r_out or p.per_tab or p.user_plan)):
        try:
            with st.spinner('Menulis ke Google Sheets...'):
                sheets, _, _ = google()
                _, out = capture(kt.terapkan, p, sheets)
            st.success('Selesai ditulis.')
            show_log(out, 'Log penulisan')
            st.session_state.pop('konten', None)
        except Exception as e:  # noqa: BLE001
            st.error(f'Gagal menulis: {e}')


# ------------------------------------------------------------------ menu 2: Event
def event_daftar():
    """Daftar sumber event: dibaca sekali dari tab "Daftar Event" di sheet Event, kalau belum ada dipakai daftar bawaan."""
    if 'event_daftar' not in st.session_state:
        try:
            sheets, _, _ = google()
            got = ev.baca_daftar(sheets)
        except Exception:  # noqa: BLE001
            got = None
        st.session_state.event_daftar = got if got is not None else ev.seed_daftar()
        st.session_state.event_tersimpan = got is not None
    return st.session_state.event_daftar


def clean_daftar(df):
    rows = []
    for r in df.to_dict('records'):
        sid = ev.sheet_id_dari(str(r.get('Sheet ID') or ''))
        if not (sid and str(r.get('Tab') or '') != ''):
            continue
        hr = r.get('Baris header')
        rows.append({'Aktif': bool(r.get('Aktif')), 'Nama': str(r.get('Nama') or ''), 'Sheet ID': sid, 'Tab': str(r['Tab']),
                     'Kolom link': str(r.get('Kolom link') or '').strip().upper(),
                     'Kolom username': str(r.get('Kolom username') or '').strip().upper(),
                     'Brand': str(r.get('Brand') or ''), 'Baris header': int(hr) if pd.notna(hr) and str(hr).strip() else 1})
    return rows


@st.cache_data(ttl=120, show_spinner=False)
def event_preview(sid, tab):
    sheets, _, _ = google()
    vals = sheets.values().get(spreadsheetId=sid, range=f"'{tab}'!A1:AZ15").execute(num_retries=3).get('values', [])
    w = max((len(r) for r in vals), default=1)
    return [r + [''] * (w - len(r)) for r in vals] or [['']]


def event_tambah():
    """Form: pilih sheet (link) -> tab -> lihat isinya -> pilih kolom link / username / brand -> tambah ke daftar."""
    url = st.text_input('Link Google Sheet event', key='ev_url', placeholder='https://docs.google.com/spreadsheets/d/...')
    if st.button('Baca sheet', key='ev_baca', disabled=not url.strip()):
        sid = ev.sheet_id_dari(url)
        try:
            sheets, _, email = google()
            meta = sheets.get(spreadsheetId=sid, fields='properties.title,sheets.properties.title').execute(num_retries=3)
            st.session_state.ev_new = {'sid': sid, 'judul': meta['properties']['title'],
                                       'tabs': [s['properties']['title'] for s in meta['sheets']]}
        except Exception as e:  # noqa: BLE001
            st.session_state.pop('ev_new', None)
            st.error(f'Sheet tidak bisa dibaca. Share sheet itu ke akun service account sebagai Viewer. ({e})')
    new = st.session_state.get('ev_new')
    if not new:
        return
    st.success(f"Sheet: {new['judul']}")
    tab = st.selectbox('Tab', new['tabs'], key=f"ev_tab_{new['sid']}")
    hrow = st.number_input('Judul kolom ada di baris ke', 1, 15, 1, key=f"ev_hrow_{new['sid']}_{tab}")
    grid = event_preview(new['sid'], tab)
    cols = [ev.letters(i) for i in range(len(grid[0]))]
    st.dataframe(pd.DataFrame(grid, columns=cols, index=range(1, len(grid) + 1)), height=280, width='stretch')
    head = grid[min(int(hrow), len(grid)) - 1]
    link_idx = [i for i, h in enumerate(head) if 'link' in h.lower()]
    user_idx = next((i for i, h in enumerate(head) if 'username' in h.lower() and 'shopee' in h.lower()),
                    next((i for i, h in enumerate(head) if 'username' in h.lower()), 0))
    label = lambda i: f'{cols[i]} · {head[i][:38]}'  # noqa: E731
    k = f"{new['sid']}_{tab}_{hrow}"
    c1, c2, c3 = st.columns(3)
    dari = c1.selectbox('Kolom link: dari', range(len(cols)), index=link_idx[0] if link_idx else 0, format_func=label, key=f'ev_dari_{k}')
    sampai = c2.selectbox('sampai', range(len(cols)), index=link_idx[-1] if link_idx else 0, format_func=label, key=f'ev_sampai_{k}')
    user = c3.selectbox('Kolom username', range(len(cols)), index=user_idx, format_func=label, key=f'ev_user_{k}')
    c4, c5 = st.columns(2)
    brand = c4.selectbox('Brand', BRANDS, key=f'ev_brand_{k}')
    nama = c5.text_input('Nama (bebas)', f"{new['judul']} / {tab.strip()}", key=f'ev_nama_{k}')
    if dari > sampai:
        st.error('Kolom link "dari" harus sebelum "sampai".')
    elif st.button('Tambah ke daftar', key='ev_tambah', type='primary'):
        row = {'Aktif': True, 'Nama': nama, 'Sheet ID': new['sid'], 'Tab': tab, 'Kolom link': f'{cols[dari]}:{cols[sampai]}',
               'Kolom username': cols[user], 'Brand': brand, 'Baris header': int(hrow)}
        st.session_state.event_daftar = clean_daftar(pd.DataFrame(st.session_state.get('event_now', []))) + [row]
        st.session_state.pop('ev_editor', None)
        st.session_state.pop('ev_new', None)
        st.rerun()


def page_event():
    header('Event', 'Pilih sheet event dan kolom linknya, lalu gabung SoW event ke sheet Event dan Raw Content.')
    st.markdown('**1. Daftar event**')
    st.caption('Centang yang mau diproses. Baris bisa diubah langsung (kolom link: G:L, username: E) atau dihapus. '
               'Sheet baru ditambah di bawah.')
    editor = st.data_editor(pd.DataFrame(event_daftar(), columns=ev.DAFTAR_KOLOM), hide_index=True, num_rows='dynamic',
                            key='ev_editor', width='stretch',
                            column_config={'Aktif': st.column_config.CheckboxColumn(width='small'),
                                           'Brand': st.column_config.SelectboxColumn(options=BRANDS),
                                           'Sheet ID': st.column_config.TextColumn(width='small'),
                                           'Baris header': st.column_config.NumberColumn(min_value=1, step=1, format='%d')})
    rows = clean_daftar(editor)
    st.session_state.event_now = rows
    c1, c2 = st.columns([1, 3])
    if c1.button('Simpan daftar', key='ev_simpan', help='Disimpan di tab "Daftar Event" pada sheet Event, supaya daftar ini ada lagi nanti.'):
        try:
            sheets, _, _ = google()
            ev.simpan_daftar(sheets, rows)
            st.session_state.event_tersimpan = True
            c2.success('Daftar tersimpan.')
        except Exception as e:  # noqa: BLE001
            c2.error(f'Gagal menyimpan: {e}')
    with st.expander('Tambah sheet / tab event baru'):
        event_tambah()

    st.markdown('**2. Cek dulu**')
    events = ev.events_dari(rows)
    if st.button('Cek dulu (tidak menulis)', key='cek_event', type='primary', disabled=not events):
        try:
            with st.spinner('Membaca sheet event dan membuka Docs/Sheet peserta...'):
                sheets, drive, email = google()
                res, log = capture(ev.siapkan, sheets, drive, email, events)
            st.session_state.event = (events, res, log)
        except Exception as e:  # noqa: BLE001
            st.session_state.pop('event', None)
            st.error(f'Gagal: {e}')
    got = st.session_state.get('event')
    if not got or got[0] != events:
        return
    _, (rows_ev, plans, user_plan), log = got
    for line in log.splitlines():
        if 'GAGAL' in line:
            st.warning(line.strip())
    new_rows = next((out for _, _, _, _, out in plans if out), [])
    users = sum(len(u) for _, _, u, _ in user_plan)
    st.markdown(f'**Kalau diterapkan:** {n(len(new_rows))} baris baru masuk ke sheet Event dan Raw Content, '
                f'{n(users)} username baru ditambah ke tab brand.')
    baru = Counter(r[7] for r in new_rows)
    st.dataframe(pd.DataFrame([{'Sumber': s, 'Link terbaca': v, 'Baru masuk': baru.get(s, 0)}
                               for s, v in sorted(Counter(r[7] for r in rows_ev).items())]), hide_index=True, width='stretch')
    if new_rows:
        with st.expander(f'Lihat {n(len(new_rows))} baris baru'):
            st.dataframe(rows_table(new_rows[:2000]), hide_index=True)
    else:
        st.info('Tidak ada baris baru.')
    if user_plan:
        st.subheader('Username yang belum ada di tab brand (akan ditambahkan)')
        st.dataframe(user_table(user_plan), hide_index=True)
    show_log(log, 'Detail proses')
    st.markdown('**3. Terapkan**')
    if apply_box('event', bool(new_rows or user_plan)):
        try:
            with st.spinner('Menulis ke Google Sheets...'):
                sheets, _, _ = google()
                _, out = capture(ev.terapkan, plans, user_plan, sheets)
            st.success('Selesai ditulis.')
            show_log(out, 'Log penulisan')
            st.session_state.pop('event', None)
        except Exception as e:  # noqa: BLE001
            st.error(f'Gagal menulis: {e}')


# ------------------------------------------------------------------ menu 3: GMV raw affiliate
def read_raw(up):
    return pd.read_excel(up) if up.name.lower().endswith(('.xlsx', '.xls')) else pd.read_csv(up, encoding='utf-8-sig', low_memory=False)


def gmv_sheet():
    return gmv.connect_creds(sa_credentials())


def page_gmv():
    header('GMV Raw Affiliate', 'Upload raw affiliate Shopee: masuk ke tab Raw, creator baru ditambah ke tab brand, lalu dicek tally GMV.')
    tab_up, tab_tally, tab_perf = st.tabs(['Upload raw', 'Cek tally', 'Performa creator'])
    with tab_up:
        up = st.file_uploader('File raw (.csv / .xlsx)', type=['csv', 'xlsx', 'xls'], key='gmv_file')
        if up:
            upload_raw(up)
    with tab_tally:
        st.caption('Membandingkan GMV tab Raw (Cek name valid) dengan Total GMV di tab brand. Menulis hasilnya ke tab "Cek Tally" dan memperbaiki yang bisa (menambah creator / menyalin rumus).')
        raw_tab = st.text_input('Tab Raw', gmv.RAW_TAB, key='tally_raw')
        fix = st.checkbox('Perbaiki otomatis kalau tidak tally', value=True)
        if st.button('Cek tally', key='run_tally', type='primary'):
            try:
                with st.spinner('Menghitung tally...'):
                    sh = gmv_sheet()
                    wei = {gmv.norm_user(u) for u in gmv.read_user_col(sh.worksheet(gmv.WEI_TAB), 1, 2)}
                    ok, out = capture(gmv.tally, sh, raw_tab, wei, fix=fix)
                (st.success if ok else st.warning)('Tally cocok.' if ok else 'Belum tally. Lihat log.')
                show_log(out, 'Hasil tally')
            except Exception as e:  # noqa: BLE001
                st.error(f'Gagal: {e}')
    with tab_perf:
        st.caption('Laporan performa creator (Cek name bukan #N/A). Hasilnya ditulis ke tab baru "Performa <tanggal>".')
        raw_tab = st.text_input('Tab Raw', gmv.RAW_TAB, key='perf_raw')
        spec = st.text_input('Tanggal: 10 | 9-15 | 2026-11-09:2026-11-15 | all', 'all')
        top = st.number_input('Top creator yang ditampilkan', 1, 100, 10)
        if st.button('Buat laporan performa', key='run_perf', type='primary'):
            try:
                with st.spinner('Menghitung performa...'):
                    _, out = capture(gmv.performa, gmv_sheet(), raw_tab, spec.strip() or 'all', top=int(top))
                st.success('Selesai.')
                show_log(out, 'Hasil performa')
            except Exception as e:  # noqa: BLE001
                st.error(f'Gagal: {e}')


def upload_raw(up):
    df = read_raw(up)
    st.caption(f'{n(len(df))} baris')
    c1, c2 = st.columns(2)
    stat_opts, ver_opts = list(df['Order Status'].value_counts().index), list(df['Verified Status'].value_counts().index)
    statuses = c1.multiselect('Order Status yang dimasukkan', stat_opts,
                              default=[s for s in stat_opts if s in ('Completed', 'Pending')] or stat_opts)
    verified = c2.multiselect('Verified Status yang dimasukkan', ver_opts, default=[s for s in ver_opts if s == 'Valid'] or ver_opts)
    c3, c4 = st.columns(2)
    weeks_txt = c3.text_input('Range tanggal per week (tanggal mulai-sampai, pisah koma)', '1-8,9-15,16-22,23-30')
    raw_tab = c4.text_input('Tab Raw tujuan', gmv.RAW_TAB)
    unknown = st.checkbox(f"Ikutkan baris brand '{gmv.UNKNOWN_BRAND}'")
    sig = (up.file_id, tuple(statuses), tuple(verified), weeks_txt, raw_tab, unknown)
    try:
        weeks = gmv.parse_weeks(weeks_txt)
    except ValueError as e:
        st.error(str(e))
        return
    if st.button('Cek dulu (tidak menulis)', key='cek_gmv', type='primary', disabled=not (statuses and verified)):
        try:
            with st.spinner('Membaca sheet BW Comm...'):
                p, log = capture(gmv.siapkan, gmv_sheet(), df, statuses, verified, weeks, unknown)
            st.session_state.gmv = (sig, p, log)
        except Exception as e:  # noqa: BLE001
            st.session_state.pop('gmv', None)
            st.error(f'Gagal: {e}')
    got = st.session_state.get('gmv')
    if not got or got[0] != sig:
        return
    _, p, log = got
    d = p['d']
    m = st.columns(4)
    m[0].metric('Baris masuk Raw', n(len(d)))
    m[1].metric('GMV', n(int(d['Purchase Value(Rp)'].sum())))
    m[2].metric('Creator baru ke tab brand', n(sum(len(v) for v in p['plan'].values())))
    m[3].metric('Username belum di WEI (tidak ditambah)', n(p['unknown_users']))
    if p['out_of_range']:
        st.warning(f"{n(p['out_of_range'])} baris tanggalnya di luar range week manapun (WEEK = OUT OF RANGE).")
    st.dataframe(d['BRANDS'].value_counts().rename_axis('Brand').reset_index(name='Baris'), hide_index=True)
    if any(len(v) for v in p['plan'].values()):
        st.subheader('Creator baru yang akan ditambahkan ke tab brand')
        st.dataframe(pd.concat([v.assign(Brand=k) for k, v in p['plan'].items() if len(v)]), hide_index=True)
    st.subheader('Rekonsiliasi')
    st.dataframe(p['rekon'], hide_index=True)
    show_log(log)
    replace = st.checkbox('KOSONGKAN tab Raw dulu lalu isi ulang (--replace). Biasanya tidak dipakai: data baru ditambah di bawah.')
    if apply_box('gmv', len(d) > 0):
        try:
            with st.spinner('Menulis ke Google Sheets...'):
                ok, out = capture(gmv.terapkan, gmv_sheet(), p, raw_tab=raw_tab, replace=replace)
            (st.success if ok else st.warning)('Tally cocok.' if ok else 'Selesai ditulis, tapi tally belum cocok. Lihat log.')
            show_log(out, 'Log penulisan dan tally')
            st.session_state.pop('gmv', None)
        except Exception as e:  # noqa: BLE001
            st.error(f'Gagal menulis: {e}')


def main():
    st.set_page_config(page_title='Shopee BW · WEI', layout='wide', initial_sidebar_state='expanded')
    st.markdown(CSS, unsafe_allow_html=True)
    email = None
    if not LOCAL_MODE:
        if not st.user.get('is_logged_in'):
            login_page()
            st.stop()
        email = st.user.get('email')
        if not allowed(email, st.user.get('email_verified'), st.secrets.get('allowed_emails', [])):
            login_page(f'Akun {email} tidak punya akses. Pakai akun @{DOMAIN}.', can_logout=True)
            st.stop()
    st.session_state.setdefault('page', 'konten')
    {'konten': page_konten, 'event': page_event, 'gmv': page_gmv}[sidebar(email)]()


if __name__ == '__main__':
    main()
