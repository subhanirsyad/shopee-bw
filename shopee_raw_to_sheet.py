#!/usr/bin/env python3
"""
Shopee BW  ->  Google Sheet (Raw tab + auto-add creator ke tab Per-Brand)

Yang dikerjakan script ini:
  1. Baca CSV raw Shopee affiliate.
  2. Kamu pilih Order Status & Verified Status mana yang dimasukkan (prompt / argumen CLI).
  3. Isi kolom: Date, WEEK (range bisa kamu atur), BRANDS (aturan sama dengan rumus kamu),
     Cek name (rumus VLOOKUP ke tab 'Username WEI'), CHANNEL (LIVE STREAMING / SHORT VIDEO / SHARELINK).
  4. Tulis ke tab Raw (default 'Raw Nov (1-15)').
  5. Untuk tiap brand: username di Raw yang Cek name-nya BUKAN #N/A (sudah ada di Username WEI)
     tapi belum ada di tab brand tsb -> otomatis ditambahkan ke kolom B (Username) tab brand,
     lengkap dengan rumus GMV/SOW yang disalin dari baris terakhir.
  6. Cetak rekonsiliasi per brand (GMV Raw vs GMV creator yang ada di tab brand).

Contoh pakai:
  # simulasi dulu (tidak menulis apa-apa ke sheet)
  python shopee_raw_to_sheet.py raw.csv --dry-run

  # jalankan beneran, pilih status & week sendiri
  python shopee_raw_to_sheet.py raw.csv \
      --status Completed,Pending --verified Valid \
      --weeks "1-7,8-14,15-21,22-30"

  # tanpa argumen --status/--verified/--weeks => script akan menanyakan secara interaktif

Auth (pilih salah satu):
  --service-account key.json   (sheet harus di-share ke email service account sebagai Editor)
  atau tanpa argumen => login OAuth Google lewat browser (gspread.oauth, butuh credentials.json OAuth client)

Install:  pip install pandas gspread
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# ============================== KONFIGURASI ==============================
SPREADSHEET_ID = "1vqus61NmM0WYoe3ukQIbGfAEr_wf_PrknLBPxQNuYQ0"
RAW_TAB = "Raw Nov (1-15)"         # tab tujuan raw (bisa diganti lewat --raw-tab)
WEI_TAB = "Username WEI"
BRAND_TABS = ["GAL", "PONDS", "VASELINE", "CLEAR", "DOVE", "SUNSILK", "TRESEMME"]

# Layout tab brand (dari sheet kamu): header di baris 15, data mulai baris 16
BRAND_FIRST_ROW = 16
COL_NAMA = 1        # A  Nama Lengkap
COL_USERNAME = 2    # B  Username
COL_NOTES = 13      # M  Notes
NOTES_TEXT = "AUTO ADD (Raw Shopee)"

# Urutan kolom di tab Raw (A..P) -> sesuai header sheet kamu
RAW_HEADERS = [
    "Order id", "Order Status", "Verified Status", "Order Time", "Date", "WEEK",
    "Item id", "Item Name", "BRANDS", "Qty", "Affiliate Name", "Cek name",
    "Affiliate Username", "Purchase Value(Rp)", "Channel", "CHANNEL",
]

# Aturan BRANDS: sama persis dengan rumus IF(SEARCH(...)) kamu, urutan prioritas sama.
# Dicari di kolom "Item Name".
BRAND_RULES = [
    ("GAL", ["GAL", "GLOW & LOVELY"]),
    ("PONDS", ["PONDS", "POND'S", "POND’S"]),
    ("VASELINE", ["VASELINE"]),
    ("CLEAR", ["CLEAR"]),
    ("DOVE", ["DOVE"]),
    ("SUNSILK", ["SUNSILK"]),
    ("TRESEMME", ["TRESE"]),
]
UNKNOWN_BRAND = "Tidak Diketahui"


# =========================================================================


# ----------------------------- LOGIKA MURNI ------------------------------
def detect_brand(item_name) -> str:
    text = str(item_name).upper()
    for brand, keys in BRAND_RULES:
        if any(k in text for k in keys):
            return brand
    return UNKNOWN_BRAND


def map_channel(ch) -> str:
    c = str(ch).strip().lower()
    if c.startswith("shopeelive"):
        return "LIVE STREAMING"
    if c.startswith("shopeevideo"):
        return "SHORT VIDEO"
    return "SHARELINK"


def parse_weeks(spec: str):
    """'1-7,8-14,15-21,22-30' -> [('W1',1,7),('W2',8,14),...]"""
    out = []
    for i, part in enumerate([p.strip() for p in spec.split(",") if p.strip()], start=1):
        m = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", part)
        if not m:
            raise ValueError(f"Format week salah: '{part}'. Contoh benar: 1-7,8-14,15-21,22-30")
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            raise ValueError(f"Range week terbalik: '{part}'")
        out.append((f"W{i}", lo, hi))
    return out


def assign_week(day: int, weeks) -> str:
    for label, lo, hi in weeks:
        if lo <= day <= hi:
            return label
    return "OUT OF RANGE"


def norm_user(x) -> str:
    """Sama dengan user_key di gabung_konten_bw: tanpa @, spasi/enter, huruf kecil (supaya tidak dobel di tab brand)."""
    return re.sub(r"\s+", "", str(x)).lstrip("@").lower()


def build_raw_frame(df: pd.DataFrame, statuses, verified, weeks) -> pd.DataFrame:
    """Filter + hitung kolom turunan. Mengembalikan DataFrame dengan kolom RAW_HEADERS
    (kolom 'Cek name' diisi nanti sebagai rumus; di sini hanya disiapkan kolom bantu)."""
    d = df.copy()
    if statuses is not None:
        d = d[d["Order Status"].isin(statuses)]
    if verified is not None:
        d = d[d["Verified Status"].isin(verified)]
    d = d.reset_index(drop=True)

    dt = pd.to_datetime(d["Order Time"], errors="coerce")
    d["Date"] = dt.dt.strftime("%Y-%m-%d")
    d["WEEK"] = dt.dt.day.map(lambda x: assign_week(int(x), weeks) if pd.notna(x) else "")
    d["BRANDS"] = d["Item Name"].map(detect_brand)
    d["CHANNEL"] = d["Channel"].map(map_channel)
    d["_user"] = d["Affiliate Username"].map(norm_user)
    return d


def plan_new_creators(d: pd.DataFrame, wei_users: set, tab_users: dict) -> dict:
    """Per brand: creator di Raw yang Cek name-nya ketemu (bukan #N/A) tapi belum ada di tab brand.
    Return {brand: DataFrame[username, nama]}."""
    plan = {}
    found = d[d["_user"].isin(wei_users)]
    for brand in BRAND_TABS:
        sub = found[found["BRANDS"] == brand]
        first = sub.drop_duplicates("_user")
        missing = first[~first["_user"].isin(tab_users.get(brand, set()))]
        plan[brand] = pd.DataFrame({
            "username": missing["Affiliate Username"].astype(str).str.strip().values,
            "nama": missing["Affiliate Name"].fillna("").astype(str).values,
        })
    return plan


def reconcile(d: pd.DataFrame, wei_users: set, tab_users: dict, plan: dict):
    """Bandingkan GMV Raw (creator yang dikenal WEI) vs GMV creator yang akan ada di tab brand."""
    rows = []
    for brand in BRAND_TABS:
        sub = d[(d["BRANDS"] == brand) & (d["_user"].isin(wei_users))]
        final = set(tab_users.get(brand, set())) | {norm_user(u) for u in plan[brand]["username"]}
        covered = sub[sub["_user"].isin(final)]
        rows.append({
            "brand": brand,
            "creator_raw(known)": sub["_user"].nunique(),
            "creator_tab_sebelum": len(tab_users.get(brand, set())),
            "ditambah": len(plan[brand]),
            "GMV_raw(known)": float(sub["Purchase Value(Rp)"].sum()),
            "GMV_tercover_tab": float(covered["Purchase Value(Rp)"].sum()),
        })
    r = pd.DataFrame(rows)
    r["selisih"] = r["GMV_raw(known)"] - r["GMV_tercover_tab"]
    return r


# ------------------------------ INTERAKTIF -------------------------------
def pick_file() -> str:
    """Buka jendela pilih file (tkinter, bawaan Python)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askopenfilename(
            title="Pilih file raw Shopee (CSV / Excel)",
            filetypes=[("Raw Shopee", "*.csv *.xlsx *.xls"), ("Semua file", "*.*")],
        )
        root.destroy()
    except Exception:
        p = input("Path file raw (.csv/.xlsx): ").strip().strip('"')
    if not p:
        sys.exit("Tidak ada file dipilih.")
    return p


def ask_weeks():
    """Tanya range tanggal tiap week satu per satu. Enter kosong = selesai."""
    print("\nAtur week. Isi tanggal mulai-sampai, contoh: 1-10 (artinya tgl 1 sampai 10). Enter kosong = selesai.")
    parts = []
    while True:
        ans = input(f"  W{len(parts) + 1} tanggal berapa sampai berapa? ").strip()
        if not ans:
            if parts:
                break
            print("  Minimal isi W1.")
            continue
        ans = re.sub(r"\s*(?:sampai|s/d|sd|to|[-–—\s])\s*", "-", ans, count=1)
        try:
            parse_weeks(ans)
        except ValueError as e:
            print("  ", e)
            continue
        parts.append(ans)
    return parse_weeks(",".join(parts))


def choose(series: pd.Series, label: str, preset):
    counts = series.value_counts()
    if preset:
        if preset.strip().lower() == "all":
            return None
        vals = [v.strip() for v in preset.split(",") if v.strip()]
        bad = [v for v in vals if v not in counts.index]
        if bad:
            sys.exit(f"{label}: nilai {bad} tidak ada di CSV. Pilihan: {list(counts.index)}")
        return vals
    print(f"\n{label} di CSV:")
    opts = list(counts.index)
    for i, v in enumerate(opts, 1):
        print(f"  {i}. {v:<16} {counts[v]:>7,} baris")
    ans = input(f"Pilih nomor {label} yang dimasukkan, pisahkan koma (Enter = semua): ").strip()
    if not ans:
        return None
    return [opts[int(x) - 1] for x in ans.split(",")]


# ------------------------------ GOOGLE SHEETS ----------------------------
def connect(args):
    import gspread
    if args.service_account:
        gc = gspread.service_account(filename=args.service_account)
    else:
        # OAuth: pakai credentials.json yang ada di folder yang sama dengan script ini.
        # Login pertama membuka browser; token disimpan di authorized_user.json (folder yang sama).
        here = Path(__file__).resolve().parent
        cred = here / "credentials.json"
        if not cred.exists():
            sys.exit(f"credentials.json tidak ditemukan di {here}. Taruh file OAuth client ID kamu di sana "
                     "dengan nama credentials.json.")
        gc = gspread.oauth(credentials_filename=str(cred),
                           authorized_user_filename=str(here / "authorized_user.json"))
    return gc.open_by_key(SPREADSHEET_ID)


def connect_creds(creds):
    """Buka spreadsheet pakai google Credentials service account yang sudah jadi."""
    import gspread
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)


