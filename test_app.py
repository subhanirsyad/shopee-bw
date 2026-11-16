"""python test_app.py -> diam kalau lulus. Cuma menguji tampilan dan tombol 'Cek dulu' (baca saja, tidak menulis)."""
import os

os.environ['SHOPEE_BW_LOKAL'] = '1'
from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file('app.py', default_timeout=600).run()
assert not at.exception, at.exception
for page in ('konten', 'event', 'gmv'):
    at.session_state.page = page
    at.run()
    assert not at.exception, (page, at.exception)

# Mandatory + Kompetisi: satu tab kecil, tanpa bulan lain, tombol "Cek dulu"
at.session_state.page = 'konten'
at.run()
for w in at.text_input:
    if w.label.startswith('Ikut baca bulan lain'):
        w.set_value('')
    if w.label.startswith('Pakai tab ini saja'):
        w.set_value('Form Clear NOV')
at.button(key='cek_konten').click().run()
assert not at.exception, at.exception
assert not at.error, [e.value for e in at.error]
labels = [m.label for m in at.metric]
assert 'Link terbaca' in labels, labels
print('LULUS', [(m.label, m.value) for m in at.metric])
