"""Gabung konten EVENT (gathering, SoW Hari-H / Setelah Event, Threads challenge) ke sheet "Event" dan
tab Raw Content November, satu link per baris, Tipe = Event. Event baru: tambahkan satu baris di EVENTS.

  python gabung_event_bw.py            # dry-run: cuma baca, simpan pratinjau CSV
  python gabung_event_bw.py --apply    # tambah baris baru ke dua tujuan

Anti-dobel dan cara buka Docs/Sheet sama dengan gabung_konten_bw.py (kunci Tipe + Username + Link).
Timestamp form event (format AS, bulan/hari) diubah ke hari/bulan seperti RAW Nov, supaya rumus Week benar.
"""
import argparse
import re
import sys
from datetime import datetime

from gabung_konten_bw import (BRAND_WORDS, HERE, apply_users, key, mark_orange, plan_users, RAW_SHEET_ID, RAW_TAB, Fetcher, new_rows,
                              read_keys, report, rows_done, rows_from_tab, services, stale_formulas, write_below)

# sheet, tab, kolom link, kolom username, brand, baris header (data mulai baris sesudahnya)
EVENTS = [
    ('1Qnhfd7ZGLau377z_e5oTLgRvCPFHhOBDbUsOyCdhwiA', ' [SHOPEE] Form SOW Hari - H', 'G:L', 'E', 'Vaseline', 1),
    ('1Qnhfd7ZGLau377z_e5oTLgRvCPFHhOBDbUsOyCdhwiA', 'THREADS CHALLENGE', 'R:T', 'N', 'Vaseline', 1),  # bagian Shopee
    ('1-Zzir3ub34gHmWnkY4pqKSdT4h2ILY0okpaOp2tNe8k', 'SoW Hari-H', 'G:I', 'E', 'Clear', 1),
    ('1-Zzir3ub34gHmWnkY4pqKSdT4h2ILY0okpaOp2tNe8k', 'SoW Setelah Event', 'G:L', 'E', 'Clear', 1),
    ('1JPRgAE9wIcYVqs870L0ysGi1U0_n5daOGmjq0IFdJAQ', 'SoW Hari-H', 'H:I', 'E', 'Vaseline', 2),
    ('1JPRgAE9wIcYVqs870L0ysGi1U0_n5daOGmjq0IFdJAQ', 'SOW After Event', 'G:N', 'E', 'Vaseline', 1),
]
EVENT_SHEET_ID = '1t7d0zmEgw5z1eSryBF5ePjiRKbo8rTQZZvIV49Kpark'  # sheet "Event", tab gid 0


def col(letter):
    return ord(letter.upper()) - ord('A')


def ddmm(ts):
    """'11/15/2026 10:13:02' (bulan/hari) -> '15/11/2026 10:13:02'; selain format itu dibiarkan."""
    try:
        return datetime.strptime(ts.strip(), '%m/%d/%Y %H:%M:%S').strftime('%d/%m/%Y %H:%M:%S')
    except ValueError:
        return ts


def produk_of(header):
    """Nama produk dari judul kolom: 'Keranjang Oren Vaseline Proderma Moisturizer (SV 1)' / '(Vaseline PDRN)'."""
    m = re.search(r'Keranjang Oren\s+([^(]+?)\s*\(', header)
    if m:
        return m.group(1)
    brands = '|'.join(BRAND_WORDS.values())
    return next((p.strip() for p in re.findall(r'\(([^)]+)\)', header) if re.search(rf'\b(?:{brands})\b', p.lower())), '')


def rows_from_event(values, links, user_col, brand, header_row, sumber, fetch):
    """Tiap kolom link diubah jadi tabel kecil format form biasa, lalu diproses rows_from_tab (Docs, channel, catatan)."""
    head, data = values[header_row - 1], values[header_row:]
    a, b = (col(x) for x in links.split(':'))
    get = lambda r, i: r[i].strip() if i < len(r) else ''  # noqa: E731
    for c in range(a, b + 1):
        h = get(head, c)
        table = [['Timestamp', 'Username Shopee', 'Produk', 'BRANDS', 'Tipe', h if 'link' in h.lower() else 'Link ' + h]]
        table += [[ddmm(get(r, 0)), get(r, col(user_col)), produk_of(h), brand, 'Event', get(r, c)]
                  for r in data]
        for row in rows_from_tab(sumber, table, fetch):
            row[9] += header_row - 1  # nomor baris di tabel kecil -> nomor baris di sheet sumber
            yield row


DAFTAR_KOLOM = ['Aktif', 'Nama', 'Sheet ID', 'Tab', 'Kolom link', 'Kolom username', 'Brand', 'Baris header']


def sheet_id_dari(text):
    """Link Google Sheet atau ID polos -> ID."""
    m = re.search(r'/d/([\w-]{20,})', text) or re.fullmatch(r'\s*([\w-]{20,})\s*', text)
    return m.group(1) if m else ''