def read_user_col(ws, col: int, start_row: int) -> list:
    vals = ws.col_values(col)
    return [v.strip() for v in vals[start_row - 1:] if str(v).strip()]


def _key_part(x) -> str:
    """Normalisasi nilai supaya data dari CSV & dari sheet bisa dibandingkan."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return ""
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    s = str(x).strip()
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


# kolom yang dipakai untuk mengenali baris yang sudah pernah ditulis (cegah dobel kalau upload file yang sama)
DEDUP_COLS = ["Order id", "Item id", "Affiliate Username", "Qty", "Purchase Value(Rp)"]


def write_raw(sh, tab, d: pd.DataFrame, replace: bool = False):
    ws = sh.worksheet(tab)
    # pastikan header tetap benar
    ws.update(range_name="A1:P1", values=[RAW_HEADERS])

    if replace:
        ws.batch_clear([f"A2:P{max(ws.row_count, 2)}"])
        start_row = 2
    else:
        # TAMBAH di bawah data lama, jangan timpa
        existing = ws.get(f"A2:P{max(ws.row_count, 2)}", value_render_option="UNFORMATTED_VALUE")
        existing = [r for r in existing if any(str(c).strip() for c in r)]
        start_row = len(existing) + 2
        idx = [RAW_HEADERS.index(c) for c in DEDUP_COLS]
        seen = {}
        for r in existing:
            k = tuple(_key_part(r[i]) if i < len(r) else "" for i in idx)
            seen[k] = seen.get(k, 0) + 1
        keep = []
        for r in d[DEDUP_COLS].itertuples(index=False):
            k = tuple(_key_part(v) for v in r)
            if seen.get(k, 0) > 0:
                seen[k] -= 1          # baris ini sudah ada di sheet -> lewati
                keep.append(False)
            else:
                keep.append(True)
        dup = keep.count(False)
        d = d[keep].reset_index(drop=True)
        print(f"  Raw: {len(existing):,} baris lama dipertahankan, {dup:,} baris dobel dilewati, "
              f"{len(d):,} baris baru ditambah mulai baris {start_row}")

    n = len(d)
    if n == 0:
        print("  Raw: tidak ada baris baru.")
        return
    need = start_row + n - 1
    if ws.row_count < need:
        ws.add_rows(need - ws.row_count)

    def num(x):
        return "" if pd.isna(x) else (x.item() if hasattr(x, "item") else x)

    rows = []
    for i, r in enumerate(d.to_dict("records"), start=start_row):
        rows.append([
            r["Order id"], r["Order Status"], r["Verified Status"], r["Order Time"], r["Date"], r["WEEK"],
            num(r["Item id"]), r["Item Name"], r["BRANDS"], num(r["Qty"]), num(r["Affiliate Name"]),
            f"=VLOOKUP(M{i},'{WEI_TAB}'!A:A,1,FALSE)",
            r["Affiliate Username"], num(r["Purchase Value(Rp)"]), r["Channel"], r["CHANNEL"],
        ])
    CH = 5000
    for s in range(0, n, CH):
        chunk = rows[s:s + CH]
        a, b = start_row + s, start_row + s + len(chunk) - 1
        ws.update(range_name=f"A{a}:P{b}", values=chunk, value_input_option="USER_ENTERED")
        print(f"  Raw: tulis baris {a}-{b}")
        time.sleep(1.2)


def _copy_formulas(sh, ws, template: int, dest_rows):
    """Salin semua rumus (GMV, SOW, dst) dari baris template ke baris-baris tujuan."""
    formulas = ws.row_values(template, value_render_option="FORMULA")
    fcols = [i for i, v in enumerate(formulas) if isinstance(v, str) and v.startswith("=")]
    groups, cur = [], []
    for c in fcols:
        if cur and c == cur[-1] + 1:
            cur.append(c)
        else:
            if cur:
                groups.append(cur)
            cur = [c]
    if cur:
        groups.append(cur)
    # gabungkan baris tujuan yang berurutan jadi satu blok
    blocks, rs = [], sorted(dest_rows)
    for r in rs:
        if blocks and r == blocks[-1][1] + 1:
            blocks[-1][1] = r
        else:
            blocks.append([r, r])
    reqs = []
    for lo, hi in blocks:
        for g in groups:
            reqs.append({"copyPaste": {
                "source": {"sheetId": ws.id, "startRowIndex": template - 1, "endRowIndex": template,
                           "startColumnIndex": g[0], "endColumnIndex": g[-1] + 1},
                "destination": {"sheetId": ws.id, "startRowIndex": lo - 1, "endRowIndex": hi,
                                "startColumnIndex": g[0], "endColumnIndex": g[-1] + 1},
                "pasteType": "PASTE_FORMULA",
            }})
    if reqs:
        sh.batch_update({"requests": reqs})
    return len(fcols)


def append_creators(sh, brand: str, new: pd.DataFrame, template: int = None):
    ws = sh.worksheet(brand)
    colb = ws.col_values(COL_USERNAME)
    last = max(len(colb), BRAND_FIRST_ROW - 1)
    start, end = last + 1, last + len(new)
    if end > ws.row_count:
        ws.add_rows(end - ws.row_count + 20)
    if template is None:
        template = last if last >= BRAND_FIRST_ROW else BRAND_FIRST_ROW

    # nama (A) + username (B) dan notes (M)
    ws.update(range_name=f"A{start}:B{end}",
              values=[[n, u] for u, n in zip(new["username"], new["nama"])],
              value_input_option="USER_ENTERED")
    ws.update(range_name=f"{_col(COL_NOTES)}{start}:{_col(COL_NOTES)}{end}",
              values=[[NOTES_TEXT]] * len(new))
    nf = _copy_formulas(sh, ws, template, range(start, end + 1))
    print(f"  {brand}: +{len(new)} creator (baris {start}-{end}), {nf} kolom rumus disalin")


# ------------------------------- TALLY -----------------------------------
TALLY_TAB = "Cek Tally"
BRAND_HEADER_ROW = BRAND_FIRST_ROW - 1   # baris 15
TOTAL_GMV_HEADER = "Total GMV"


def _to_num(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _pad(rows, n):
    return rows + [[]] * (n - len(rows))


def _collect_tally(sh, raw_tab: str, wei: set):
    """Hitung tally. Return (summary df, detail list, info per brand, nama asli dari Raw)."""
    ws = sh.worksheet(raw_tab)
    n = ws.row_count
    col_brand, col_kn = ws.batch_get([f"I2:I{n}", f"K2:N{n}"], value_render_option="UNFORMATTED_VALUE")
    L = max(len(col_brand), len(col_kn))
    col_brand, col_kn = _pad(col_brand, L), _pad(col_kn, L)
    raw = pd.DataFrame({
        "brand": [str(r[0]).strip() if r else "" for r in col_brand],
        "nama": [str(r[0]).strip() if r else "" for r in col_kn],
        "user": [str(r[2]).strip() if len(r) > 2 else "" for r in col_kn],
        "gmv": [_to_num(r[3]) if len(r) > 3 else 0.0 for r in col_kn],
    })
    raw["key"] = raw["user"].map(norm_user)
    raw_all = raw.groupby("brand")["gmv"].sum()
    valid = raw[raw["key"].isin(wei) & raw["brand"].isin(BRAND_TABS)]
    raw_user = valid.groupby(["brand", "key"])["gmv"].sum()
    names = {(r.brand, r.key): (r.user, r.nama)
             for r in valid.drop_duplicates(["brand", "key"]).itertuples(index=False)}

    summary, detail, info = [], [], {}
    for b in BRAND_TABS:
        bws = sh.worksheet(b)
        header = bws.row_values(BRAND_HEADER_ROW)
        pos = [i for i, h in enumerate(header) if str(h).strip().lower() == TOTAL_GMV_HEADER.lower()]
        if not pos:
            print(f"  {b}: kolom '{TOTAL_GMV_HEADER}' tidak ketemu di baris {BRAND_HEADER_ROW}, dilewati")
            continue
        gcol = _col(pos[-1] + 1)
        last = bws.row_count
        users, gmvs = bws.batch_get([f"B{BRAND_FIRST_ROW}:B{last}", f"{gcol}{BRAND_FIRST_ROW}:{gcol}{last}"],
                                    value_render_option="UNFORMATTED_VALUE")
        rows, template = {}, None   # rows: user -> [(no_baris, gmv atau None kalau tanpa rumus)]
        for i, u in enumerate(users):
            if not u or not str(u[0]).strip():
                continue
            cell = gmvs[i][0] if i < len(gmvs) and gmvs[i] else ""
            g = None if str(cell).strip() == "" else _to_num(cell)
            rows.setdefault(norm_user(u[0]), []).append((BRAND_FIRST_ROW + i, g))
            if g is not None:
                template = BRAND_FIRST_ROW + i
        info[b] = {"ws": bws, "rows": rows, "template": template}

        tab = {k: sum(g or 0.0 for _, g in v) for k, v in rows.items()}
        r_b = raw_user[b] if b in raw_user.index.get_level_values(0) else pd.Series(dtype=float)
        raw_total = float(r_b.sum())
        tab_total = sum(tab.values())
        summary.append([b, raw_total, tab_total, raw_total - tab_total, float(raw_all.get(b, 0.0))])

        for u in sorted(set(r_b.index) | {k for k, v in tab.items() if v}):
            rg = float(r_b.get(u, 0.0))
            if u not in rows:
                status = "BELUM MASUK tab brand"
            elif len(rows[u]) > 1:
                status = "DOBEL di tab brand"
            elif rows[u][0][1] is None:
                status = "ada, tapi baris tanpa rumus GMV"
            elif u not in wei:
                status = "ada di tab, tapi #N/A di WEI"
            else:
                status = "ada"
            tg = tab.get(u, 0.0)
            if round(rg - tg) != 0 or status != "ada":
                detail.append([b, u, rg, status, tg, rg - tg])

    s = pd.DataFrame(summary, columns=["Brand", "Raw (Cek valid)", "Tab brand (Total GMV)", "Selisih",
                                       "Raw semua (termasuk #N/A)"])
    return s, detail, info, names


def _print_tally(s, detail) -> bool:
    tot = ["Total"] + [s[c].sum() for c in s.columns[1:]]
    print(pd.concat([s, pd.DataFrame([tot], columns=s.columns)])
          .to_string(index=False, float_format=lambda x: f"{x:,.0f}"))
    ok = all(round(x) == 0 for x in s["Selisih"])
    if ok:
        print("TALLY OK: semua brand cocok.")
    else:
        print("TIDAK TALLY.")
    if detail:
        print(f"{len(detail)} username perlu dicek:")
        dd = pd.DataFrame(detail, columns=["Brand", "Username", "GMV Raw", "Status", "GMV tab", "Selisih"])
        print(dd.to_string(index=False, float_format=lambda x: f"{x:,.0f}"))
    return ok


def auto_fix(sh, detail, info, names) -> int:
    """Perbaiki yang aman diperbaiki otomatis supaya tally:
       - BELUM MASUK tab brand      -> tambah creator di bawah + salin rumus
       - baris tanpa rumus GMV      -> salin rumus dari baris lain (hanya kalau username tidak dobel)
    Yang TIDAK diubah otomatis (perlu dicek manual): username dobel, #N/A di WEI, GMV beda padahal rumus ada."""
    fixed = 0
    print("\n--- Perbaikan otomatis ---")
    for b in BRAND_TABS:
        if b not in info:
            continue
        det = [d for d in detail if d[0] == b]
        missing = [d[1] for d in det if d[3] == "BELUM MASUK tab brand" and (b, d[1]) in names]
        if missing:
            new = pd.DataFrame({"username": [names[(b, u)][0] for u in missing],
                                "nama": [names[(b, u)][1] for u in missing]})
            append_creators(sh, b, new, template=info[b]["template"])
            print(f"  {b}: ditambahkan {', '.join(missing)}")
            fixed += len(missing)

        no_formula = [info[b]["rows"][d[1]][0][0] for d in det if d[3] == "ada, tapi baris tanpa rumus GMV"]
        if no_formula and info[b]["template"]:
            _copy_formulas(sh, info[b]["ws"], info[b]["template"], no_formula)
            print(f"  {b}: rumus GMV disalin ke baris {', '.join(map(str, no_formula))}")
            fixed += len(no_formula)

        for d in det:
            if d[3] == "DOBEL di tab brand":
                rr = ", ".join(f"{r}{'(tanpa rumus)' if g is None else ''}" for r, g in info[b]["rows"][d[1]])
                print(f"  {b}: CEK MANUAL {d[1]} dobel di baris {rr}")
            elif d[3] in ("ada", "ada di tab, tapi #N/A di WEI"):
                print(f"  {b}: CEK MANUAL {d[1]} ({d[3]}), selisih {d[5]:,.0f}")
    if not fixed:
        print("  Tidak ada yang bisa diperbaiki otomatis.")
    return fixed


