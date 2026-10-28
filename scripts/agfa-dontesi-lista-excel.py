# -*- coding: utf-8 -*-
"""Build the AgfaPhoto image-anomaly decision list as a workbook and upload it to the
shared Drive folder.

David's standing rule (2026-08-18, memory 695): every spreadsheet an agent makes goes to
the Google Drive folder "PDB megosztott tablak" (1rfvSxQe2bIkqoAlhCHDfjIT0ZqJ-f1O9), so
everyone can see it. He restated it on 2026-10-22 06:26 after a PDF went out instead.

Source of the content: store/agfa-kep-audit/jelentes-2026-10-09.md (13 tabs, 229 images
opened, 41 anomalies) and the decision list built from it on 2026-10-16.

The upload path mirrors scripts/david-feladatlista-excel.py: refresh-token auth from
store/.google-sheets-credentials, name-based lookup then PATCH so re-runs do not multiply
the file, and Google Sheets conversion by default so he can edit it in the browser.

Usage:
  python3 scripts/agfa-dontesi-lista-excel.py              # build + upload as a Sheet
  python3 scripts/agfa-dontesi-lista-excel.py --no-upload  # build the .xlsx only
  python3 scripts/agfa-dontesi-lista-excel.py --xlsx       # upload as .xlsx, no conversion
"""
import argparse, json, mimetypes, os, urllib.parse, urllib.request
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

CREDS = "/home/pdb/marveen/store/.google-sheets-credentials"
FOLDER = "1rfvSxQe2bIkqoAlhCHDfjIT0ZqJ-f1O9"
KIMENET = "/home/pdb/marveen/store/agfa-kep-audit/agfa-dontesi-lista.xlsx"
NEV = "Agfa kép-anomáliák döntési lista"

FEJ = PatternFill("solid", fgColor="2E7D32")
SAV = PatternFill("solid", fgColor="E8F5E9")
ELDOLT = PatternFill("solid", fgColor="C8E6C9")
VAR = PatternFill("solid", fgColor="FFF9C4")
KULSO = PatternFill("solid", fgColor="FFE0B2")
KERET = Border(*[Side(style="thin", color="A5D6A7")] * 4)
FEJBETU = Font(bold=True, color="FFFFFF", size=10)
TORD = Alignment(wrap_text=True, vertical="top")


def fejlec(ws, cimek, szelesseg):
    ws.append(cimek)
    for i, sz in enumerate(szelesseg, start=1):
        ws.column_dimensions[get_column_letter(i)].width = sz
    for c in ws[1]:
        c.fill, c.font, c.alignment, c.border = FEJ, FEJBETU, TORD, KERET
    ws.freeze_panes = "A2"


def sorok(ws, adat, kiemelo=None):
    for n, r in enumerate(adat):
        ws.append(r)
        sor = ws[ws.max_row]
        for c in sor:
            c.alignment, c.border = TORD, KERET
            c.fill = SAV if n % 2 else PatternFill("none")
        if kiemelo:
            kiemelo(sor, r)


