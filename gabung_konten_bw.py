"""Gabung semua konten Mandatory + Kompetisi dari "Super Sheet Shopee BW" ke tab RAW bulan itu, satu link per baris.

Sumber: tab yang kata terakhirnya = bulan (--bulan) dan namanya RAW..., Form... atau ...Competition...
(tab Paid / Data Penerima dilewati). Link di dalam Google Docs / Google Sheet / Excel / Word peserta ikut dibuka;
kalau tidak bisa dibuka, linknya tetap ditulis dengan catatan di kolom Catatan.

Dijalankan tiap minggu: baris yang sudah ada di tab tujuan (Tipe + Username + Link sama) tidak ditulis lagi.

  python gabung_konten_bw.py --bulan Nov            # dry-run: cuma baca, simpan pratinjau CSV
  python gabung_konten_bw.py --bulan Nov --apply    # tambah baris baru ke 2 tujuan:
      1. Super Sheet, tab "RAW Nov": A:G di bawah data terakhir, Catatan/Sumber di H:I
      2. sheet BW Comm bulan itu, tab "Raw Content November": A:G, Catatan/Sumber di J:K, H:I (rumus) tidak disentuh

credentials.json (service account) harus punya akses Viewer ke sheet (Editor untuk --apply), dan Google Drive API
harus aktif di project-nya supaya Docs/Sheet peserta bisa dibuka.
"""
import argparse
import csv
import html
import io
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
CREDENTIALS_FILE = HERE / 'credentials.json'
SHEET_ID = '16bRIE2U57YlT_HyU4B_leI-fDXPQ5SW9r006lksgq-Y'
# tujuan kedua, ganti tiap bulan (atau pakai --raw-sheet / --raw-tab): [INT] BW Comm Shopee X WEI - NOVEMBER 2026
RAW_SHEET_ID = '1vqus61NmM0WYoe3ukQIbGfAEr_wf_PrknLBPxQNuYQ0'
RAW_TAB = 'Raw Content November'
HEADER = ['Timestamp', 'Username Shopee', 'Produk', 'BRANDS', 'Jenis Channel', 'Link', 'Tipe', 'Sumber Tab', 'Catatan']
BRANDS = {b.lower(): b for b in ['Vaseline', 'TRESemme', 'GAL', 'Ponds', 'Sunsilk', 'Clear', 'Dove']}

URL_RE = re.compile(r'h?ttps?://[^\s<>"\'()\[\]]+?(?=h?ttps?://|[\s<>"\'()\[\]]|$)', re.I)
FILE_ID_RE = re.compile(r'(?:/d/|[?&]id=)([\w-]{20,})')
# host yang query-nya cuma tracking (fromSource, smtt, si, ...): dibuang supaya link yang sama terdeteksi sama
SHORT_HOSTS = {'id.shp.ee', 's.shopee.co.id', 'threads.com', 'threads.net', 'vt.tiktok.com', 'vm.tiktok.com',
               'tiktok.com', 'youtu.be'}

MIME_DOC = 'application/vnd.google-apps.document'
MIME_SHEET = 'application/vnd.google-apps.spreadsheet'
MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MIME_DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


# ---------------------------------------------------------------- link
def clean_url(u):
    u = u.rstrip('.,;:!?*')
    if u.lower().startswith('ttp'):  # salah ketik "ttps://"
        u = 'h' + u
    p = urlsplit(u)
    if p.netloc.lower() in ('www.google.com', 'google.com') and p.path == '/url':  # bungkus redirect dari export Docs
        u = parse_qs(p.query).get('q', [u])[0]
    return u


def extract_urls(text):
    return [u for u in (clean_url(m.group()) for m in URL_RE.finditer(text or '')) if '.' in urlsplit(u).netloc]


def host_of(url):
    h = urlsplit(url).netloc.lower()
    return h[4:] if h.startswith('www.') else h


def norm(url):
    p = urlsplit(url)
    host, path = host_of(url), p.path.rstrip('/')
    if host in SHORT_HOSTS or not p.query:
        return host + path
    return f'{host}{path}?{p.query}'


def on(host, *domains):
    return any(host == d or host.endswith('.' + d) for d in domains)


def hint_of(text):
    t = (text or '').lower()
    if 'threads' in t:
        return 'Threads'
    if 'ig story' in t or 'instagram' in t:
        return 'IG Story'
    if 'share link' in t:
        return 'Share Link'
    if 'live' in t:
        return 'Live Streaming'
    if 'video' in t or t.strip() == 'sv':
        return 'Short Video'
    return None


