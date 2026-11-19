"""Bank konten per creator: tarik LINK dari tab Raw Content (BW Comm) ke tab brand di Tracker Sample.

Dipakai menu "Bank Konten Creator" di Shopee_BW/app.py. Dua tahap, sama seperti skrip gabung lain:
  siapkan(...)  -> hanya BACA, hasilnya rencana (plan)
  terapkan(...) -> TULIS (hanya dari tombol Terapkan)

Sumber (header baris 1): Username Shopee | BRANDS | Jenis Channel | Link | Tipe, dibaca untuk baris dari-sampai yang dipilih.
Tujuan: tab brand (nama tab = nama brand), header baris 12, data mulai baris 14, username di kolom "Creator Username".
Kolom tujuan dicari lewat NAMA header (letak kolom tiap brand beda, mis. Clear punya kolom PID):
  Short Video / Share Link  x  Mandatory / Competition / Event.
Link yang sudah ada di sel dipertahankan, link baru ditambah di bawahnya tanpa dobel. Sel berisi rumus ditimpa
(isi lamanya dibackup). Live Streaming tidak punya kolom tujuan, jadi dilewati dan dilaporkan.
"""
import difflib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from gabung_konten_bw import norm as link_key

HERE = Path(__file__).resolve().parent
HEADER_ROW, FIRST_ROW = 12, 14
USER_HEAD = 'Creator Username'
SRC = {'user': 'username shopee', 'brand': 'brands', 'channel': 'jenis channel', 'link': 'link', 'tipe': 'tipe'}
CHANNEL = {'short video': 'Short Video', 'share link': 'Share Link'}
TIPE = {'mandatory': 'Mandatory', 'kompetisi': 'Competition', 'competition': 'Competition', 'event': 'Event'}
TARGETS = [f'{c} {t}' for c in ('Short Video', 'Share Link') for t in ('Mandatory', 'Competition', 'Event')]
URL = re.compile(r'https?://.+?(?=https?://|\s|$)')  # lookahead: link yang nempel ke link lain tetap kepisah
SKIP = ('docs.google.com', 'drive.google.com')  # link ke Docs/Drive bukan link konten


def extract_links(*cells):
    seen = {}
    for text in cells:
        for u in URL.findall(text or ''):
            u = u.rstrip('.,;)')
            if not any(d in u for d in SKIP):
                seen[u] = None  # dict = dedupe + urutan tetap
    return list(seen)


def norm(u):
    return re.sub(r'\s+', '', u or '').lstrip('@').lower()


def letter(i):
    s, i = '', i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def gabung(old, new):
    """(isi sel lama, link baru) -> (isi sel baru, jumlah link yang benar-benar ditambah). Rumus dianggap kosong."""
    old = '' if old.startswith('=') else old.rstrip('\n')
    have = {link_key(x) for x in extract_links(old)}
    add = []
    for x in dict.fromkeys(new):
        if link_key(x) not in have:
            have.add(link_key(x))
            add.append(x)
    return (old + '\n' if old and add else old) + '\n'.join(add), len(add)


def curiga(name, others):
    """Alasan username baru terlihat typo ('' = bersih): karakter aneh / nomor HP, atau mirip (>=85%) username lain."""
    close = difflib.get_close_matches(norm(name), [o for o in others if o and o != norm(name)], n=1, cutoff=0.85)
    if not re.fullmatch(r'[A-Za-z0-9._]+', name) or name.isdigit():
        return 'karakter aneh / nomor'
    return f'mirip "{close[0]}"' if close else ''


def get(sheets, sid, rng, **kw):
    return sheets.values().get(spreadsheetId=sid, range=rng, **kw).execute(num_retries=3).get('values', [])


def baca_meta(sheets, sid):
    """(judul spreadsheet, [(nama tab, jumlah baris grid)])."""
    m = sheets.get(spreadsheetId=sid, fields='properties.title,sheets.properties(title,gridProperties.rowCount)').execute(num_retries=3)
    return m['properties']['title'], [(s['properties']['title'], s['properties']['gridProperties']['rowCount']) for s in m['sheets']]


