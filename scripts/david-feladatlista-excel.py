#!/usr/bin/env python3
"""Build David's task workbook (open + closed tabs) and upload it to his Drive folder.

David asked for it on 2026-10-06 (Telegram 8469), verbatim: "ide hozd letre nekem a
feladataimbol egy excelt, legyen szep, datumokkal szines cellakkal, zold tonusban, amit
befejezek az legyen egy kulon fulon, probalj meg valalhogy kategorzalni is".

The data comes from the SAME three sources as the daily list (david-napi-osszesito-0815):
the caf30d7b collector card's comments (with the [KESZ] / [MODOSITVA] filtering its own
description prescribes), David's open note cards, and the [OTLET] items. The items are
kept here as literal text on purpose: the collector comments are prose, and the filtering
decision (what is an item, what is an audit note) is a reading, not a regex -- see the
card description and the kanban-audit skill. Re-run after updating the ITEMS lists.

Drive: folder 1rfvSxQe2bIkqoAlhCHDfjIT0ZqJ-f1O9 ("PDB megosztott tablak"), auth from
store/.google-sheets-credentials (OAuth user token, scope includes .../auth/drive).
Measured 2026-10-06: canAddChildren and canEdit are both true on that folder.

Usage:
  python3 scripts/david-feladatlista-excel.py            # build + upload (converts to Sheets)
  python3 scripts/david-feladatlista-excel.py --no-upload # build the .xlsx only
  python3 scripts/david-feladatlista-excel.py --xlsx      # upload as .xlsx, no conversion
"""
import argparse
import datetime as dt
import json
import mimetypes
import os
import urllib.parse
import urllib.request

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

CREDS = "/home/pdb/marveen/store/.google-sheets-credentials"
FOLDER = "1rfvSxQe2bIkqoAlhCHDfjIT0ZqJ-f1O9"
KIMENET = "/home/pdb/marveen/store/david-listak/David_feladatai.xlsx"

# (kategoria, tetel, tipus, felveve)
# A SZOVEG EKEZETES, MERT EZ A FAJL DAVIDHOZ MEGY. A CLAUDE.md tilalma ("soha ne irj
# ekezet nelkuli magyart") a kimeno artefaktumra is all, nem csak az uzenetekre.
NYITOTT = [
    ("Belső / eszköz",      "Mi van a Kandaóval, amit elvitt a bizalmi körre?",                      "tétel",  "2026-08-28"),
    ("Belső / eszköz",      "Laptop vásárlás + iPad eladás",                                         "tétel",  "2026-08-28"),
    ("Termékadat",          "Az összes Peepsnek új kép és leírás (a cikkszámok kész)",               "tétel",  "2026-08-28"),
    ("Belistázás",          "Meshy Boom medical",                                                    "tétel",  "2026-08-31"),
    ("Beszerzés / árazás",  "Hohem árlistát megnézni, kalkulálni, hogyan eladni és venni",           "jegyzet", "2026-09-07"),
    ("Belistázás",          "Vincentnek van-e másik fa hatású képkerete",                            "jegyzet", "2026-09-15"),
    ("Partner / csatorna",  "MM Marketplace",                                                        "jegyzet", "2026-09-15"),
    ("Belistázás",          "Kodak scanner",                                                         "jegyzet", "2026-09-15"),
    ("Partner / csatorna",  "Transconineta bekötés",                                                 "jegyzet", "2026-09-15"),
    ("Partner / csatorna",  "Minnievel meeting összehozása",                                         "jegyzet", "2026-10-02"),
    ("Partner / csatorna",  "Ulanzi és K&F-et ne tudjon vásárolni az Onlinefoto",                    "jegyzet", "2026-10-02"),
    ("Belistázás",          "Vincent 700-as képkeret, 21 EUR",                                       "jegyzet-kártya", "2026-09-25"),
    ("Beszerzés / árazás",  "Agfa nyomtató order",                                                   "jegyzet-kártya", "2026-09-25"),
    ("Partner / csatorna",  "AgfaPhoto gyerekfényképező ajánlat a MediaMarktnak",                    "jegyzet-kártya", "2026-10-01"),
    ("Termék / konkurencia", "Printo probléma a Canon Selphy mellett",                               "jegyzet-kártya", "2026-10-01"),
    ("Tisztázandó",         "Retro box",                                                             "jegyzet-kártya", "2026-10-01"),
    ("Beszerzés / árazás",  "MyFirst: kevesebbet rendelni, Európából",                               "jegyzet-kártya", "2026-10-01"),
    ("Fejlesztési ötlet",   "Ár-pozíció figyelés: napi összevetés a fő versenytársak áraival, két lista (hol vagyunk drágák, hol feleslegesen olcsók)", "ötlet", "2026-09-03"),
    ("Fejlesztési ötlet",   "Halott készlet havi felismerése, javaslattal: csomag, akció, visszaadás beszállítónak, piactér", "ötlet", "2026-09-03"),
    ("Fejlesztési ötlet",   "A webshop nulla-találatos kereséseinek elemzése belistázási ötletforrásként", "ötlet", "2026-09-03"),
    ("Fejlesztési ötlet",   "Beszállítói proforma feldolgozása egy lépéssé: beküldött lista, kész feltölthető .xls és egyezés-jelentés", "ötlet", "2026-09-03"),
    ("Fejlesztési ötlet",   "Szállítói cikkszám lefedettségi felmérés márkánként",                   "ötlet", "2026-09-03"),
    ("Fejlesztési ötlet",   "Proforma egységár összevetése a legutóbb fizetett árral, eltérés-jelzéssel", "ötlet", "2026-09-03"),
]