def channel_of(url, hint):
    """Jenis Channel dengan istilah sheet: Short Video / Share Link / Live Streaming (IG, Threads, FB, dst = Share Link,
    seperti isian form RAW Nov dan kriteria COUNTIFS tab brand). None = bukan konten (link produk / profil)."""
    return as_sheet(platform_of(url, hint))


def as_sheet(ch):
    return 'Share Link' if ch in ('Threads', 'IG Story', 'IG Reels') else ch


def platform_of(url, hint):
    """Platform dari domain; link Shopee ikut kolom/pilihan form. None = link produk, bukan konten."""
    host, path = host_of(url), urlsplit(url).path
    if on(host, 'threads.com', 'threads.net'):
        return None if path.startswith('/@') and '/post/' not in path else 'Threads'  # /@user = link profil
    if on(host, 'instagram.com'):
        return 'IG Reels' if path.startswith(('/reel/', '/reels/')) else 'IG Story'
    if on(host, 'tiktok.com', 'youtube.com', 'youtu.be', 'facebook.com', 'fb.watch', 'fb.com', 'twitter.com', 'x.com'):
        return 'Share Link'
    if host == 's.shopee.co.id':
        return 'Share Link' if hint == 'Share Link' else None
    if on(host, 'shp.ee', 'shopee.co.id'):
        return hint if hint in ('Short Video', 'Share Link', 'Live Streaming') else 'Short Video'
    return hint or 'Lainnya'


def gfile(url):
    """ID file Google Docs/Sheet/Drive, 'folder' untuk folder Drive, None kalau bukan file Google."""
    if not on(host_of(url), 'docs.google.com', 'drive.google.com'):
        return None
    if '/folders/' in url:
        return 'folder'
    m = FILE_ID_RE.search(url)
    return m.group(1) if m else 'folder'


# ---------------------------------------------------------------- isi file peserta
def links_from_html(data):
    s = data.decode('utf-8', 'replace') if isinstance(data, bytes) else data
    s = re.sub(r'(?is)<(style|script|head)\b.*?</\1>', ' ', s)
    # href dibuka bungkus redirect-nya dulu: URL asli ada di dalam ?q=, kalau tidak nanti terpotong dua
    s = re.sub(r'(?is)<a\s[^>]*?href="([^"]*)"[^>]*>', lambda m: f' {clean_url(html.unescape(m.group(1)))} ', s)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    return [(u, None) for u in extract_urls(s)]


def links_from_xlsx(data):
    import openpyxl
    out = []
    for ws in openpyxl.load_workbook(io.BytesIO(data)).worksheets:
        hints = {}
        for row in ws.iter_rows():
            for c in row:
                text = '' if c.value is None else str(c.value)
                if c.row == 1:
                    hints[c.column] = hint_of(text)
                if c.hyperlink is not None and c.hyperlink.target:
                    text += ' ' + c.hyperlink.target
                out += [(u, hints.get(c.column)) for u in extract_urls(text)]
    return out


def links_from_docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = ' '.join(z.read(n).decode('utf-8', 'replace') for n in z.namelist() if n.startswith('word/'))
    # hyperlink ada di Target="..." file .rels; teks biasa di antara tag. URL skema XML lain sengaja tidak diambil.
    targets = ' '.join(re.search(r'Target="([^"]+)"', t).group(1)
                       for t in re.findall(r'<Relationship\b[^>]*/hyperlink"[^>]*>', text) if 'Target="' in t)
    body = re.sub(r'<[^>]+>', '', re.sub(r'</w:p>', ' ', text))
    return [(u, None) for u in extract_urls(html.unescape(targets + ' ' + body))]