def siapkan(sheets, src_id, src_tab, r1, r2, trk_id):
    """Tahap baca saja. Hasil: SimpleNamespace(brands={tab: info}, skipped=Counter, baca=jumlah baris sumber yang dibaca)."""
    head = [h.strip().lower() for h in (get(sheets, src_id, f"'{src_tab}'!A1:Z1") or [[]])[0]]
    miss = [v for v in SRC.values() if v not in head]
    if miss:
        raise ValueError(f'Header baris 1 tab "{src_tab}" tidak punya kolom: {", ".join(miss)}')
    col = {k: head.index(v) for k, v in SRC.items()}
    rows = get(sheets, src_id, f"'{src_tab}'!A{r1}:Z{r2}")
    print(f'Sumber "{src_tab}" baris {r1}-{r2}: {len(rows)} baris terbaca.')
    tab_of = {t.lower(): t for t, _ in baca_meta(sheets, trk_id)[1]}

    skipped, display, per = Counter(), {}, {}
    for r in rows:
        g = lambda k: r[col[k]].strip() if col[k] < len(r) else ''  # noqa: E731
        user, links = g('user'), extract_links(g('link'))
        if not (user and links):
            continue
        tab, ch, tp = tab_of.get(g('brand').lower()), CHANNEL.get(g('channel').lower()), TIPE.get(g('tipe').lower())
        if not tab:
            skipped[f'brand "{g("brand")}" tidak punya tab di tujuan'] += 1
        elif not ch:
            skipped[f'channel "{g("channel")}" tidak punya kolom tujuan'] += 1
        elif not tp:
            skipped[f'tipe "{g("tipe")}" tidak dikenal'] += 1
        else:
            display.setdefault(norm(user), user.lstrip('@'))
            per.setdefault(tab, {}).setdefault(f'{ch} {tp}', {}).setdefault(norm(user), []).extend(links)

    brands = {}
    for tab, by_target in per.items():
        head = [h.strip() for h in (get(sheets, trk_id, f"'{tab}'!A{HEADER_ROW}:AZ{HEADER_ROW}") or [[]])[0]]
        gone = [h for h in [USER_HEAD, *TARGETS] if h not in head]
        if gone:
            brands[tab] = {'error': f'header baris {HEADER_ROW} tidak punya kolom: {", ".join(gone)}'}
            continue
        cols = {h: letter(head.index(h)) for h in [USER_HEAD, *TARGETS]}
        order = [norm(x[0]) if x else '' for x in get(sheets, trk_id, f"'{tab}'!{cols[USER_HEAD]}{FIRST_ROW}:{cols[USER_HEAD]}")]
        last = FIRST_ROW + len(order) - 1
        old = {t: get(sheets, trk_id, f"'{tab}'!{cols[t]}{FIRST_ROW}:{cols[t]}{last}", valueRenderOption='FORMULA')
               for t in TARGETS} if order else {t: [] for t in TARGETS}
        cell = lambda t, i: (old[t][i][0] if i < len(old[t]) and old[t][i] else '')  # noqa: E731
        cells, added, formulas, seen = [], Counter(), 0, set()
        for i, u in enumerate(order):
            if not u or u in seen:
                continue  # username dobel di tracker: hanya baris pertama yang diisi
            seen.add(u)
            for t in TARGETS:
                if u in by_target.get(t, {}):
                    text, k = gabung(cell(t, i), by_target[t][u])
                    if k:
                        cells.append((FIRST_ROW + i, t, text))
                        added[t] += k
                        formulas += cell(t, i).startswith('=')
        known = set(order)
        new_users = list(dict.fromkeys(u for d in by_target.values() for u in d if u not in known))
        new = []
        for u in new_users:
            texts = {t: gabung('', by_target[t][u]) for t in TARGETS if u in by_target.get(t, {})}
            for t, (_, k) in texts.items():
                added[t] += k
            new.append({'user': u, 'nama': display[u], 'curiga': curiga(display[u], list(known) + [x for x in new_users if x != u]),
                        'links': {t: text for t, (text, _) in texts.items()}})
        brands[tab] = {'cols': cols, 'n_old': len(order), 'cells': cells, 'added': added, 'formulas': formulas, 'new': new,
                       'backup': {t: old[t] for t in TARGETS}}
        print(f'  {tab}: {sum(added.values())} link baru ({len(cells)} sel), {len(new)} username baru, {formulas} sel berisi rumus akan ditimpa')
    for why, c in skipped.items():
        print(f'  dilewati {c} baris: {why}')
    return SimpleNamespace(trk=trk_id, brands=brands, skipped=skipped, baca=len(rows))