# (kategoria, tetel, felveve, lezarva, hogyan zarult)
LEZART = [
    ("Termékadat",         "Ricsinek kell termékeket kiválogatni",                      "2026-08-28", "2026-09-01", "David jelezte, hogy elkészült"),
    ("Belistázás",         "Ipon porfújók",                                             "2026-09-01", "2026-09-01", "David jelezte, hogy elkészült"),
    ("Beszerzés / árazás", "KF árlista",                                                "2026-09-07", "2026-09-07", "David maga nekiállt, nem kell emlékeztető"),
    ("Partner / csatorna", "Kell még valami segítség az IFA-ra?",                       "2026-08-28", "2026-10-02", "David jelezte, hogy törölhető"),
    ("Belső / eszköz",     "CRM, és benne a válasz nélküli levelek követése",           "2026-09-02", "2026-10-02", "David jelezte, hogy törölhető"),
    ("Termékadat",         "Kép-forrás linkek beírása a Dörr New York állapot-táblába", "2026-09-03", "2026-10-02", "David jelezte, hogy törölhető"),
    ("Partner / csatorna", "Elérte Zoli a Patikát?",                                    "2026-08-28", "2026-10-02", "Átkerült Cilihez, ő kérdezi Zolit minden hétköznap"),
    ("Beszerzés / árazás", "Kínából FOB rendelés, hogyan működik",                      "2026-08-28", "2026-10-02", "David jelezte, hogy törölhető"),
    ("Partner / csatorna", "Godox B2B felületre belépni",                               "2026-08-28", "2026-10-02", "David jelezte, hogy törölhető"),
]

# Zold tonus, vilagostol a sotetig. A kategoria-szinek ugyanebbol a csaladbol valok,
# hogy a lap egyben maradjon, es a sorok csak a kategoriaban kulonbozzenek.
SOTET = "1E5631"
FEJLEC_BG = "1E5631"
SAVOK = ("EDF6EE", "FFFFFF")
KATEGORIA_SZIN = {
    "Belistázás":           "C8E6C9",
    "Beszerzés / árazás":   "A5D6A7",
    "Partner / csatorna":   "B2DFDB",
    "Termékadat":           "DCEDC8",
    "Termék / konkurencia": "D7CCC8",
    "Belső / eszköz":       "E0E0E0",
    "Fejlesztési ötlet":    "E8F5E9",
    "Tisztázandó":          "FFE0B2",
}
VONAL = Side(style="thin", color="BDBDBD")
KERET = Border(left=VONAL, right=VONAL, top=VONAL, bottom=VONAL)

# FORRAS-OSZLOP. David kerte 2026-10-06-an (Telegram 8472), mert eszrevette, hogy a 19-24.
# sort nem o vette fel. Igaza volt, es ki is mertem: 09-03 13:58-kor O kerdezte, milyen uj
# feladatot latok, a hat otletet EN javasoltam (13:59 es 14:03), es 14:22-kor annyit kert,
# hogy "ird fel ezeket mint otlet a kartyaimra". Minden MAS tetel az o diktalasa: a gyujto-
# kartya kommentjei szo szerinti idezettel rogzitik ("Dovid kartyara, ...", "kartyara - ...",
# "jegyzet - ..."), es a jegyzet-kartyak leirasa is idezetet tartalmaz.
# EGY KORLAT, AMIT KI KELL MONDANI: a conversation_log a 2026-08-31-i napra HIANYOS (husz sor,
# tobb kimeno valasz bejovo par nelkul), tehat a legelso ket tetelnel (Peeps, Meshy Boom) a
# bejovo keres SORA nem latszik. A komment alakja viszont ugyanaz, mint a tobbi diktalt
# tetelnel ("Fent van. Ot tetel." / "Kilenc tetel."), es a szovegezes is az ove, ezert
# Davidnak konyvelem oket. Ha o masra emlekszik, az ONE az eldontes.
FORRAS_OTLET = "Pedro javaslata, David parkoltatta"
FORRAS_DAVID = "David"