def letters(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    return (chr(64 + i // 26) if i >= 26 else '') + chr(65 + i % 26)


def events_dari(daftar):
    """Baris daftar yang Aktif -> tuple seperti EVENTS."""
    return [(r['Sheet ID'], r['Tab'], r['Kolom link'], r['Kolom username'], r['Brand'], int(r['Baris header']))
            for r in daftar if r.get('Aktif') and r.get('Sheet ID') and r.get('Tab') and r.get('Kolom link')]


def siapkan(sheets, drive, email, events=None, event_sheet=EVENT_SHEET_ID, raw_sheet=RAW_SHEET_ID, raw_tab=RAW_TAB):
    """Tahap baca saja: kumpulkan baris event dan cari yang baru per tujuan. Hasil: (rows, plans, user_plan, warna).
    events = daftar tuple seperti EVENTS (kosong = EVENTS bawaan). Sumber yang tidak bisa dibaca dilaporkan 'GAGAL' dan dilewati.
    warna = {sheet sumber: ({tab: [nomor baris]}, {tab: [indeks kolom username]})} untuk baris yang semua link-nya sudah masuk."""
    from googleapiclient.errors import HttpError
    fetch, rows, titles, src = Fetcher(drive), [], {}, {}
    for sid, tab, links, user_col, brand, header_row in (events if events is not None else EVENTS):
        try:
            if sid not in titles:
                titles[sid] = sheets.get(spreadsheetId=sid, fields='properties.title').execute(
                    num_retries=3)['properties']['title']
            vals = sheets.values().get(spreadsheetId=sid, range=f"'{tab}'").execute(num_retries=3).get('values', [])
        except HttpError as e:
            print(f'  GAGAL: {sid} / "{tab}" tidak bisa dibaca ({e.resp.status}). Share sheet ke {email} sebagai Viewer.')
            continue
        label = f'{titles[sid]} / {tab.strip()}'
        src[label] = (sid, tab, col(user_col))
        got = list(rows_from_event(vals, links, user_col, brand, header_row, label, fetch))
        print(f'  {label} [{links}]: {len(got)} link')
        rows += got

    meta = sheets.get(spreadsheetId=event_sheet, fields='sheets.properties').execute(num_retries=3)
    props = [s['properties'] for s in meta['sheets']]
    ev_tab = next((p['title'] for p in props if p['sheetId'] == 0), props[0]['title'])  # tab pertama / gid 0 di sheet Event
    targets = [(event_sheet, ev_tab, 'H', f'Event / {ev_tab}', 'event'),
               (raw_sheet, raw_tab, 'J', f'BW Comm / {raw_tab}', 'event_raw_content')]
    plans, done = [], []
    for sid, tab, note_col, label, name in targets:
        keys, last = read_keys(sheets, sid, tab, 'G')
        out = new_rows(rows, keys)
        report(label, rows, out, HERE / f'gabung_preview_{name}.csv')
        if out and sid == raw_sheet:
            for f in stale_formulas(sheets, sid, tab, last + len(out)):
                print(f'  PERINGATAN: rumus H2/I2 berhenti sebelum baris {last + len(out)}; ubah rentangnya jadi '
                      f'terbuka (A2:A2009 -> A2:A):\n    {f[:100]}')
        plans.append((sid, tab, note_col, last, out))
        done.append(set(keys) | {key(r) for r in out})
    raw_out = next((out for sid, _, _, _, out in plans if sid == raw_sheet), [])
    user_plan = []
    if raw_out:
        titles_raw = [x['properties']['title'] for x in sheets.get(
            spreadsheetId=raw_sheet, fields='sheets.properties.title').execute(num_retries=3)['sheets']]
        user_plan = plan_users(sheets, raw_sheet, titles_raw, raw_out, HERE / 'gabung_username_belum_ada_event.csv')

    warna = {}
    for label, nums in rows_done(rows, lambda k: all(k in d for d in done), None).items():
        if nums and label in src:
            sid, tab, ui = src[label]
            per_tab, ucols = warna.setdefault(sid, ({}, {}))
            per_tab[tab], ucols[tab] = nums, [ui]
            print(f'  Diwarnai oranye (kolom username) di {label}: {len(nums)} baris')
    return rows, plans, user_plan, warna


def terapkan(plans, user_plan, sheets, warna=None, raw_sheet=RAW_SHEET_ID):
    """Tahap tulis (hanya dari --apply / tombol Terapkan)."""
    from googleapiclient.errors import HttpError
    for sid, tab, note_col, last, out in plans:
        if out:
            print(f'Menulis {len(out)} baris ke "{tab}" (baris {last + 1}-{last + len(out)}) ...')
            write_below(sheets, sid, tab, last + 1, out, note_col)
            print(f'Selesai: {len(out)} baris ditambahkan ke "{tab}" (baris {last + 1}-{last + len(out)}).')
    if user_plan:
        apply_users(sheets, raw_sheet, user_plan, HERE / f'backup_username_tab_brand_{datetime.now():%Y%m%d_%H%M%S}.json')
    for sid, (per_tab, ucols) in (warna or {}).items():
        try:
            mark_orange(sheets, sid, per_tab, ucols)
            print(f'Selesai: {sum(map(len, per_tab.values()))} baris username diwarnai oranye di sheet {sid}.')
        except HttpError as e:  # data utama sudah tertulis; warna butuh akses Editor ke sheet sumber
            print(f'GAGAL mewarnai sheet {sid} ({e.resp.status}): jadikan service account Editor di sheet itu. Data tidak terpengaruh.')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='benar-benar menulis ke Google Sheets')
    a = ap.parse_args(argv)
    sheets, drive, email = services(a.apply)
    _, plans, user_plan, warna = siapkan(sheets, drive, email)
    if not a.apply:
        print('\nDRY-RUN: tidak ada yang ditulis. Tambahkan --apply untuk menulis.')
        return
    terapkan(plans, user_plan, sheets, warna)


if __name__ == '__main__':
    main()