def pulihkan_format(sheets, trk_id, tab, cols, last):
    """Menulis teks ke sel menghapus number format-nya. Kembalikan ke format yang paling umum di kolom itu; cuma numberFormat disentuh."""
    meta = sheets.get(spreadsheetId=trk_id, ranges=[f"'{tab}'!{c}{FIRST_ROW}:{c}{last}" for c in cols],
                      fields='sheets(properties.sheetId,data(startColumn,rowData.values(userEnteredFormat.numberFormat,userEnteredValue)))').execute()
    sheet, reqs = meta['sheets'][0], []
    fmt = lambda v: v.get('userEnteredFormat', {}).get('numberFormat')  # noqa: E731
    for d in sheet['data']:
        cells = [(r.get('values') or [{}])[0] for r in d.get('rowData', [])]
        common = Counter(json.dumps(fmt(v), sort_keys=True) for v in cells if fmt(v)).most_common(1)
        if not common:
            continue
        tpl, c0 = json.loads(common[0][0]), d.get('startColumn', 0)
        for i, v in enumerate(cells):
            if v.get('userEnteredValue') and not fmt(v):
                reqs.append({'updateCells': {'range': {'sheetId': sheet['properties']['sheetId'], 'startRowIndex': FIRST_ROW - 1 + i,
                                                       'endRowIndex': FIRST_ROW + i, 'startColumnIndex': c0, 'endColumnIndex': c0 + 1},
                                             'rows': [{'values': [{'userEnteredFormat': {'numberFormat': tpl}}]}],
                                             'fields': 'userEnteredFormat.numberFormat'}})
    for i in range(0, len(reqs), 200):
        sheets.batchUpdate(spreadsheetId=trk_id, body={'requests': reqs[i:i + 200]}).execute(num_retries=3)
    return len(reqs)


def terapkan(p, sheets, tambah):
    """Tahap tulis. tambah = {tab: set username (norm) baru yang boleh ditambahkan}. Backup isi lama dulu."""
    backup = {tab: b['backup'] for tab, b in p.brands.items() if 'backup' in b}
    path = HERE / f'backup_bank_konten_{datetime.now():%Y%m%d_%H%M%S}.json'
    path.write_text(json.dumps(backup, ensure_ascii=False), encoding='utf-8')
    print(f'Backup isi lama kolom link: {path}')
    for tab, b in p.brands.items():
        if 'error' in b:
            print(f'{tab}: dilewati, {b["error"]}')
            continue
        add = [u for u in b['new'] if u['user'] in tambah.get(tab, ())]
        a0 = FIRST_ROW + b['n_old']
        data = [{'range': f"'{tab}'!{b['cols'][t]}{row}", 'values': [[text]]} for row, t, text in b['cells']]
        for k, u in enumerate(add):
            data.append({'range': f"'{tab}'!{b['cols'][USER_HEAD]}{a0 + k}", 'values': [[u['nama']]]})
            data += [{'range': f"'{tab}'!{b['cols'][t]}{a0 + k}", 'values': [[text]]} for t, text in u['links'].items()]
        rows = [row for row, _, _ in b['cells']]
        print(f'Menulis tab "{tab}": {len(b["cells"])} sel link' + (f' (baris {min(rows)}-{max(rows)})' if rows else '') +
              (f', {len(add)} username baru + linknya (baris {a0}-{a0 + len(add) - 1})' if add else '') + ' ...')
        for i in range(0, len(data), 200):
            print(f'  kirim batch {i // 200 + 1}/{(len(data) + 199) // 200} ({min(i + 200, len(data))}/{len(data)} sel) ...')
            sheets.values().batchUpdate(spreadsheetId=p.trk, body={'valueInputOption': 'RAW', 'data': data[i:i + 200]}).execute(num_retries=3)
        if data:
            fixed = pulihkan_format(sheets, p.trk, tab, list(b['cols'][t] for t in TARGETS), a0 + len(add) - 1 if add else a0 + b['n_old'] - 1)
            print(f'  Selesai {tab}: {len(data)} sel ditulis, {fixed} sel dipulihkan number format-nya.')


def demo():
    t = "1.https://www.threads.com/@a/post/X1?xmt=AQ\nLink komplit ada di https://docs.google.com/document/d/14A63/edit"
    assert extract_links(t) == ['https://www.threads.com/@a/post/X1?xmt=AQ']
    assert extract_links('https://a.co/1https://a.co/2.') == ['https://a.co/1', 'https://a.co/2']
    assert norm(' @Yupi2023 \n') == 'yupi2023' and letter(29) == 'AD' and letter(1) == 'B'
    assert gabung('', ['https://id.shp.ee/a', 'https://id.shp.ee/a']) == ('https://id.shp.ee/a', 1)
    assert gabung('https://id.shp.ee/a', ['https://id.shp.ee/a?smtt=1', 'https://id.shp.ee/b']) == ('https://id.shp.ee/a\nhttps://id.shp.ee/b', 1)
    assert gabung('=SUMIF(A:A,B1,C:C)', ['https://x.co/1']) == ('https://x.co/1', 1)
    assert gabung('catatan 1\n', ['https://x.co/1']) == ('catatan 1\nhttps://x.co/1', 1)
    assert gabung('https://x.co/1', ['https://x.co/1']) == ('https://x.co/1', 0)
    assert curiga('0812345678', []) and curiga('sarah_lia', ['sarah_lia1']) and not curiga('budi', ['siti'])


if __name__ == '__main__':
    demo()
    print('LULUS')
