"""python test_gabung_konten_bw.py -> diam kalau lulus."""
import io

import openpyxl

from gabung_konten_bw import (FileError, extract_urls, key, links_from_html, links_from_xlsx, new_rows, pick_tabs,
                              rows_from_tab)

# link nempel, salah ketik ttps, kurung, tanda baca
assert extract_urls('1. https://id.shp.ee/aa?x=1 (ttps://s.shopee.co.id/7A)\n47. https://t.co/a/ 48. https://t.co/b/.'
                    'https://id.shp.ee/cc') == ['https://id.shp.ee/aa?x=1', 'https://s.shopee.co.id/7A',
                                                'https://t.co/a/', 'https://t.co/b/', 'https://id.shp.ee/cc']

# export Docs: href redirect google dibuka, CSS di head dibuang
doc = ('<html><head><style>@import url(https://fonts.x/css)</style></head><body><p>'
       '<a href="https://www.google.com/url?q=https://www.threads.com/share/AB/&amp;sa=D">1</a> '
       'https://id.shp.ee/zz?fromSource=a&amp;smtt=0</p></body></html>')
assert [u for u, _ in links_from_html(doc)] == ['https://www.threads.com/share/AB/',
                                                 'https://id.shp.ee/zz?fromSource=a&smtt=0']

# xlsx peserta: hint dari judul kolom
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['SHOPEE VIDEO', 'THREADS'])
ws.append(['1. https://id.shp.ee/v1', '1. https://www.threads.com/share/t1/'])
buf = io.BytesIO()
wb.save(buf)
assert links_from_xlsx(buf.getvalue()) == [('https://id.shp.ee/v1', 'Short Video'),
                                           ('https://www.threads.com/share/t1/', 'Threads')]


def fetch(fid):
    if fid == 'LOCKED' * 4:
        raise FileError('Docs/Sheet tidak bisa dibuka: akses ditolak')
    return 'Dove', [('https://id.shp.ee/v1', 'Short Video'), ('https://www.threads.com/share/t1/', 'Threads'),
                    ('https://s.shopee.co.id/prod', None)]


comp = [['Timestamp', 'Username Shopee', 'Link Akun Shopee', 'Produk apa?', 'Link Kumpulan Shopee Video',
         'Masukan 3 Link Shopee Video terbaik', 'Link Kumpulan Threads', 'Username Shopee'],
        ['31/10/2026', 'debo', 'https://id.shp.ee/akun', 'Dove Biotin',
         'https://id.shp.ee/a1?fromSource=x\nhttps://id.shp.ee/a2 (https://s.shopee.co.id/p)',
         'https://id.shp.ee/a1?fromSource=y',
         'https://www.threads.com/share/t9/ https://docs.google.com/spreadsheets/d/' + 'F' * 25 + '/edit '
         'https://docs.google.com/document/d/' + 'LOCKED' * 4 + '/edit']]
rows = list(rows_from_tab('Dove Competition OCT', comp, fetch))
out = new_rows(rows, [])
assert [(r[3], r[4], r[5], r[6]) for r in out] == [
    ('Dove', 'Short Video', 'https://id.shp.ee/a1?fromSource=x', 'Kompetisi'),
    ('Dove', 'Short Video', 'https://id.shp.ee/a2', 'Kompetisi'),
    ('Dove', 'Share Link', 'https://www.threads.com/share/t9/', 'Kompetisi'),
    ('Dove', 'Short Video', 'https://id.shp.ee/v1', 'Kompetisi'),
    ('Dove', 'Share Link', 'https://www.threads.com/share/t1/', 'Kompetisi'),
    ('Dove', 'Share Link', 'https://docs.google.com/document/d/' + 'LOCKED' * 4 + '/edit', 'Kompetisi')], out
assert out[3][8] == 'dari file "Dove"' and out[5][8] == 'Docs/Sheet tidak bisa dibuka: akses ditolak'

# RAW: Jenis Channel menentukan; s.shopee di kolom Share Link tetap dihitung
raw = [['Timestamp', 'Username Shopee', 'Produk Sample yang diterima?', 'BRANDS', 'Jenis Channel', 'Link', 'Tipe'],
       ['01/11/2026', 'niqi', 'Ponds Age', 'Ponds', 'Share Link', 'https://s.shopee.co.id/50a', 'Mandatory']]
assert [r[4] for r in rows_from_tab('RAW Nov', raw, fetch)] == ['Share Link']