class Fetcher:
    """Buka file Google sekali saja per run. Hasil: (nama, [(url, hint)]) atau raise FileError."""

    def __init__(self, drive):
        self.drive, self.cache = drive, {}

    def __call__(self, fid):
        if fid not in self.cache:
            try:
                self.cache[fid] = self._fetch(fid)
            except FileError as e:
                self.cache[fid] = e
        hit = self.cache[fid]
        if isinstance(hit, FileError):
            raise hit
        return hit

    def _fetch(self, fid):
        from googleapiclient.errors import HttpError
        if fid == 'folder':
            raise FileError('Folder Drive, cek manual')
        f = self.drive.files()
        try:
            meta = f.get(fileId=fid, fields='name,mimeType', supportsAllDrives=True).execute(num_retries=3)
            mt = meta['mimeType']
            if mt == MIME_DOC:
                return meta['name'], links_from_html(f.export(fileId=fid, mimeType='text/html').execute(num_retries=3))
            if mt == MIME_SHEET:
                return meta['name'], links_from_xlsx(f.export(fileId=fid, mimeType=MIME_XLSX).execute(num_retries=3))
            if mt in (MIME_XLSX, MIME_DOCX) or mt.startswith('text/'):
                data = f.get_media(fileId=fid, supportsAllDrives=True).execute(num_retries=3)
                if mt == MIME_XLSX:
                    return meta['name'], links_from_xlsx(data)
                if mt == MIME_DOCX:
                    return meta['name'], links_from_docx(data)
                return meta['name'], [(u, None) for u in extract_urls(data.decode('utf-8', 'replace'))]
            raise FileError(f'File Drive bukan Docs/Sheet ({mt}), cek manual')
        except HttpError as e:
            body = str(e.content)
            if 'accessNotConfigured' in body or 'SERVICE_DISABLED' in body:
                sys.exit('ERROR: Google Drive API belum aktif di project credentials.json. Aktifkan dulu di '
                         'console.cloud.google.com > APIs & Services > Library > Google Drive API.')
            reason = {403: 'akses ditolak', 404: 'akses ditolak / file tidak ada'}.get(e.resp.status, f'error {e.resp.status}')
            raise FileError(f'Docs/Sheet tidak bisa dibuka: {reason}') from None
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            raise FileError(f'Docs/Sheet tidak bisa dibuka: file rusak ({e.__class__.__name__})') from None


class FileError(Exception):
    pass


# ---------------------------------------------------------------- tab sumber -> baris
def tab_brand(title):
    words = [w for w in title.split()[:-1] if w.lower() not in ('form', 'competition', 'raw')]
    name = ' '.join(words)
    return BRANDS.get(name.lower(), name)


BRAND_WORDS = {'Vaseline': r'vaseline', 'TRESemme': r'tres+(?:em+e?)?', 'GAL': r'gal|glow', 'Ponds': r'pond\'?s?',
               'Sunsilk': r'sunsilk', 'Clear': r'clear', 'Dove': r'dove'}


def brand_in(text):
    """Brand pertama yang disebut di teks (judul tab / header kolom), atau ''."""
    return next((b for b, pat in BRAND_WORDS.items() if re.search(rf'\b(?:{pat})\b', text.lower())), '')


def other_brand(file_name, brand):
    """Brand lain yang disebut di judul file peserta (mis. file "Clear" dikirim ke kompetisi Dove), atau ''."""
    low = file_name.lower()
    hit = [b for b, pat in BRAND_WORDS.items() if re.search(rf'\b(?:{pat})\b', low)]
    return ', '.join(hit) if hit and brand not in hit else ''


def rows_from_tab(title, values, fetch):
    if not values:
        return
    head = [h.strip().lower() for h in values[0]]
    idx = lambda pred: [i for i, h in enumerate(head) if pred(h)]  # noqa: E731
    ts_col = idx(lambda h: h == 'timestamp')
    user_cols = idx(lambda h: 'username' in h)
    prod_cols = idx(lambda h: 'produk' in h)
    brand_col = idx(lambda h: h in ('brands', 'brand'))
    tipe_col = idx(lambda h: h == 'tipe')
    chan_col = idx(lambda h: h == 'jenis channel')
    link_cols = idx(lambda h: 'link' in h and 'akun' not in h)
    col_hint = {i: hint_of(values[0][i]) for i in link_cols}
    paid = 'paid' in title.lower()
    default_tipe = 'Kompetisi' if 'competition' in title.lower() else 'Mandatory'  # tab Paid juga Mandatory
    col_brand = {i: brand_in(values[0][i]) for i in link_cols} if paid else {}
    title_brand = brand_in(title) if paid else ''

    for n, r in enumerate(values[1:], start=2):  # n = nomor baris di tab sumber (untuk penanda warna)
        get = lambda i: r[i].strip() if i < len(r) else ''  # noqa: E731
        first = lambda cols: next((get(i) for i in cols if get(i)), '')  # noqa: E731
        base = [first(ts_col), first(user_cols), first(prod_cols), first(brand_col) or tab_brand(title)]
        tipe = first(tipe_col) or default_tipe
        row_hint = hint_of(first(chan_col))
        for c in link_cols:
            hint = row_hint or col_hint[c]
            row = base[:3] + [col_brand.get(c) or title_brand or base[3]]
            for u in extract_urls(get(c)):
                fid = gfile(u)
                if fid is None:
                    ch = channel_of(u, hint)
                    if ch:
                        yield row + [ch, u, tipe, title, '', n]
                    continue
                try:
                    name, inner = fetch(fid)
                except FileError as e:
                    yield row + [as_sheet(hint) or 'Lainnya', u, tipe, title, str(e), n]
                    continue
                kept, note = 0, f'dari file "{name}"'
                other = other_brand(name, base[3])
                if other:
                    note += f' (judul file brand {other}, cek)'
                for u2, h2 in inner:
                    ch = channel_of(u2, h2 or hint)
                    if ch and not gfile(u2):
                        kept += 1
                        yield row + [ch, u2, tipe, title, note, n]
                if not kept:
                    yield row + [as_sheet(hint) or 'Lainnya', u, tipe, title, f'File "{name}" kebuka tapi tidak ada link konten', n]


