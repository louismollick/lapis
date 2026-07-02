`lookup_repo_root`: Absolute path to this repo checkout.

`definition_dictionary_names`: Preferred dictionary name fragments for rendering related-word definitions.

`frequency_dictionary_names`: Preferred dictionary name fragments for picking a frequency value.

`dictionary_db_path`: Optional absolute path to a prepared Yomitan sqlite database. Leave `null` to use `tools/lookup/data/lapis-yomitan.sqlite` inside `lookup_repo_root`.

`max_words_per_kanji`: Max related words to precompute for each kanji.

`lookup_chunk_size`: Number of notes to process per Node/Yomitan worker restart. Lower values use less memory and run slower. Default: `100`.

`note_timeout_seconds`: Seconds to wait for a note before killing the current worker, skipping that note, and continuing. Default: `90`.

`node_max_old_space_mb`: Optional Node heap cap in MB. Leave `null` to use Node's default.
