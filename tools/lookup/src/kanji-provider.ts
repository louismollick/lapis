import { readArchiveText } from "./dictionaries.js";

const JPDB_KANJI_ARCHIVE = "JPDB_Kanji.zip";
const JPDB_KANJI_BANK_FILE = "kanji_bank_1.json";

let cachedWordMap: Map<string, string[]> | null = null;

export async function getRelatedWordsForKanji(
    character: string,
): Promise<string[]> {
    if (!cachedWordMap) {
        cachedWordMap = await loadRelatedWordMap();
    }

    return cachedWordMap.get(character) ?? [];
}

async function loadRelatedWordMap(): Promise<Map<string, string[]>> {
    const jsonText = await readArchiveText(
        JPDB_KANJI_ARCHIVE,
        JPDB_KANJI_BANK_FILE,
    );
    const rawEntries = JSON.parse(jsonText) as unknown[];
    const wordMap = new Map<string, string[]>();

    for (const entry of rawEntries) {
        if (!Array.isArray(entry) || typeof entry[0] !== "string") {
            continue;
        }

        const words = Array.isArray(entry[4])
            ? entry[4].filter(
                  (item): item is string => typeof item === "string",
              )
            : [];
        const dedupedWords = [
            ...new Set(words.map((word) => word.trim()).filter(Boolean)),
        ];
        wordMap.set(entry[0], dedupedWords);
    }

    return wordMap;
}