def forras(tipus: str) -> str:
    return FORRAS_OTLET if tipus == "ötlet" else FORRAS_DAVID


def fejlec(ws, cimek, szelesseg):
    for i, c in enumerate(cimek, 1):
        s = ws.cell(1, i, c)
        s.font = Font(bold=True, color="FFFFFF", size=11)
        s.fill = PatternFill("solid", fgColor=FEJLEC_BG)
        s.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        s.border = KERET
        ws.column_dimensions[get_column_letter(i)].width = szelesseg[i - 1]
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"


def ma() -> dt.date:
    return dt.date.today()


def nyitott_lap(wb):
    ws = wb.active
    ws.title = "Nyitott"
    fejlec(ws, ["#", "Kategória", "Tétel", "Típus", "Forrás", "Felvéve", "Napja nyitva",
                "Kész?"],
           [5, 21, 62, 15, 27, 12, 13, 9])
    for n, (kat, tetel, tipus, felveve) in enumerate(NYITOTT, 1):
        d = dt.date.fromisoformat(felveve)
        napja = (ma() - d).days
        f = forras(tipus)
        sor = n + 1
        ertekek = [n, kat, tetel, tipus, f, d, napja, ""]
        for i, v in enumerate(ertekek, 1):
            s = ws.cell(sor, i, v)
            s.border = KERET
            s.alignment = Alignment(vertical="center",
                                    wrap_text=(i in (3, 5)),
                                    horizontal="center" if i in (1, 4, 6, 7, 8) else "left")
            s.fill = PatternFill("solid", fgColor=SAVOK[n % 2])
            if i == 2:
                s.fill = PatternFill("solid", fgColor=KATEGORIA_SZIN.get(kat, "F1F8E9"))
                s.font = Font(bold=True, size=10)
            if i == 5 and f != FORRAS_DAVID:
                # Csak az terjen el a szemnek, ami NEM az ove. A sajat tetelei maradjanak semlegesek.
                s.fill = PatternFill("solid", fgColor="FFF3E0")
                s.font = Font(italic=True, size=9)
            if i == 6:
                s.number_format = "yyyy-mm-dd"
            if i == 7:
                # Minel regebben all, annal sotetebb a jelzes. Harom sav, nem folytonos.
                s.font = Font(bold=napja >= 30)
                s.fill = PatternFill("solid", fgColor="FFF9C4" if 14 <= napja < 30
                                     else "FFE0B2" if napja >= 30 else SAVOK[n % 2])
        ws.row_dimensions[sor].height = 28
    return ws


def lezart_lap(wb):
    ws = wb.create_sheet("Lezárt")
    fejlec(ws, ["#", "Kategória", "Tétel", "Forrás", "Felvéve", "Lezárva", "Hány nap",
                "Hogyan zárult"],
           [5, 21, 50, 14, 12, 12, 11, 42])
    for n, (kat, tetel, felveve, lezarva, hogyan) in enumerate(LEZART, 1):
        d1 = dt.date.fromisoformat(felveve)
        d2 = dt.date.fromisoformat(lezarva)
        sor = n + 1
        # A lezart teteleket mind David diktalta, egy sem az en javaslatom volt.
        for i, v in enumerate([n, kat, tetel, FORRAS_DAVID, d1, d2, (d2 - d1).days, hogyan], 1):
            s = ws.cell(sor, i, v)
            s.border = KERET
            s.alignment = Alignment(vertical="center",
                                    wrap_text=(i in (3, 8)),
                                    horizontal="center" if i in (1, 4, 5, 6, 7) else "left")
            s.fill = PatternFill("solid", fgColor=SAVOK[n % 2])
            if i == 2:
                s.fill = PatternFill("solid", fgColor=KATEGORIA_SZIN.get(kat, "F1F8E9"))
                s.font = Font(bold=True, size=10)
            if i in (5, 6):
                s.number_format = "yyyy-mm-dd"
            if i == 6:
                s.font = Font(bold=True, color=SOTET)
        ws.row_dimensions[sor].height = 28
    return ws


