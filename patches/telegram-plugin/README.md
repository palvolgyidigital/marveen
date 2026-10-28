# Telegram plugin patch: idezett uzenet a <channel> blokkban

Ez a konyvtar NEM a marveen sajat forraskodjahoz tartozik. A tartalma egy
LOKALIS patch a hivatalos Claude Code marketplace pluginhoz:

- **Plugin**: `claude-plugins-official/telegram`
- **Erintett verzio**: `0.0.7`
- **Elettelen hely elesben**: `~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7/`
  (minden agent kozos, git nelkuli peldanya -- lasd "Amit ez NEM old meg" lent)

## Miert kellett

2026-09-04-en David Telegramon IDEZVE valaszolt Pedro egy konkret uzenetere
("lezarhato"), Pedro viszont egy masik nyitott temara ertette, mert a bejovo
`<channel>` blokk nem tartalmazza, MELYIK korabbi uzenetre valaszolt a
felhasznalo. Rossz kartya zarult le, egy uzleti dontes is rosszul rogzult,
42 masodperc mulva helyesbiteni kellett.

Root cause: a Telegram Bot API update-je (`ctx.message.reply_to_message`)
tartalmazza az idezett uzenetet, a plugin mar MA IS hasznalja ezt egy masik
celra (server.ts:323, csoportos bot-megszolitas felismerese) -- de a bejovo
`<channel>` notification meta-ja soha nem adta tovabb a modellnek.

## Mit modosit a patch

1. **`reply-meta.ts`** (UJ fajl a plugin konyvtaraba) -- tiszta, fail-safe
   fuggveny: `replyMeta(replyTo)`.
   - Nincs idezett uzenet -> `{}` (semmi valtozas a mai viselkedeshez kepest).
   - Van idezett uzenet -> `reply_to_message_id` mindig, `reply_to_excerpt`
     csak ha van szoveg/caption (max 200 karakter, a mar meglevo `safeName()`
     mintajat kovetve cenzurazza a `< > [ ] \r \n ;` karaktereket, nehogy az
     IDEZETT fel szovege kitorjon a `<channel>` tagbol -- ez nem feltetlenul
     ugyanaz a szemely, mint aki most ir).
2. **`reply-meta.test.ts`** (UJ fajl) -- `bun:test`, 7 eset (idezettel/anelkul,
   szoveg/caption/egyik sem, tulhosszu szoveg vagasa, delimiter-injection,
   csak-whitespace szoveg). Futtatas: `bun test reply-meta.test.ts` a plugin
   konyvtarabol.
3. **`server.ts`** -- harom pontos valtoztatas, lasd `server.ts.patch`:
   - import `replyMeta`
   - a bejovo notification meta-objektumaba `...replyMeta(ctx.message?.reply_to_message)`
   - az instrukcio-szoveg (amit a modell tooldescription-kent kap) kiegeszitve
     egy mondattal a `reply_to_message_id` / `reply_to_excerpt` mezokrol --
     kulonben az adat megjonne, de senki nem tudna, hogy nezze.

`conversation_log`-os tarolas (utolagos rekonstrualhatosag) SZANDEKOSAN NINCS
ebben a korben -- Pedro kulon valtoztatasnak akarja, sema-modositas, elobb
lassa az adatot elesben.

## FIGYELEM: A KESZLET ELAVULT AZ ELO FAJLHOZ KEPEST (mert 2026-10-12, es ez a recept HIBAJA volt)

Amikor ma a negyedik patch-et irtam, lemertem a harom fajlt, es a kep ez volt:
elo `server.ts` 40205 bajt, `server.ts.patched` 40661, `server.ts.orig` 40358.
**Az ELO fajl KET olyan Marveen-patch-et tartalmazott, ami a keszletben nem volt benne**
(`elsokor922-d4`: a /help es /status kezelok athelyezve a command hookba; `cmd920-evid`:
inbound-evidence naplozas). Vagyis a lenti "egyszeru fajl-visszamasolas" recept
**CSENDBEN VISSZAVONTA VOLNA azt a ket elo javitast.**

