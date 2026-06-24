import { readArchiveText } from "./dictionaries.js";

const JPDB_KANJI_ARCHIVE = "JPDB_Kanji.zip";
const JPDB_KANJI_BANK_FILE = "kanji_bank_1.json";
const KANJI_DECOMPOSITION_MARKER = "漢字分解:";

export type KanjiRelatedData = {
    relatedWords: string[];
    components: string[];
};

let cachedWordMap: Map<string, KanjiRelatedData> | null = null;

export async function getRelatedDataForKanji(
    character: string,
): Promise<KanjiRelatedData> {
    if (!cachedWordMap) {
        cachedWordMap = await loadRelatedWordMap();
    }

    return (
        cachedWordMap.get(character) ?? {
            relatedWords: [],
            components: [],
        }
    );
}

export function parseKanjiRelatedData(rawItems: unknown[]): KanjiRelatedData {
    const relatedWords: string[] = [];
    const components: string[] = [];
    let readingComponents = false;

    for (const item of rawItems) {
        if (typeof item !== "string") {
            continue;
        }

        const value = item.trim();
        if (!value) {
            continue;
        }
        if (value === KANJI_DECOMPOSITION_MARKER) {
            readingComponents = true;
            continue;
        }

        if (readingComponents) {
            components.push(value);
        } else {
            relatedWords.push(value);
        }
    }

    return {
        relatedWords: [...new Set(relatedWords)],
        components: [...new Set(components)],
    };
}

async function loadRelatedWordMap(): Promise<Map<string, KanjiRelatedData>> {
    const jsonText = await readArchiveText(
        JPDB_KANJI_ARCHIVE,
        JPDB_KANJI_BANK_FILE,
    );
    const rawEntries = JSON.parse(jsonText) as unknown[];
    const wordMap = new Map<string, KanjiRelatedData>();

    for (const entry of rawEntries) {
        if (!Array.isArray(entry) || typeof entry[0] !== "string") {
            continue;
        }

        const relatedData = Array.isArray(entry[4])
            ? parseKanjiRelatedData(entry[4])
            : { relatedWords: [], components: [] };
        wordMap.set(entry[0], relatedData);
    }

    return wordMap;
}