def key(row):
    """Tipe + username + link ternormalisasi: penentu baris sudah pernah ditulis atau belum."""
    user = re.sub(r'\s+', '', row[1]).lstrip('@').lower()
    return row[6].strip().lower(), user, norm(row[5])


def new_rows(rows, existing):
    seen, out = set(existing), []
    for r in rows:
        k = key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def pick_tabs(titles, bulan):
    b = bulan.lower()[:3]
    out = []
    for t in titles:
        low = t.lower()
        if 'penerima' in low or low.startswith('gabungan'):
            continue
        if t.split()[-1].lower()[:3] == b and (low.startswith(('raw', 'form')) or 'competition' in low):
            out.append(t)
    return out


MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'mei': 5, 'may': 5, 'jun': 6, 'jul': 7, 'agu': 8, 'aug': 8,
          'sep': 9, 'okt': 10, 'oct': 10, 'nov': 11, 'des': 12, 'dec': 12}


def month_no(name):
    return MONTHS.get(name.lower()[:3])


def only_month(values, m):
    """Header + baris yang Timestamp-nya (hari/bulan/tahun) jatuh di bulan m; sisanya dikosongkan (posisi baris tetap)."""
    if not values:
        return values
    ts = next((i for i, h in enumerate(values[0]) if h.strip().lower() == 'timestamp'), None)
    if ts is None:
        return values[:1]
    keep = lambda r: (mt := re.match(r'\s*\d{1,2}/(\d{1,2})/\d{4}', r[ts] if ts < len(r) else '')) and int(mt.group(1)) == m  # noqa: E731
    return values[:1] + [r if keep(r) else [] for r in values[1:]]


# ---------------------------------------------------------------- Google API
def services(write, creds=None):
    """creds = google Credentials siap pakai (mis. dari Streamlit secrets); kosong = credentials.json."""
    import google_auth_httplib2
    import httplib2
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    scopes = ['https://www.googleapis.com/auth/spreadsheets' + ('' if write else '.readonly'),
              'https://www.googleapis.com/auth/drive.readonly']
    creds = creds or service_account.Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=scopes)
    mk = lambda api, v: build(api, v, http=google_auth_httplib2.AuthorizedHttp(  # noqa: E731
        creds, http=httplib2.Http(timeout=180)), cache_discovery=False)
    return mk('sheets', 'v4').spreadsheets(), mk('drive', 'v3'), creds.service_account_email


def read_keys(sheets, sid, tab, last_col):
    """Kunci baris yang sudah ada di tab tujuan + nomor baris terakhir yang berisi (1 = cuma header)."""
    vals = sheets.values().get(spreadsheetId=sid, range=f"'{tab}'!A2:{last_col}").execute(num_retries=3).get('values', [])
    return [key((r + [''] * 9)[:9]) for r in vals if len(r) > 5], len(vals) + 1


def stale_formulas(sheets, sid, tab, last_row):
    """ARRAYFORMULA H2/I2 (Week, Username clean) yang rentangnya berhenti sebelum last_row."""
    got = sheets.values().get(spreadsheetId=sid, range=f"'{tab}'!H2:I2",
                              valueRenderOption='FORMULA').execute(num_retries=3).get('values') or [[]]
    return [f for f in got[0] if any(int(n) < last_row for n in re.findall(r'[A-Z]+2:[A-Z]+(\d+)', f))]


def report(label, rows, out, preview):
    tally = {}
    for r in out:
        tally[(r[6], r[4])] = tally.get((r[6], r[4]), 0) + 1
    print(f'\n[{label}] baris baru: {len(out)} (dilewati karena sudah ada / dobel: {len(rows) - len(out)})')
    for (tipe, ch), n in sorted(tally.items()):
        print(f'  {tipe:10} {ch:15} {n}')
    print(f'  Docs/Sheet tidak bisa dibuka: {sum(1 for r in out if r[8].startswith("Docs/Sheet tidak bisa"))}')
    with open(preview, 'w', newline='', encoding='utf-8-sig') as fh:
        csv.writer(fh).writerows([HEADER] + [r[:9] for r in out])
    print(f'  Pratinjau: {preview}')