def osszegzo_lap(wb):
    ws = wb.create_sheet("Összegzés")
    fejlec(ws, ["Kategória", "Nyitott", "Lezárt"], [24, 11, 11])
    katok = sorted({k for k, *_ in NYITOTT} | {k for k, *_ in LEZART})
    for n, kat in enumerate(katok, 1):
        ny = sum(1 for k, *_ in NYITOTT if k == kat)
        le = sum(1 for k, *_ in LEZART if k == kat)
        for i, v in enumerate([kat, ny, le], 1):
            s = ws.cell(n + 1, i, v)
            s.border = KERET
            s.alignment = Alignment(vertical="center",
                                    horizontal="left" if i == 1 else "center")
            s.fill = PatternFill("solid", fgColor=KATEGORIA_SZIN.get(kat, "F1F8E9")
                                 if i == 1 else SAVOK[n % 2])
            if i == 1:
                s.font = Font(bold=True, size=10)
    sor = len(katok) + 2
    for i, v in enumerate(["ÖSSZESEN", len(NYITOTT), len(LEZART)], 1):
        s = ws.cell(sor, i, v)
        s.font = Font(bold=True, color="FFFFFF")
        s.fill = PatternFill("solid", fgColor=FEJLEC_BG)
        s.border = KERET
        s.alignment = Alignment(vertical="center",
                                horizontal="left" if i == 1 else "center")
    ws.cell(sor + 2, 1, f"Állapot: {ma().isoformat()}").font = Font(italic=True, size=9)
    return ws


def epit() -> str:
    wb = Workbook()
    nyitott_lap(wb)
    lezart_lap(wb)
    osszegzo_lap(wb)
    os.makedirs(os.path.dirname(KIMENET), exist_ok=True)
    wb.save(KIMENET)
    return KIMENET


def token() -> str:
    c = {}
    for line in open(CREDS):
        if "=" in line:
            k, v = line.split("=", 1)
            c[k.strip()] = v.strip()
    data = urllib.parse.urlencode({
        "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"],
        "refresh_token": c["REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=data))
    return json.load(r)["access_token"]


def letezo(tok: str, nev: str):
    """A mappaban mar bent levo, ugyanilyen nevu fajl id-je, hogy ne szaporodjon."""
    q = urllib.parse.urlencode({
        "q": f"'{FOLDER}' in parents and name = '{nev}' and trashed = false",
        "fields": "files(id,name,mimeType)", "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true"})
    r = urllib.request.urlopen(urllib.request.Request(
        f"https://www.googleapis.com/drive/v3/files?{q}",
        headers={"Authorization": "Bearer " + tok}))
    f = json.load(r).get("files", [])
    return f[0]["id"] if f else None


def feltolt(utvonal: str, nev: str, sheetre: bool) -> dict:
    tok = token()
    meta = {"name": nev}
    if sheetre:
        meta["mimeType"] = "application/vnd.google-apps.spreadsheet"
    azonos = letezo(tok, nev)
    if azonos:
        url = (f"https://www.googleapis.com/upload/drive/v3/files/{azonos}"
               "?uploadType=multipart&supportsAllDrives=true&fields=id,name,webViewLink")
        modszer = "PATCH"
    else:
        meta["parents"] = [FOLDER]
        url = ("https://www.googleapis.com/upload/drive/v3/files"
               "?uploadType=multipart&supportsAllDrives=true&fields=id,name,webViewLink")
        modszer = "POST"

    hatar = "----pedro-drive-boundary"
    tipus = mimetypes.guess_type(utvonal)[0] or "application/octet-stream"
    test = (f"--{hatar}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta, ensure_ascii=False)}\r\n"
            f"--{hatar}\r\nContent-Type: {tipus}\r\n\r\n").encode()
    test += open(utvonal, "rb").read() + f"\r\n--{hatar}--\r\n".encode()

    keres = urllib.request.Request(url, data=test, method=modszer, headers={
        "Authorization": "Bearer " + tok,
        "Content-Type": f"multipart/related; boundary={hatar}"})
    return json.load(urllib.request.urlopen(keres))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--xlsx", action="store_true", help="ne konvertalja Google Sheets-re")
    a = ap.parse_args()

    p = epit()
    print(f"kesz: {p} ({os.path.getsize(p)} bajt), "
          f"{len(NYITOTT)} nyitott / {len(LEZART)} lezart tetel")
    if a.no_upload:
        return 0
    r = feltolt(p, "David feladatai", sheetre=not a.xlsx)
    print(f"feltoltve: {r['name']} | id={r['id']}")
    print(f"link: {r.get('webViewLink')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