# minggu depan: yang sudah ada di tab tujuan tidak masuk lagi
existing = [key(r) for r in out[:4]]
assert new_rows(rows, existing) == out[4:]
assert key(['', '@Debo ', '', '', '', 'https://id.shp.ee/a1?z', 'Kompetisi']) == key(out[0])

assert pick_tabs(['RAW Nov', 'RAW Threads OCT', 'Dove Competition OCT', 'Form Dove OCT', 'Form Paid Share Link - Sept',
                  'Data penerima paid share link', 'Vaseline PDRN', 'GABUNGAN OCT', 'RAW OCT'], 'OCT') == \
    ['RAW Threads OCT', 'Dove Competition OCT', 'Form Dove OCT', 'RAW OCT']  # RAW bulan itu = tujuan sekaligus sumber

# judul file peserta menyebut brand lain -> ditandai
from gabung_konten_bw import other_brand  # noqa: E402
assert other_brand('Clear', 'Dove') == 'Clear'
assert other_brand('Dove Oktober', 'Dove') == '' and other_brand('Link Threads', 'Dove') == ''
assert other_brand('Glow n lovely Oktober ', 'GAL') == '' and other_brand('Tresemme ', 'TRESemme') == ''

# ---- event
from gabung_event_bw import ddmm, produk_of, rows_from_event  # noqa: E402
from gabung_konten_bw import channel_of  # noqa: E402
assert ddmm('11/15/2026 10:13:02') == '15/11/2026 10:13:02' and ddmm('11/8/2026 9:52:55') == '08/11/2026 09:52:55'
assert produk_of('Link Shopee Video + Keranjang Oren Vaseline Proderma Moisturizer (SV 1)') == 'Vaseline Proderma Moisturizer'
assert produk_of('Link IG STORY + Taplink (Vaseline PDRN) 1') == 'Vaseline PDRN'
assert produk_of('Link Shopee Video + Keranjang Oren (SV 1)') == '' and produk_of('Link Report Threads') == ''
assert channel_of('https://www.instagram.com/reel/DfePKiWhv_8/?srtk=c3', None) == 'Share Link'  # Reels/IG/Threads = Share Link (istilah sheet)
assert channel_of('https://www.threads.com/@kiki?igshid=N', 'Threads') is None  # profil, bukan konten
ev = [['Timestamp', 'Kamu platform?', 'Username Tiktok', 'Username Shopee', 'Link Report Threads', 'Link Report Threads'],
      ['11/15/2026 9:20:07', 'Shopee', '', 'kiky', 'https://www.threads.com/@kiky', 'https://s.shopee.co.id/AK'],
      ['11/15/2026 9:30:00', 'Shopee', '', 'budi', 'https://www.threads.com/share/BAU/', '-']]
assert [r[:7] for r in rows_from_event(ev, 'E:F', 'D', 'Vaseline', 1, 'Gathering / THREADS', fetch)] == \
    [['15/11/2026 09:30:00', 'budi', '', 'Vaseline', 'Share Link', 'https://www.threads.com/share/BAU/', 'Event']]

# tab OCT yang masih terisi bulan November: hanya baris November
from gabung_konten_bw import month_no, only_month  # noqa: E402
assert month_no('Nov') == 11 and month_no('OCT') == 10 and month_no('xyz') is None
assert only_month([['Timestamp', 'u'], ['31/10/2026 23:59:00', 'a'], ['01/11/2026 00:10:00', 'b'], ['', 'c'], ['2/11/2026', 'd']], 11) == \
    [['Timestamp', 'u'], [], ['01/11/2026 00:10:00', 'b'], [], ['2/11/2026', 'd']]  # posisi baris tetap

# tab Paid: brand per kolom (Share Link) / dari judul (TRES), Tipe tetap Mandatory, nomor baris sumber ikut
from gabung_konten_bw import brand_in, rows_done  # noqa: E402
assert brand_in('Form Paid TRES Silk Press - Sept') == 'TRESemme' and brand_in('Masukan link (Share link) - Glow & Lovely') == 'GAL'
assert brand_in('Link Short Video + Keranjang Oren (SV 1)') == '' and brand_in('Form Paid Share Link - Sept') == ''
paid = [['Timestamp', 'Username Shopee', 'Masukan link (Share link) - Vaseline', 'Masukan link (Share link) - Ponds', 'SL Vaseline'],
        ['21/09/2026', 'inna', 'https://www.threads.com/share/AA/', 'https://www.threads.com/share/BB/', '1'],
        ['22/09/2026', 'vita', '-', '-', '0']]
