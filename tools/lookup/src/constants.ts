import path from "node:path";
import { fileURLToPath } from "node:url";

export type DictionaryArchiveSpec = {
    fileName: string;
    url: string;
};

const currentDir = path.dirname(fileURLToPath(import.meta.url));

export const TOOL_ROOT = path.resolve(currentDir, "..", "..");
export const REPO_ROOT = path.resolve(TOOL_ROOT, "..", "..");
export const DICTIONARY_CACHE_DIR = path.join(
    REPO_ROOT,
    ".cache",
    "yomitan-dicts",
);

export const DICTIONARY_ARCHIVES: DictionaryArchiveSpec[] = [
    {
        fileName: "jitendex-yomitan.zip",
        url: "https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/jitendex-yomitan.zip",
    },
    {
        fileName: "KANJIDIC_english.zip",
        url: "https://github.com/yomidevs/jmdict-yomitan/releases/latest/download/KANJIDIC_english.zip",
    },
    {
        fileName: "JPDB_v2.2_Frequency_Kana_2024-10-13.zip",
        url: "https://github.com/Kuuuube/yomitan-dictionaries/raw/main/dictionaries/JPDB_v2.2_Frequency_Kana_2024-10-13.zip",
    },
    {
        fileName: "JPDB_Kanji.zip",
        url: "https://github.com/MarvNC/yomichan-dictionaries/raw/master/dl/%5BKanji%5D%20JPDB%20Kanji.zip",
    },
];

export const DEFAULT_DEFINITION_DICTIONARY_NAMES = ["Jitendex"];
export const DEFAULT_FREQUENCY_DICTIONARY_NAMES = ["JPDB"];
export const DEFAULT_MAX_WORDS_PER_KANJI = 12;