A `plugin-patch-orszem` ettol nem vedett meg, es ez nem az o hibaja: az `ellenorzes.py`
a replyMeta-patch JELENLETET meri, nem a fajl teljes azonossagat. Egy szuk orszem
helyes, csak tudni kell, mit NEM mer.

**SZABALY, AMI EBBOL KOVETKEZIK: valahanyszor egy uj patch kerul az ELO plugin-fajlba,
ugyanabban a korben regeneralni kell a keszletet is:**
```bash
P=~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7
cp "$P/server.ts" patches/telegram-plugin/server.ts.patched
diff -u patches/telegram-plugin/server.ts.orig patches/telegram-plugin/server.ts.patched \
  > patches/telegram-plugin/server.ts.patch
```
Es POZITIV KONTROLL utana, mert egy diff lehet szintaktikailag jo es tartalmilag hibas:
az `orig`-ra alkalmazva BAJTRA a `patched` fajlt kell adnia (`patch` + `cmp`).
A 2026-10-12-i regeneralas igy tortent, es a kontroll atment. A regi, elavult peldany
`server.ts.patched.elavult-20261012` neven megmaradt, hogy a ket elveszett patch
visszakeresheto legyen, ha kell.

## NEGYEDIK PATCH: `permleak1012` -- a jovahagyas-prompt nem megy mindenkinek

**A hiba, ket mert esettel:** a vendor a `permission_request` notificationt
`for (const chat_id of access.allowFrom)` ciklusban MINDEN parositott chatre elkuldi.
Nalunk minden agens allowFrom-jaban 3-5 kollega van, tehat egy sub-agens Bash-promptja
mindegyikukhoz megerkezik. 2026-08-03-an David kapta meg Sam szkriptjenek promptjat
(ket Deny-t nyomott ra), 2026-09-11-en Abel Max hat kutato-szalabol. Egy ilyen prompt
utvonalat, parancsot vagy parameter-erteket is tartalmazhat.

**A javitas:** ha a `/home/pdb/marveen/store/permission-prompt-chat.txt` EGY chat_id-t
tartalmaz, a prompt CSAK oda megy. A fajl ma a 8668856531-et (Marci, a technikai
tulajdonos) tartalmazza. Ha a fajl hianyzik vagy ures, a vendor viselkedes valtozatlan,
tehat egy friss telepitesen nincs regresszio.

**KET DONTES A JAVITASBAN, es mindketto szandekos:**
1. **Nem az `access.json`-ba kerult a beallitas**, hanem egy sajat fajlba a repoban. Az
   `access.json` szerkesztese parositasi/hozzaferesi muvelet, es a plugin sajat
   instrukcioja tiltja, hogy csatorna-uzenet alapjan hozzanyuljunk. Ez a valtoztatas
   ettol fuggetlen: NEM ad hozzaferest senkinek, csak szukiti, ki kap promptot.
2. **Ha a konfiguralt chat NINCS az adott csatorna allowFrom-jaban, a kod a vendor
   broadcastra esik vissza, es stderr-re ir.** A kezenfekvo alternativa (ne menjen
   senkinek) egy jovahagyast NEMITANA EL, ami megakasztja a Bash-hivast -- az rosszabb,
   mint a zaj. Merve: a 8668856531 ma mind a nyolc agens allowFrom-jaban benne van.

**AMIT EZ NEM FED:** nincs ra unit-teszt. A `reply-meta.ts` kulon fuggvenyben all, ezert
tesztelheto; ez a logika a vendor fajlban, inline. A szintaxist `bun build`-del
ellenoriztem, a harom agat olvasassal. Eles igazolas egy valodi jovahagyas-prompt lenne.

## Hogyan alkalmazd (friss telepitesen, vagy egy plugin-frissites utan)

A legmegbizhatobb ut EGYSZERU FAJL-VISSZAMASOLAS, nem ujraforditas vagy
kezi patch-elgetes:

```bash
PLUGIN_DIR=~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7
cp patches/telegram-plugin/reply-meta.ts "$PLUGIN_DIR/"
cp patches/telegram-plugin/reply-meta.test.ts "$PLUGIN_DIR/"
cp patches/telegram-plugin/server.ts.patched "$PLUGIN_DIR/server.ts"
```

Ez CSAK akkor biztonsagos, ha a plugin meg mindig `0.0.7` -- ellenorizd:

```bash
grep '"version"' ~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7/.claude-plugin/plugin.json
```

Ha MAS verzio van telepitve, a `server.ts.patched` valoszinuleg NEM
egyezik meg tobbe az uj vendor-fajllal -- ilyenkor `server.ts.patch`-et
(unified diff) probald meg `patch`/`git apply`-vel az UJ `server.ts`-re, es
kezzel oldd fel az utkozeseket. A `reply-meta.ts`/`reply-meta.test.ts` uj,
onallo fajlok, azok valtozatlanul masolhatok at.

## Visszaallitas (rollback)

```bash
PLUGIN_DIR=~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7
cp patches/telegram-plugin/server.ts.orig "$PLUGIN_DIR/server.ts"
rm -f "$PLUGIN_DIR/reply-meta.ts" "$PLUGIN_DIR/reply-meta.test.ts"
```

Utana a plugin-t hordozo csatorna-processz(eke)t ujra kell inditani, hogy a
valtoztatas ELESBEN is ervenyesuljon (a mar futo bun-processzek a regi kodot
tartjak memoriaban).

## Amit ez NEM old meg

- **Ez a plugin-cache-masolat NINCS verziokezelve.** A `~/.claude/plugins/cache/...`
  konyvtarnak nincs sajat git-je, a marveen repo sem epiti/masolja oda ezeket
  a fajlokat automatikusan. A `patches/telegram-plugin/` alatti masolat a
  TUDAS megorzesere valo, nem egy mukodo telepito -- a tenyleges elesitest
  mindig kezzel (vagy egy jovoben megirando script-tel) kell elvegezni.
- **Egy jovobeli plugin-auto-frissites CSENDBEN felulirhatja.** Nincs olyan
  installer-hook, mint a git-hookoknal (`scripts/install-*-hook.sh` +
  `scripts/sync-hooks.sh`), ami minden `update.sh` futasnal ujra beallitana
  ezt a patch-et. Ha egy frissites utan valaki azt latja, hogy "megint nem
  jon at az idezet a <channel> blokkban", ez a leggyakoribb ok -- nezd meg a
  plugin verziojat (fent), es ha valtozott, alkalmazd ujra ezt a patchet.
- **Fork-vs-lokalis-patch strategiai kerdes nyitva van.** Hosszu tavon ket ut
  van: (a) sajat forkolt masolat a plugin marketplace-bol, a marveen sajat
  build/deploy folyamataba illesztve (a marveen upstream-fork mintajara), vagy
  (b) tudatosan vallalt, dokumentalt lokalis patch, amit minden plugin-
  frissitesnel ujra meg kell nezni. Ez Marci dontese, nem technikai kerdes --
  Pedro kartyara veszi, kuszobbel, nem surgos.

## Ellenorzes elesitesnel

- `bun test reply-meta.test.ts` a plugin konyvtarabol -- zold.
- `bun build server.ts --target=bun` a plugin konyvtarabol -- hiba nelkul
  bundlel (ez az import-felbontast es a szintaxist igazolja ujrainditas
  nelkul, de NEM helyettesiti az eles ellenorzest).
- **ELES ELLENORZES, ami tenyleg szamit**: egy VALODI idezett Telegram-uzenet
  utan nezd meg, hogy a `<channel>` blokkban ott van-e a `reply_to_message_id`
  es (ha volt szoveg) a `reply_to_excerpt` attributum. A bundle sikeres
  epitese ezt NEM bizonyitja.