def tally(sh, raw_tab: str, wei: set, write_tab: bool = True, fix: bool = True) -> bool:
    """Cek: GMV Raw (Cek name bukan #N/A) per brand == Total GMV di tab brand.
    Dihitung dari SELURUH isi tab Raw (data lama + baru). Kalau tidak tally dan fix=True,
    perbaiki otomatis lalu cek ulang. Return True kalau semua tally."""
    print(f"\n=== TALLY: '{raw_tab}' (Cek name valid) vs Total GMV tab brand ===")
    s, detail, info, names = _collect_tally(sh, raw_tab, wei)
    ok = _print_tally(s, detail)

    if fix and detail and auto_fix(sh, detail, info, names):
        time.sleep(3)   # tunggu rumus menghitung ulang
        print("\n=== TALLY ULANG setelah perbaikan ===")
        s, detail, info, names = _collect_tally(sh, raw_tab, wei)
        ok = _print_tally(s, detail)

    if write_tab:
        try:
            tws = sh.worksheet(TALLY_TAB)
        except Exception:
            tws = sh.add_worksheet(TALLY_TAB, rows=2000, cols=12)
        tws.batch_clear([f"A1:L{max(tws.row_count, 1)}"])
        left = [["Brand", "Username", "GMV Raw (Cek name valid)", "Status di tab brand", "GMV di tab brand",
                 "Selisih"]] + (detail or [["", "Semua username tally", "", "", "", ""]])
        if len(left) + 1 > tws.row_count:
            tws.add_rows(len(left) + 1 - tws.row_count)
        tot = ["Total"] + [s[c].sum() for c in s.columns[1:]]
        right = [list(s.columns)] + s.values.tolist() + [tot, [], ["Status", "TALLY" if ok else "TIDAK TALLY"],
                                                          ["Dicek", datetime.now().strftime("%Y-%m-%d %H:%M")]]
        right = [[(x.item() if hasattr(x, "item") else x) for x in r] for r in right]
        tws.update(range_name=f"A1:F{len(left)}", values=left)
        tws.update(range_name=f"H1:L{len(right)}", values=[r + [""] * (5 - len(r)) for r in right])
        print(f"Hasil tally ditulis ke tab '{TALLY_TAB}'.")
    return ok