def write_below(sheets, sid, tab, first, out, note_col):
    """Tulis mulai baris `first`: A:G = kolom form, note_col dan sebelahnya = Catatan, Sumber Tab.
    Kolom lain (mis. rumus H:I di Raw Content) tidak disentuh. Baris/kolom grid ditambah kalau kurang."""
    last, note_end = first + len(out) - 1, chr(ord(note_col) + 1)
    meta = sheets.get(spreadsheetId=sid, fields='sheets.properties').execute(num_retries=3)
    prop = next(s['properties'] for s in meta['sheets'] if s['properties']['title'] == tab)
    grid, need_cols = prop['gridProperties'], ord(note_end) - ord('A') + 1
    grow = [('ROWS', last - grid['rowCount']), ('COLUMNS', need_cols - grid['columnCount'])]
    reqs = [{'appendDimension': {'sheetId': prop['sheetId'], 'dimension': d, 'length': n}} for d, n in grow if n > 0]
    if reqs:
        sheets.batchUpdate(spreadsheetId=sid, body={'requests': reqs}).execute(num_retries=3)
    data = [{'range': f"'{tab}'!A{first}:G{last}", 'values': [r[:7] for r in out]},
            {'range': f"'{tab}'!{note_col}{first}:{note_end}{last}", 'values': [[r[8], r[7]] for r in out]}]
    head = (sheets.values().get(spreadsheetId=sid, range=f"'{tab}'!A1:{note_end}1").execute(
        num_retries=3).get('values') or [[]])[0]
    head += [''] * (ord(note_end) - ord('A') + 1 - len(head))
    if not head[0]:  # tab kosong: tulis header A:G juga
        data.append({'range': f"'{tab}'!A1:G1", 'values': [HEADER[:7]]})
    if not head[ord(note_col) - ord('A')]:
        data.append({'range': f"'{tab}'!{note_col}1:{note_end}1", 'values': [['Catatan', 'Sumber Tab']]})
    sheets.values().batchUpdate(spreadsheetId=sid, body={'valueInputOption': 'RAW', 'data': data}).execute(num_retries=3)


def user_key(u):
    return re.sub(r'\s+', '', u).lstrip('@').lower()


def missing_users(rows, tab_users):
    """{brand: {username: jumlah link}} untuk username baris baru yang belum ada di tab brand (tab_users = {brand: set kunci})."""
    out = {}
    for r in rows:
        if r[1].strip() and user_key(r[1]) not in tab_users.get(r[3], set()):
            d = out.setdefault(r[3], {})
            d[r[1].strip()] = d.get(r[1].strip(), 0) + 1
    return out


TPL_ROW, TPL_RANGE = 16, 'N16:CF16'  # baris contoh di tab brand: rumus N:CF disalin untuk username baru


def fill_row(tpl, n):
    """Rumus baris TPL_ROW dipindah ke baris n (referensi baris 16 -> n); rentang $D$2:$D$9742 jadi terbuka."""
    out = []
    for f in tpl:
        if isinstance(f, str) and f.startswith('='):
            f = re.sub(r'(?<![\w$])(\$?[A-Z]{1,3})16(?!\d)', rf'\g<1>{n}', f)
            f = re.sub(r'(\$[A-Z]+\$2:\$[A-Z]+)\$\d+', r'\1', f)
        out.append(f)
    return out


