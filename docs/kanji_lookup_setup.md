# Lapis Lookup setup

This guide covers the `lapis_lookup` addon in this repo.

Goal:
- review a normal Lapis card
- tap a kanji on the **back**
- open a kanji popover with common related words
- tap a related word
- open a second popover with that word's definition + frequency

All lookup data is precomputed offline and stored in the note field `KanjiLookupData`.

## What this feature supports

- Lapis-family note types only
- desktop Anki addon for setup/backfill
- review-time usage on cards, including mobile clients that can run the card JS

It does **not** do live dictionary lookups during review.

## Prerequisites

You need:

1. Anki desktop
2. Node.js and npm on your `PATH`
3. A repo checkout of `~/personal/lapis`
4. The `lapis_lookup` addon copied into your Anki `addons21` folder

The addon expects `lookup_repo_root` to point at this repo checkout.

## Files involved

- addon: [anki_addon/lapis_lookup/addon.py](/Users/mollicl/personal/lapis/anki_addon/lapis_lookup/addon.py:1)
- addon config: [anki_addon/lapis_lookup/config.json](/Users/mollicl/personal/lapis/anki_addon/lapis_lookup/config.json:1)
- lookup tool: [tools/lookup/package.json](/Users/mollicl/personal/lapis/tools/lookup/package.json:1)
- card back UI: [src/back.html](/Users/mollicl/personal/lapis/src/back.html:112)
- card styling: [src/styling.css](/Users/mollicl/personal/lapis/src/styling.css:1162)

## One-time setup

### 1. Install the addon

Copy this folder into Anki:

- `/Users/mollicl/personal/lapis/anki_addon/lapis_lookup`

Target should be something like:

- `~/Library/Application Support/Anki2/addons21/lapis_lookup/`

Then fully restart Anki.

### 2. Check addon config

Open:

- `Tools -> Add-ons -> lapis_lookup -> Config`

Confirm:

- `lookup_repo_root` points to `/Users/mollicl/personal/lapis`

Default config keys:

- `lookup_repo_root`
- `definition_dictionary_names`
- `frequency_dictionary_names`
- `max_words_per_kanji`

Meaning:

- `definition_dictionary_names`: preferred dictionary name fragments for related-word definitions
- `frequency_dictionary_names`: preferred dictionary name fragments for frequency pick
- `max_words_per_kanji`: max related words stored for each kanji

See also: [anki_addon/lapis_lookup/config.md](/Users/mollicl/personal/lapis/anki_addon/lapis_lookup/config.md:1)

### 3. Let the addon bootstrap tool dependencies

You do **not** need to manually install dictionaries first.

On first real backfill run, the addon will:

1. install npm deps for `tools/lookup`
2. build the TypeScript tool
3. download the required dictionary zips into:
   - `/Users/mollicl/personal/lapis/.cache/yomitan-dicts/`
4. import those dictionaries into:
   - `/Users/mollicl/personal/lapis/tools/lookup/data/lapis-yomitan.sqlite`

Lookup uses the prepared sqlite database. The zips are bootstrap inputs only.

Downloaded dictionaries:

- `jitendex-yomitan.zip`
- `KANJIDIC_english.zip`
- `JPDB_v2.2_Frequency_Kana_2024-10-13.zip`
- `JPDB_Kanji.zip`

## First use

### 1. Open Browser and select Lapis notes

Use a small test set first.

Recommended:

- select 5-20 Lapis notes

### 2. Run setup + backfill

In Browser menu bar:

- `Lapis Lookup -> Setup + Backfill Selected Notes`

What it does:

1. verifies selected notes are Lapis-family notes
2. clones current note type to `<CurrentName>+Lookup` if needed
3. adds field `KanjiLookupData`
4. patches back template/CSS with the lookup UI
5. converts selected notes in place to the cloned note type
6. computes lookup payloads and writes `KanjiLookupData`

Important:

- this does **not** create a new deck
- this does **not** duplicate the notes
- it converts selected notes in place, so scheduling should stay intact as long as template count/order match

### 3. Review one of the converted cards

On the **back** of the card:

1. tap a kanji in the expression
2. kanji popover opens
3. tap a related word
4. word popover opens
5. use `Back` to return

Navigation:

- word back -> kanji view
- kanji back -> main card

## Diagnose / sanity checks

In Browser:

- `Lapis Lookup -> Diagnose Selected Notes`

Use this if setup/backfill did not do what you expected.

It checks whether selected notes:

- are on a Lapis-family model
- have `KanjiLookupData`
- are already on a lookup-enabled note type

## Recommended onboarding flow

Safest flow:

1. backup your Anki profile or export your deck
2. select a small Lapis subset
3. run `Setup + Backfill Selected Notes`
4. review a few converted cards
5. if good, run on a larger selection

## How lookup data is built

For each selected note:

1. read `Expression`
2. extract unique kanji in display order
3. get related words from JPDB kanji data
4. look up each related word through `yomitan-core`
5. if a related word is a single kanji and term lookup fails, fallback to kanji lookup
6. choose one frequency from preferred frequency dictionaries
7. store result as JSON in `KanjiLookupData`

The payload includes:

- source expression
- constituent kanji
- related words per kanji
- reading
- frequency
- rendered dictionary-entry HTML for the word popover

## If you update dictionaries or tool code

If you change:

- `tools/lookup`
- dictionary preferences
- number of words per kanji

Then rerun:

- `Lapis Lookup -> Setup + Backfill Selected Notes`

It is safe to use as a refresh/backfill command for already-enabled notes.

## Known limitations

- Lapis-family note types only
- data can get large because related-word HTML is stored in notes
- first run can be slow because npm install/build + dictionary download + sqlite preparation happen automatically
- no live search during review; only precomputed drilldown around the card expression

## Troubleshooting

### The menu does not appear

- fully quit Anki and reopen
- confirm addon folder is really `addons21/lapis_lookup/`

### Backfill fails immediately

Check:

- `node -v`
- `npm -v`

Both must work on your machine.

If the prepared dictionary database is missing, from repo root run:

```bash
cd tools/lookup
npm install
npm run build
npm run fetch-dictionaries
npm run prepare-database
```

### No related words show up

Possible causes:

- selected notes were not Lapis-family notes
- `Expression` field empty or kana-only
- backfill did not finish
- note type not converted to the `+Lookup` clone

Run:

- `Lapis Lookup -> Diagnose Selected Notes`

### I want different dictionaries

Edit addon config:

- `definition_dictionary_names`
- `frequency_dictionary_names`
- `dictionary_db_path`

These are matched by name fragment, not exact full title.
