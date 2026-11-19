"""python test_app.py -> diam kalau lulus. Cuma menguji tampilan dan tahap "Cek dulu" (baca saja, tidak menulis ke sheet)."""
import io
import os
from contextlib import redirect_stdout

os.environ['SHOPEE_BW_LOKAL'] = '1'
from streamlit.testing.v1 import AppTest  # noqa: E402

import gabung_event_bw as ev  # noqa: E402
import gabung_konten_bw as kt  # noqa: E402

at = AppTest.from_file('app.py', default_timeout=600).run()
assert not at.exception, at.exception
for page in ('konten', 'event', 'bank', 'gmv'):
    at.session_state.page = page
    at.run()
    assert not at.exception, (page, at.exception)

# Mandatory + Kompetisi: tanpa link sheet -> belum ada tombol; dengan link: bulan tanpa tab sumber -> Cek nonaktif, Nov -> aktif
at.session_state.page = 'konten'
at.run()
assert not [b for b in at.button if b.key == 'cek_konten']
at.text_input(key='kt_src').set_value('https://docs.google.com/spreadsheets/d/' + kt.SHEET_ID + '/edit')
at.text_input(key='kt_dst').set_value('https://docs.google.com/spreadsheets/d/' + kt.RAW_SHEET_ID + '/edit').run()
at.selectbox[0].set_value('Des').run()
assert at.button(key='cek_konten').disabled
at.selectbox[0].set_value('Nov').run()
assert not at.exception, at.exception
assert not at.button(key='cek_konten').disabled

# Event: tanpa daftar dan tanpa link tujuan, tombol Cek nonaktif (tidak ada daftar bawaan / tersimpan lagi)
at.session_state.page = 'event'
at.run()
assert not at.exception, at.exception
assert at.button(key='cek_event').disabled

# tahap baca nyata, satu tab / satu sumber saja
sheets, drive, email = kt.services(False)
a = kt.buat_parser().parse_args(['--bulan', 'Nov', '--target', 'RAW Nov', '--ke-raw-content'])
a.tabs_pilih = [('Form Clear NOV', None)]
with redirect_stdout(io.StringIO()):
    p = kt.siapkan(a, sheets, drive, email)
assert p.info and p.info[0][0] == 'Form Clear NOV' and p.info[0][4] > 0, p.info

one = [e for e in ev.EVENTS if e[1] == 'SoW Hari-H' and e[4] == 'Clear']
with redirect_stdout(io.StringIO()):
    rows, plans, user_plan, warna = ev.siapkan(sheets, drive, email, one)
assert rows and all(r[3] == 'Clear' for r in rows)
buf = io.StringIO()
with redirect_stdout(buf):
    ev.siapkan(sheets, drive, email, [('1' * 44, 'Tidak Ada', 'A:B', 'A', 'Clear', 1)])
assert 'GAGAL' in buf.getvalue()  # sheet yang tidak bisa dibaca dilaporkan, proses tidak berhenti
print('LULUS')