def plan_users(sheets, sid, titles, rows, path):
    """Cek username baris baru ke kolom B tab brand di BW Comm (hanya baca) dan rencanakan penambahan yang belum ada.
    Hasil: [(tab, baris pertama, [username], rumus contoh)]."""
    tab_users, last, tab_of = {}, {}, {}
    for brand in sorted({r[3] for r in rows}):
        tab = next((t for t in titles if t.lower() == brand.lower()), None)
        if tab:
            col = sheets.values().get(spreadsheetId=sid, range=f"'{tab}'!B16:B").execute(num_retries=3).get('values', [])
            tab_users[brand], last[brand], tab_of[brand] = {user_key(v[0]) for v in col if v}, 15 + len(col), tab
    miss = missing_users([r for r in rows if r[3] in tab_users], tab_users)
    print()
    print('Cek username ke tab brand (hanya baca):')
    if not miss:
        print('  semua username baris baru sudah ada di tab brand-nya.')
    plan = []
    for brand, d in sorted(miss.items()):
        users, seen, bad = [], set(), []
        for u in d:
            c = u.lstrip('@').strip()
            if not re.fullmatch(r'[\w.]+', c):
                bad.append(u)
            elif user_key(c) not in seen:
                seen.add(user_key(c))
                users.append(c)
        print(f'  {brand}: {len(d)} username belum ada di tab {tab_of[brand]} ({sum(d.values())} link): ' + ', '.join(list(d)[:8]))
        if users:
            tpl = sheets.values().get(spreadsheetId=sid, range=f"'{tab_of[brand]}'!{TPL_RANGE}",
                                      valueRenderOption='FORMULA').execute(num_retries=3).get('values', [[]])[0]
            plan.append((tab_of[brand], last[brand] + 1, users, tpl))
            print(f'    -> akan ditambah di baris {last[brand] + 1}-{last[brand] + len(users)} tab {tab_of[brand]}')
        if bad:
            print(f'    dilewati (bukan format username, isi manual): {", ".join(bad)}')
    nob = sorted({r[3] for r in rows} - set(tab_users))
    if nob:
        print('  brand tanpa tab brand (dilewati):', ', '.join(nob))
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['Brand', 'Username', 'Jumlah link baru'])
        w.writerows([b, u, n] for b, d in sorted(miss.items()) for u, n in d.items())
    print(f'  Daftar lengkap: {path}')
    return plan


def apply_users(sheets, sid, plan, backup_path):
    """Tulis username (kolom B) + rumus N:CF ke baris kosong setelah username terakhir tiap tab brand. Isi lama di-backup."""
    import json
    meta = sheets.get(spreadsheetId=sid, fields='sheets.properties').execute(num_retries=3)
    props = {x['properties']['title']: x['properties'] for x in meta['sheets']}
    backup, data, grow = {}, [], []
    for tab, first, users, tpl in plan:
        last = first + len(users) - 1
        rows_now = props[tab]['gridProperties']['rowCount']
        if last > rows_now:
            grow.append({'appendDimension': {'sheetId': props[tab]['sheetId'], 'dimension': 'ROWS', 'length': last - rows_now}})
        rng = f"'{tab}'!N{first}:CF{last}"
        backup[rng] = sheets.values().get(spreadsheetId=sid, range=rng, valueRenderOption='FORMULA').execute(
            num_retries=3).get('values', [])
        for k, u in enumerate(users):
            n = first + k
            data += [{'range': f"'{tab}'!B{n}", 'values': [[u]]},
                     {'range': f"'{tab}'!N{n}:CF{n}", 'values': [fill_row(tpl, n)]}]
    pathlib.Path(backup_path).write_text(json.dumps(backup), encoding='utf-8')
    print(f'Backup isi lama baris tab brand: {backup_path}')
    if grow:
        sheets.batchUpdate(spreadsheetId=sid, body={'requests': grow}).execute(num_retries=3)
    for i in range(0, len(data), 100):
        sheets.values().batchUpdate(spreadsheetId=sid, body={'valueInputOption': 'USER_ENTERED', 'data': data[i:i + 100]}).execute(num_retries=3)
    print(f'Selesai: {sum(len(u) for _, _, u, _ in plan)} username ditambahkan ke tab brand.')


ORANGE = {'red': 1.0, 'green': 0.75, 'blue': 0.35}


def rows_done(rows, ok, skip_tab):
    """{tab sumber: [nomor baris]} yang semua link-nya sudah ada di tab tujuan (ok(key) = benar)."""
    seen, bad = {}, set()
    for r in rows:
        seen.setdefault(r[7], set()).add(r[9])
        if not ok(key(r)):
            bad.add((r[7], r[9]))
    return {t: sorted(n for n in ns if (t, n) not in bad) for t, ns in seen.items() if t != skip_tab}


def username_cols(header):
    """Indeks kolom 'Username Shopee' di baris judul (kalau tidak ada, kolom yang judulnya memuat 'username')."""
    low = [h.strip().lower() for h in header]
    return [i for i, h in enumerate(low) if 'username shopee' in h] or [i for i, h in enumerate(low) if 'username' in h]