# ---------------------------- PERFORMA CREATOR ---------------------------
PERF_TAB_PREFIX = "Performa"   # nama tab: "Performa 10 Nov", "Performa 9-15 Nov", "Performa 28 Okt-3 Nov"
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def perf_tab_name(start, end) -> str:
    if start == end:
        rng = f"{start.day} {BULAN[start.month - 1]}"
    elif (start.year, start.month) == (end.year, end.month):
        rng = f"{start.day}-{end.day} {BULAN[end.month - 1]}"
    else:
        rng = f"{start.day} {BULAN[start.month - 1]}-{end.day} {BULAN[end.month - 1]}"
    if start.year != end.year:
        rng += f" {end.year}"
    return f"{PERF_TAB_PREFIX} {rng}"


CHANNEL_SHORT = {"LIVE STREAMING": "LS", "SHORT VIDEO": "SV", "SHARELINK": "SL"}


def _to_date(v):
    """Tanggal dari sheet: angka serial (46334) atau teks ('2026-11-09' / '2026-11-09 10:00:00')."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(v))).date()
    t = pd.to_datetime(str(v).strip(), errors="coerce")
    return None if pd.isna(t) else t.date()


def parse_date_range(spec: str, ref_dates):
    """'10' -> tgl 10 saja, '9-15' / '9 sampai 15' -> tgl 9 s/d 15 (bulan & tahun ikut data Raw),
    '2026-11-09' atau '2026-11-09:2026-11-15' -> tanggal lengkap. Kosong / 'all' -> semua tanggal."""
    spec = (spec or "").strip().lower()
    known = [d for d in ref_dates if d]
    if not known:
        sys.exit("Tidak ada tanggal yang terbaca di tab Raw.")
    if spec in ("", "all", "semua"):
        return min(known), max(known)
    full = re.findall(r"\d{4}-\d{1,2}-\d{1,2}", spec)
    if full:
        a = pd.to_datetime(full[0]).date()
        b = pd.to_datetime(full[-1]).date()
    else:
        days = [int(x) for x in re.findall(r"\d{1,2}", spec)]
        if not days or len(days) > 2:
            raise ValueError(f"Format tanggal salah: '{spec}'. Contoh: 10  |  9-15  |  2026-11-09:2026-11-15")
        ref = max(known)
        a = ref.replace(day=days[0])
        b = ref.replace(day=days[-1])
    if a > b:
        a, b = b, a
    return a, b


def ask_date_range(ref_dates):
    lo, hi = min(d for d in ref_dates if d), max(d for d in ref_dates if d)
    print(f"\nData di Raw: {lo} s/d {hi}")
    while True:
        ans = input("Tanggal berapa? (contoh: 10  |  9-15  |  Enter = semua): ")
        try:
            return parse_date_range(ans, ref_dates)
        except ValueError as e:
            print("  ", e)


def performa(sh, raw_tab: str, spec=None, write_tab: bool = True, top: int = 10):
    """Performa creator (Cek name bukan #N/A) per brand & semua brand, untuk range tanggal tertentu."""
    ws = sh.worksheet(raw_tab)
    n = ws.row_count
    col_a, col_e, col_ip = ws.batch_get([f"A2:A{n}", f"E2:E{n}", f"I2:P{n}"],
                                        value_render_option="UNFORMATTED_VALUE")
    L = max(len(col_a), len(col_e), len(col_ip))
    col_a, col_e, col_ip = _pad(col_a, L), _pad(col_e, L), _pad(col_ip, L)

    def g(r, i):
        return r[i] if len(r) > i else ""

    raw = pd.DataFrame({
        "order": [str(g(r, 0)).strip() for r in col_a],
        "date": [_to_date(g(r, 0)) if g(r, 0) != "" else None for r in col_e],
        "brand": [str(g(r, 0)).strip() for r in col_ip],          # I
        "qty": [_to_num(g(r, 1)) for r in col_ip],                # J
        "nama": [str(g(r, 2)).strip() for r in col_ip],           # K
        "cek": [str(g(r, 3)).strip() for r in col_ip],            # L
        "user": [str(g(r, 4)).strip() for r in col_ip],           # M
        "gmv": [_to_num(g(r, 5)) for r in col_ip],                # N
        "channel": [str(g(r, 7)).strip() for r in col_ip],        # P
    })
    raw = raw[raw["user"] != ""]

    if spec is None:
        start, end = ask_date_range(raw["date"].tolist())
    else:
        start, end = parse_date_range(spec, raw["date"].tolist())
    label = f"{start}" if start == end else f"{start} s/d {end}"
    tab_name = perf_tab_name(start, end)

    d = raw[(raw["date"].notna()) & (raw["date"] >= start) & (raw["date"] <= end)
            & (raw["cek"] != "") & (~raw["cek"].str.startswith("#"))
            & (raw["brand"].isin(BRAND_TABS))].copy()
    excluded = raw[(raw["date"].notna()) & (raw["date"] >= start) & (raw["date"] <= end)
                   & (raw["cek"].str.startswith("#"))]
    print(f"\n=== PERFORMA CREATOR {label} (Cek name bukan #N/A) ===")
    print(f"Baris valid: {len(d):,} | GMV {d['gmv'].sum():,.0f} "
          f"(baris #N/A tidak dihitung: {len(excluded):,}, GMV {excluded['gmv'].sum():,.0f})")
    if d.empty:
        print("Tidak ada data di tanggal ini.")
        return None

    d["key"] = d["user"].map(norm_user)
    d["ch"] = d["channel"].map(lambda c: CHANNEL_SHORT.get(c.upper(), "SL"))

    # ---- tabel per creator: 1 blok ALL BRANDS + 1 blok per brand (tidak dicampur) ----
    def block(x, all_brands=False):
        ch = x.pivot_table(index="key", columns="ch", values="gmv", aggfunc="sum", fill_value=0)
        ch = ch.reindex(columns=["LS", "SV", "SL"], fill_value=0)
        first = x.drop_duplicates("key").set_index("key")
        t = pd.DataFrame({"Username": first["user"], "Nama": first["nama"]})
        if all_brands:
            t["Brands"] = x.groupby("key")["brand"].agg(
                lambda s: ", ".join(br for br in BRAND_TABS if br in set(s)))
        t["Order"] = x.groupby("key")["order"].nunique()
        t["Qty"] = x.groupby("key")["qty"].sum()
        t = t.join(ch.add_prefix("GMV "))
        t["Total GMV"] = x.groupby("key")["gmv"].sum()
        t = t.sort_values("Total GMV", ascending=False).reset_index(drop=True)
        t.insert(0, "Rank", range(1, len(t) + 1))
        return t

    blocks = [("ALL BRANDS", block(d, all_brands=True))]
    blocks += [(b, block(d[d["brand"] == b])) for b in BRAND_TABS if (d["brand"] == b).any()]
    cr = blocks[0][1]

    # ---- ringkasan per brand ----
    total = d["gmv"].sum()
    rows = []
    for b in BRAND_TABS:
        x = d[d["brand"] == b]
        rows.append([b, x["key"].nunique(), x["order"].nunique(), x["qty"].sum(), x["gmv"].sum(),
                     (x["gmv"].sum() / total) if total else 0,
                     (x["gmv"].sum() / x["key"].nunique()) if x["key"].nunique() else 0])
    rows.append(["ALL BRANDS", d["key"].nunique(), d["order"].nunique(), d["qty"].sum(), total, 1.0,
                 total / d["key"].nunique()])
    sm = pd.DataFrame(rows, columns=["Brand", "Creator", "Order", "Qty", "GMV", "% GMV", "GMV / creator"])

    fmt = lambda v: f"{v:,.0f}"
    print("\nRingkasan per brand:")
    print(sm.assign(**{"% GMV": sm["% GMV"].map(lambda v: f"{v:.1%}")})
          .to_string(index=False, float_format=fmt))
    for name, t in blocks:
        n_show = top if name == "ALL BRANDS" else 5
        print(f"\nTop {n_show} {name}:")
        print(t.head(n_show)[["Rank", "Username", "Nama", "Order", "Total GMV"]]
              .to_string(index=False, float_format=fmt))

    if write_tab:
        def py(v):
            return v.item() if hasattr(v, "item") else v

        GAP = 1                                    # 1 kolom kosong antar blok brand
        r_title = len(sm) + 7                      # baris judul blok brand
        width = sum(len(t.columns) + GAP for _, t in blocks)
        height = r_title + 1 + max(len(t) for _, t in blocks)

        try:
            pws = sh.worksheet(tab_name)
            print(f"\nTab '{tab_name}' sudah ada -> isinya diperbarui.")
        except Exception:
            pws = sh.add_worksheet(tab_name, rows=height + 5, cols=width + 2)
            print(f"\nTab baru dibuat: '{tab_name}'")
        pws.clear()
        if pws.row_count < height + 5:
            pws.add_rows(height + 5 - pws.row_count)
        if pws.col_count < width:
            pws.add_cols(width - pws.col_count)

        top_part = [[f"PERFORMA CREATOR {label}  (Cek name bukan #N/A)", "",
                     f"Dibuat {datetime.now():%Y-%m-%d %H:%M}"], [],
                    ["RINGKASAN PER BRAND"], list(sm.columns)]
        top_part += [[py(v) for v in r] for r in sm.values.tolist()]
        data = [{"range": "A1", "values": top_part}]

        bold = {"textFormat": {"bold": True}}
        num = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}
        fmts = [
            {"range": "A1", "format": {"textFormat": {"bold": True, "fontSize": 12}}},
            {"range": "A3", "format": bold},
            {"range": f"A4:G4", "format": {**bold, "backgroundColor": {"red": .9, "green": .9, "blue": .9}}},
            {"range": f"B5:E{4 + len(sm)}", "format": num},
            {"range": f"G5:G{4 + len(sm)}", "format": num},
            {"range": f"F5:F{4 + len(sm)}", "format": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}},
            {"range": f"A{4 + len(sm)}:G{4 + len(sm)}", "format": bold},
        ]
        col = 1
        for name, t in blocks:
            c1, c2 = _col(col), _col(col + len(t.columns) - 1)
            gmv = sm.loc[sm["Brand"] == name, "GMV"].iloc[0]
            data.append({"range": f"{c1}{r_title}",
                         "values": [[f"{name}  |  {len(t):,} creator  |  GMV {gmv:,.0f}"],
                                    list(t.columns)] + [[py(v) for v in r] for r in t.values.tolist()]})
            head_bg = {"red": .2, "green": .3, "blue": .5} if name == "ALL BRANDS" else {"red": .25, "green": .5, "blue": .45}
            fmts += [
                {"range": f"{c1}{r_title}:{c2}{r_title}",
                 "format": {"backgroundColor": head_bg,
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                {"range": f"{c1}{r_title + 1}:{c2}{r_title + 1}",
                 "format": {**bold, "backgroundColor": {"red": .9, "green": .9, "blue": .9}}},
                {"range": f"{_col(col + list(t.columns).index('Order'))}{r_title + 2}:{c2}{r_title + 1 + len(t)}",
                 "format": num},
            ]
            col += len(t.columns) + GAP
        pws.batch_update(data, value_input_option="RAW")
        pws.batch_format(fmts)
        print(f"Hasil ditulis ke tab '{tab_name}': blok ALL BRANDS + {len(blocks) - 1} brand, "
              f"masing-masing kolom sendiri.")
    return cr


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# --------------------------------- MAIN ----------------------------------
def siapkan(sh, df, statuses, verified, weeks, include_unknown=False, log=print):
    """Tahap baca saja: filter, hitung kolom turunan, cari creator baru, rekonsiliasi. Tidak menulis ke sheet."""
    d = build_raw_frame(df, statuses, verified, weeks)
    skipped = 0
    if not include_unknown:
        skipped = int((d["BRANDS"] == UNKNOWN_BRAND).sum())
        d = d[d["BRANDS"] != UNKNOWN_BRAND].reset_index(drop=True)
    log(f"Setelah filter: {len(d):,} baris | GMV {d['Purchase Value(Rp)'].sum():,.0f} | brand '{UNKNOWN_BRAND}' dilewati: {skipped:,}")
    wei = {norm_user(u) for u in read_user_col(sh.worksheet(WEI_TAB), 1, 2)}
    tab_users = {b: {norm_user(u) for u in read_user_col(sh.worksheet(b), COL_USERNAME, BRAND_FIRST_ROW)}
                 for b in BRAND_TABS}
    plan = plan_new_creators(d, wei, tab_users)
    return {"d": d, "wei": wei, "tab_users": tab_users, "plan": plan, "skipped": skipped,
            "out_of_range": int((d["WEEK"] == "OUT OF RANGE").sum()),
            "unknown_users": int(d[~d["_user"].isin(wei)]["_user"].nunique()),
            "rekon": reconcile(d, wei, tab_users, plan)}


def terapkan(sh, p, raw_tab=RAW_TAB, replace=False, append=True, tally_fix=True, log=print):
    """Tahap tulis: Raw, creator baru ke tab brand (dicek ulang tepat sebelum ditambah), lalu tally."""
    log("Menulis Raw ...")
    write_raw(sh, raw_tab, p["d"], replace=replace)
    if append:
        log("Menambah creator ke tab brand ...")
        for brand, new in p["plan"].items():
            if not len(new):
                continue
            now = {norm_user(u) for u in read_user_col(sh.worksheet(brand), COL_USERNAME, BRAND_FIRST_ROW)}
            new = new[~new["username"].map(norm_user).isin(now)]  # baca ulang: kalau sudah ditambah alat lain, lewati
            if len(new):
                append_creators(sh, brand, new)
    time.sleep(3)  # beri waktu rumus di tab brand menghitung ulang
    return tally(sh, raw_tab, p["wei"], fix=tally_fix)


def main():
    ap = argparse.ArgumentParser(description="Shopee BW raw CSV -> Google Sheet")
    ap.add_argument("csv", nargs="?", help="path file raw (.csv/.xlsx). Kosongkan untuk memilih lewat jendela pilih file")
    ap.add_argument("--status", help="Order Status yang dimasukkan, pisah koma, atau 'all'")
    ap.add_argument("--verified", help="Verified Status yang dimasukkan, pisah koma, atau 'all'")
    ap.add_argument("--weeks", help="Range tanggal per week, mis. '1-10,11-17,18-24,25-30'. Kosongkan untuk mengisi satu per satu")
    ap.add_argument("--raw-tab", default=RAW_TAB)
    ap.add_argument("--service-account", help="path JSON service account (opsional)")
    ap.add_argument("--dry-run", action="store_true", help="hanya simulasi, tidak menulis ke sheet")
    ap.add_argument("--include-unknown", action="store_true",
                    help=f"ikutkan baris brand '{UNKNOWN_BRAND}' ke Raw (default: hanya 7 brand)")
    ap.add_argument("--no-append", action="store_true", help="isi Raw saja, jangan tambah creator ke tab brand")
    ap.add_argument("--replace", action="store_true",
                    help="KOSONGKAN tab Raw dulu lalu isi ulang (perilaku lama). Default: data baru ditambah di bawah")
    ap.add_argument("--tally-only", action="store_true",
                    help="tidak upload apa-apa, hanya cek tally Raw (Cek name valid) vs Total GMV tab brand")
    ap.add_argument("--no-tally", action="store_true", help="lewati cek tally di akhir")
    ap.add_argument("--no-fix", action="store_true",
                    help="tally hanya cek, jangan perbaiki otomatis (tambah creator / salin rumus)")
    ap.add_argument("--performa", nargs="?", const="__ASK__", metavar="TANGGAL",
                    help="laporan performa creator (Cek name bukan #N/A) per brand & all brands. "
                         "TANGGAL: 10 | 9-15 | 2026-11-09:2026-11-15 | all. Kosongkan untuk ditanya")
    ap.add_argument("--top", type=int, default=10, help="jumlah top creator yang ditampilkan (default 10)")
    args = ap.parse_args()

    if args.performa is not None:
        sh = connect(args)
        performa(sh, args.raw_tab, None if args.performa == "__ASK__" else args.performa, top=args.top)
        sys.exit(0)

    if args.tally_only:
        sh = connect(args)
        wei = {norm_user(u) for u in read_user_col(sh.worksheet(WEI_TAB), 1, 2)}
        ok = tally(sh, args.raw_tab, wei, fix=not args.no_fix)
        sys.exit(0 if ok else 1)

    path = args.csv or pick_file()
    print(f"File: {path}")
    if str(path).lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    print(f"Data: {len(df):,} baris")

    statuses = choose(df["Order Status"], "Order Status", args.status)
    verified = choose(df["Verified Status"], "Verified Status", args.verified)
    weeks = parse_weeks(args.weeks) if args.weeks else ask_weeks()
    print("Week:", ", ".join(f"{l}={lo}-{hi}" for l, lo, hi in weeks))

    d = build_raw_frame(df, statuses, verified, weeks)
    if not args.include_unknown:
        skipped = int((d["BRANDS"] == UNKNOWN_BRAND).sum())
        d = d[d["BRANDS"] != UNKNOWN_BRAND].reset_index(drop=True)
        print(f"Baris brand '{UNKNOWN_BRAND}' tidak dimasukkan ke Raw: {skipped:,}")
    print(f"Setelah filter: {len(d):,} baris | GMV {d['Purchase Value(Rp)'].sum():,.0f}")
    print(d["BRANDS"].value_counts().to_string())
    oor = (d["WEEK"] == "OUT OF RANGE").sum()
    if oor:
        print(f"PERINGATAN: {oor} baris tanggalnya di luar range week manapun")

    sh = connect(args)
    wei = {norm_user(u) for u in read_user_col(sh.worksheet(WEI_TAB), 1, 2)}
    tab_users = {b: {norm_user(u) for u in read_user_col(sh.worksheet(b), COL_USERNAME, BRAND_FIRST_ROW)}
                 for b in BRAND_TABS}
    print(f"Username WEI: {len(wei):,} | per tab: " + ", ".join(f"{b}={len(s)}" for b, s in tab_users.items()))

    plan = plan_new_creators(d, wei, tab_users)
    tot = sum(len(v) for v in plan.values())
    unknown = d[~d["_user"].isin(wei)]["_user"].nunique()
    print(f"\nCreator baru yang akan ditambah ke tab brand: {tot:,} "
          f"(username #N/A / belum di WEI, tidak ditambah: {unknown:,})")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pd.concat([v.assign(brand=k) for k, v in plan.items()]).to_csv(f"creator_baru_{ts}.csv", index=False)

    if args.dry_run:
        print("\n[DRY RUN] tidak ada yang ditulis. Daftar creator baru: creator_baru_%s.csv" % ts)
    else:
        print("\nMenulis Raw ...")
        write_raw(sh, args.raw_tab, d, replace=args.replace)
        if not args.no_append:
            print("Menambah creator ke tab brand ...")
            for brand, new in plan.items():
                if len(new):
                    append_creators(sh, brand, new)

    print("\nRekonsiliasi (GMV Raw creator dikenal WEI vs yang tercover tab brand):")
    print(reconcile(d, wei, tab_users, plan).to_string(index=False, float_format=lambda x: f"{x:,.0f}"))

    if not args.dry_run and not args.no_tally:
        time.sleep(3)   # beri waktu rumus di tab brand menghitung ulang
        tally(sh, args.raw_tab, wei, fix=not args.no_fix)
    print("\nSelesai." if not args.dry_run else "")


if __name__ == "__main__":
    main()