pr = list(rows_from_tab('Form Paid Share Link - Sept', paid, fetch))
assert [(r[3], r[4], r[6], r[9]) for r in pr] == [('Vaseline', 'Share Link', 'Mandatory', 2), ('Ponds', 'Share Link', 'Mandatory', 2)], pr
tres = [['Timestamp', 'Username Shopee', 'Link Short Video + Keranjang Oren (SV 1)'], ['17/09/2026', 'ry', 'https://id.shp.ee/j1']]
assert [(r[3], r[4], r[6]) for r in rows_from_tab('Form Paid TRES Silk Press - Sept', tres, fetch)] == [('TRESemme', 'Short Video', 'Mandatory')]
assert pick_tabs(['Form Paid Share Link - Sept', 'Form Paid TRES Silk Press - Sept', 'Data penerima paid share link'], 'Sept') ==     ['Form Paid Share Link - Sept', 'Form Paid TRES Silk Press - Sept']

# penanda oranye: baris sumber diwarnai hanya kalau SEMUA link-nya sudah ada di tujuan
rr = [['', 'a', '', 'D', 'Short Video', 'https://id.shp.ee/1', 'Mandatory', 'Form Dove NOV', '', 2],
      ['', 'a', '', 'D', 'Short Video', 'https://id.shp.ee/2', 'Mandatory', 'Form Dove NOV', '', 2],
      ['', 'b', '', 'D', 'Short Video', 'https://id.shp.ee/3', 'Mandatory', 'Form Dove NOV', '', 3],
      ['', 'c', '', 'D', 'Short Video', 'https://id.shp.ee/4', 'Mandatory', 'RAW Nov', '', 5]]
ok = {key(rr[0]), key(rr[1]), key(rr[3])}
assert rows_done(rr, lambda k: k in ok, 'RAW Nov') == {'Form Dove NOV': [2]}
assert rows_done(rr, lambda k: k in ok - {key(rr[1])}, 'RAW Nov') == {'Form Dove NOV': []}

# cek username baris baru ke tab brand
from gabung_konten_bw import missing_users  # noqa: E402
r1 = ['', ' @Niqi ', '', 'GAL', 'Short Video', 'https://id.shp.ee/1', 'Mandatory']
r2 = ['', 'baru', '', 'GAL', 'Short Video', 'https://id.shp.ee/2', 'Mandatory']
r3 = ['', 'baru', '', 'GAL', 'Share Link', 'https://id.shp.ee/3', 'Mandatory']
assert missing_users([r1, r2, r3], {'GAL': {'niqi'}}) == {'GAL': {'baru': 2}}

# username baru: rumus baris 16 disalin ke baris n, batas $9742 dibuka
from gabung_konten_bw import fill_row  # noqa: E402
tpl = ["=COUNTIFS('Raw Content November'!$D$2:$D$9742,\"GAL\",'Raw Content November'!$I$2:$I$9742,TRIM($B16))", '=AX16+AO16+W16+N16', 'x', '']
assert fill_row(tpl, 1679) == ["=COUNTIFS('Raw Content November'!$D$2:$D,\"GAL\",'Raw Content November'!$I$2:$I,TRIM($B1679))",
                               '=AX1679+AO1679+W1679+N1679', 'x', '']
assert fill_row(['=A160+B116+C16'], 20) == ['=A160+B116+C20']  # angka yang cuma berakhiran 16 tidak ikut berubah

# daftar event yang bisa diubah dari Streamlit
from gabung_event_bw import EVENTS, events_dari, letters, seed_daftar, sheet_id_dari  # noqa: E402
assert sheet_id_dari('https://docs.google.com/spreadsheets/d/1Qnhfd7ZGLau377z_e5oTLgRvCPFHhOBDbUsOyCdhwiA/edit?gid=0#gid=0') == '1Qnhfd7ZGLau377z_e5oTLgRvCPFHhOBDbUsOyCdhwiA'
assert sheet_id_dari(' 1Qnhfd7ZGLau377z_e5oTLgRvCPFHhOBDbUsOyCdhwiA ') == '1Qnhfd7ZGLau377z_e5oTLgRvCPFHhOBDbUsOyCdhwiA' and sheet_id_dari('abc') == ''
assert [letters(i) for i in (0, 25, 26, 27, 51, 52)] == ['A', 'Z', 'AA', 'AB', 'AZ', 'BA']
assert events_dari(seed_daftar()) == [tuple(e) for e in EVENTS]  # daftar bawaan = EVENTS
d = seed_daftar()
d[0]['Aktif'] = False
assert events_dari(d) == [tuple(e) for e in EVENTS[1:]]