def mark_orange(sheets, sid, per_tab, ucols):
    """Warnai sel Username Shopee di baris sumber yang sudah masuk (hanya latar belakang, isi sel tidak diubah)."""
    meta = sheets.get(spreadsheetId=sid, fields='sheets.properties').execute(num_retries=3)
    ids = {x['properties']['title']: x['properties']['sheetId'] for x in meta['sheets']}
    reqs = []
    for tab, nums in per_tab.items():
        runs = []
        for n in nums:
            if runs and n == runs[-1][1] + 1:
                runs[-1][1] = n
            else:
                runs.append([n, n])
        for a, b in runs:
            for c in ucols.get(tab, []):
                reqs.append({'repeatCell': {'range': {'sheetId': ids[tab], 'startRowIndex': a - 1, 'endRowIndex': b,
                                                      'startColumnIndex': c, 'endColumnIndex': c + 1},
                                            'cell': {'userEnteredFormat': {'backgroundColor': ORANGE}},
                                            'fields': 'userEnteredFormat.backgroundColor'}})
    for i in range(0, len(reqs), 100):
        sheets.batchUpdate(spreadsheetId=sid, body={'requests': reqs[i:i + 100]}).execute(num_retries=3)


def buat_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bulan', required=True, help='kata terakhir nama tab sumber, mis. Nov / OCT')
    ap.add_argument('--target', help='tab tujuan di Super Sheet (bawaan: "RAW <bulan>")')
    ap.add_argument('--tab', action='append', help='pakai tab ini saja (boleh diulang), ganti pilihan otomatis')
    ap.add_argument('--tambah-bulan', action='append', default=[], metavar='BULAN',
                    help='ikut baca tab bulan lain (mis. OCT), tapi hanya baris yang tanggalnya di --bulan; boleh diulang')
    ap.add_argument('--sheet', default=SHEET_ID)
    ap.add_argument('--raw-sheet', default=RAW_SHEET_ID, help='spreadsheet BW Comm bulan ini')
    ap.add_argument('--raw-tab', default=RAW_TAB, help='tab Raw Content bulan ini')
    ap.add_argument('--ke-raw-content', action='store_true',
                    help='tulis ke Raw Content walau bulan sumber beda dengan nama tab (tanggal asli tetap, Week ikut hari)')
    ap.add_argument('--apply', action='store_true', help='benar-benar menulis ke Google Sheets')
    return ap


