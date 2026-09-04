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