def teendo_lap(wb):
    """David kerese 2026-10-22 09:07: "dolgozd at az excel listat, mert erhetetlen amivel kell
    foglalkozni / ami kesz NE legyen benne / ami nekunk nincs keszleten NE legyen benn".

    Ezert EGY ful van, es csak az all benne, amivel dolgozni kell. Ami kesz, es ami nem a mi
    cikkunk, kikerult. A kivett tetelek merese a 4cc47972 kartyan tetelesen megvan.
    """
    ws = wb.active
    ws.title = "Teendő"
    fejlec(ws, ["#", "Cikkszám", "Megnevezés a GT füzetben", "Mi hiányzik", "Készlet",
                "Kinél van a lépés", "Kész?"],
           [5, 20, 30, 34, 10, 26, 9])
    adat = [
        [1, "AG-AZK01", "BATTERIES", "nincs termékkép a GT munkafüzetben", "9",
         "gyártó (GT, Vincent)", ""],
        [2, "AG-ABL5B", "BATTERIES", "nincs termékkép a GT munkafüzetben", "14",
         "gyártó (GT, Vincent)", ""],
        [3, "AG-ABP5M", "BATTERIES", "nincs termékkép a GT munkafüzetben", "21",
         "gyártó (GT, Vincent)", ""],
        [4, "AG-BAT-AC7000", "BATTERIES", "nincs termékkép a GT munkafüzetben", "10",
         "gyártó (GT, Vincent)", ""],
        [5, "AG-BAT-AC9000", "BATTERIES", "nincs termékkép a GT munkafüzetben", "9",
         "gyártó (GT, Vincent)", ""],
        [6, "AG-WP6000BL", "CAMERA", "nincs termékkép a GT munkafüzetben", "13",
         "gyártó (GT, Vincent)", ""],
        [7, "AG-WP6000RD", "CAMERA", "nincs termékkép a GT munkafüzetben", "16",
         "gyártó (GT, Vincent)", ""],
        [8, "AG-ARKICPK", "KIDS", "nincs termékkép a GT munkafüzetben", "16",
         "gyártó (GT, Vincent)", ""],
        [9, "AG-ATP3CL2", "PRINTER & CARTRIDGE",
         "kép a PAPÍRRÓL (doboz-képe van, image210)", "van",
         "gyártó (GT, Vincent). A Te kérésed 10-22.", ""],
        [10, "CC2700-2MIC", "VIDEO",
         "ELŐBB TISZTÁZÁS, nem kép: nálunk nincs pontos egyezés", "nincs rá adat",
         "nálunk: van AG-CC2700 és AG-CC2700-2, de mikrofonos csomag nincs", ""],
    ]

    def kiem(sor, r):
        sor[6].fill = VAR
        if r[0] == 10:
            for c in sor:
                c.fill = KULSO
    sorok(ws, adat, kiem)

    ws.append([])
    ws.append(["", "EZ A TELJES TEENDŐ-LISTA, 2026-10-22 09:1x. Kilenc kép-kérés a gyártó felé, "
               "plusz egy tisztázandó tétel. A kiküldés a Te köröd; ha kell, összeállítom "
               "angolul, küldésre készen."])
    ws.append(["", "MI KERÜLT KI, ÉS MIÉRT (a Te két szabályod szerint):"])
    ws.append(["", "KÉSZ, ezért nincs benne: az ATP3WH2 és az ATP3CL2 saját doboz-képe már első; "
               "a DC5200 mind az öt színe és a DC5500 PK, RD is a saját színében van a "
               "webshopon. Sam mérte 10-22-én, élőben."])
    ws.append(["", "NEM A MI CIKKÜNK, ezért nincs benne, 19 tétel: ATP3WH, AMCS20, AMOC40, "
               "AMOC80, ASQC20, AMOC120, DC5500 BL, ABL5B2, 110-866888, 110-866901, az öt SD "
               "kártya (10403P, 10424, 10425, 10428, 10582A1), a négy pendrive (10512, 10513, "
               "10514, 10542N), a három analóg (603010, 6FR100, 6FR400), FL-10, ZINK30, "
               "APF1560WIFIWD. Sam mind a 27-et lemérte, getProduct, több SKU-alakkal."])
    ws.append(["", "KÉSZLET: a kilenc teendő-tétel közül mind a nyolc mérhetőnek van készlete "
               "(9 és 21 db között), tehát nincs olyan sor, ami nulla készlet miatt esne ki."])
    ws.append(["", "AMI A GT MUNKAFÜZETBEN NYITOTT MARADT, de a webshopunkon KÉSZ, ezért "
               "kivettem: a DC5200 öt és a DC5500 két színváltozatának doboz-fotója, és a "
               "hőpapír-hármas horgonyzása. Szólj, ha ezeket mégis látni akarod."])
    for i in range(6):
        for c in ws[ws.max_row - i]:
            c.alignment, c.border = TORD, KERET


def epit() -> str:
    wb = Workbook()
    teendo_lap(wb)
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
    return json.load(urllib.request.urlopen(keres)), modszer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--xlsx", action="store_true", help="ne konvertalja Google Sheets-re")
    a = ap.parse_args()
    p = epit()
    print(f"kesz: {p} ({os.path.getsize(p)} bajt)")
    if a.no_upload:
        return 0
    r, modszer = feltolt(p, NEV, sheetre=not a.xlsx)
    print(f"{modszer} | feltoltve: {r['name']} | id={r['id']}")
    print(f"link: {r.get('webViewLink')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