def siapkan(a, sheets, drive, email):
    """Tahap baca saja: kumpulkan baris sumber, cari yang baru, rencanakan penanda warna dan username baru.
    Hasil dipakai terapkan(); tidak ada yang ditulis ke sheet."""
    from types import SimpleNamespace
    from googleapiclient.errors import HttpError

    def titles_of(sid):
        try:
            meta = sheets.get(spreadsheetId=sid, fields='sheets.properties.title').execute(num_retries=3)
        except HttpError as e:
            sys.exit(f'ERROR: sheet {sid} tidak bisa dibaca ({e.resp.status}). Share sheet ke {email} '
                     f'(Viewer untuk dry-run, Editor untuk --apply).')
        return [s['properties']['title'] for s in meta['sheets']]

    titles = titles_of(a.sheet)
    want = (a.target or f'RAW {a.bulan}').lower()
    target = next((t for t in titles if t.lower() == want), None)
    if not target:
        sys.exit(f'ERROR: tab tujuan "{a.target or "RAW " + a.bulan}" tidak ada di Super Sheet.')
    bm = month_no(a.bulan)
    tabs = [(t, None) for t in (a.tab or pick_tabs(titles, a.bulan))]
    for b in a.tambah_bulan:
        if not bm:
            sys.exit(f'ERROR: --tambah-bulan butuh --bulan berupa nama bulan, bukan "{a.bulan}".')
        tabs += [(t, bm) for t in pick_tabs(titles, b) if (t, None) not in tabs and not t.lower().startswith('raw ' + b.lower()[:3])]
    if getattr(a, 'tabs_pilih', None):  # dari Streamlit: daftar (tab, bulan penyaring atau None) pilihan pengguna
        tabs = list(a.tabs_pilih)
    if not tabs:
        sys.exit(f'ERROR: tidak ada tab sumber untuk bulan "{a.bulan}".')
    print('Tab sumber:', ', '.join(t + (' (hanya baris bulan ini)' if m else '') for t, m in tabs))

    fetch, rows, ucols, info = Fetcher(drive), [], {}, []
    for t, m in tabs:
        vals = sheets.values().get(spreadsheetId=a.sheet, range=f"'{t}'").execute(num_retries=3).get('values', [])
        total = len(vals) - 1 if vals else 0
        ucols[t] = username_cols(vals[0]) if vals else []
        if m:
            vals = only_month(vals, m)
        got = list(rows_from_tab(t, vals, fetch))
        print(f'  {t}: {total} respons' + (f', {sum(1 for r in vals[1:] if r)} bulan ini' if m else '') + f' -> {len(got)} link')
        info.append((t, m, total, sum(1 for r in vals[1:] if r) if m else total, len(got)))
        rows += got

    # tujuan 1: tab RAW <bulan> di Super Sheet (sekaligus sumber; baris aslinya dikenali lewat kunci, tidak dobel)
    g_keys, g_last = read_keys(sheets, a.sheet, target, 'G')
    g_out = new_rows(rows, g_keys)
    report(f'Super Sheet / {target}', rows, g_out, HERE / f'gabung_preview_{a.bulan}.csv')

    # tujuan 2: tab Raw Content di sheet BW Comm, hanya kalau bulannya sama (data OCT jangan masuk tab November)
    raw_ok = a.ke_raw_content or a.bulan.lower()[:3] in a.raw_tab.lower()
    r_out, r_last = [], 0
    if not raw_ok:
        print(f'\n[{a.raw_tab}] dilewati: bulan "{a.bulan}" beda dengan nama tab. Pakai --raw-sheet / --raw-tab bulan itu.')
    else:
        if a.raw_tab not in titles_of(a.raw_sheet):
            sys.exit(f'ERROR: tab "{a.raw_tab}" tidak ada di sheet {a.raw_sheet}.')
        r_keys, r_last = read_keys(sheets, a.raw_sheet, a.raw_tab, 'G')
        r_out = new_rows(rows, r_keys)
        report(f'BW Comm / {a.raw_tab}', rows, r_out, HERE / f'gabung_preview_{a.bulan}_raw_content.csv')
        if r_out:
            for f in stale_formulas(sheets, a.raw_sheet, a.raw_tab, r_last + len(r_out)):
                print(f'  PERINGATAN: rumus di H2/I2 berhenti sebelum baris {r_last + len(r_out)}, baris baru tidak '
                      f'dapat Week / Username clean. Ubah rentangnya jadi terbuka (A2:A2009 -> A2:A):\n    {f[:100]}')

    user_plan = []
    if raw_ok and r_out:
        user_plan = plan_users(sheets, a.raw_sheet, titles_of(a.raw_sheet), r_out, HERE / 'gabung_username_belum_ada.csv')

    dg = set(g_keys) | {key(r) for r in g_out}
    dr = (set(r_keys) | {key(r) for r in r_out}) if raw_ok else None
    per_tab = rows_done(rows, lambda k: k in dg and (dr is None or k in dr), target)
    per_tab = {t: n for t, n in per_tab.items() if n}
    print()
    print(f'Baris sumber yang diwarnai oranye (semua link-nya sudah masuk): {sum(map(len, per_tab.values()))}')
    for t, n in per_tab.items():
        print(f'  {t}: {len(n)}')
    return SimpleNamespace(a=a, target=target, rows=rows, ucols=ucols, g_out=g_out, g_last=g_last, r_out=r_out,
                           r_last=r_last, user_plan=user_plan, per_tab=per_tab, tabs=tabs, info=info)


def terapkan(p, sheets):
    """Tahap tulis (hanya dipanggil dari --apply / tombol Terapkan)."""
    a, target, ucols, g_out, g_last, r_out, r_last = p.a, p.target, p.ucols, p.g_out, p.g_last, p.r_out, p.r_last
    user_plan, per_tab = p.user_plan, p.per_tab
    if g_out:
        write_below(sheets, a.sheet, target, g_last + 1, g_out, 'H')
        print(f'Selesai: {len(g_out)} baris ditambahkan ke "{target}" (baris {g_last + 1}-{g_last + len(g_out)}).')
    if r_out:
        write_below(sheets, a.raw_sheet, a.raw_tab, r_last + 1, r_out, 'J')
        print(f'Selesai: {len(r_out)} baris ditambahkan ke "{a.raw_tab}" (baris {r_last + 1}-{r_last + len(r_out)}).')
    if user_plan:
        from datetime import datetime
        apply_users(sheets, a.raw_sheet, user_plan, HERE / f'backup_username_tab_brand_{datetime.now():%Y%m%d_%H%M%S}.json')
    mark_orange(sheets, a.sheet, per_tab, ucols)
    print(f'Selesai: {sum(map(len, per_tab.values()))} baris sumber diwarnai oranye (kolom Username Shopee).')


def main(argv=None):
    a = buat_parser().parse_args(argv)
    sheets, drive, email = services(a.apply)
    p = siapkan(a, sheets, drive, email)
    if not a.apply:
        print('\nDRY-RUN: tidak ada yang ditulis. Tambahkan --apply untuk menulis.')
        return
    terapkan(p, sheets)


if __name__ == '__main__':
    main()
