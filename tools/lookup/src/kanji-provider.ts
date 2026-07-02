import type { KanjiDictionaryEntry, YomitanCoreLike } from "./yomitan-types.js";

const KANJI_DECOMPOSITION_MARKER = "漢字分解:";
const JPDB_DICTIONARY_FRAGMENT = "jpdb";

export type KanjiRelatedData = {
    relatedWords: string[];
    components: string[];
};

export async function getRelatedDataForKanji(
    character: string,
    core: YomitanCoreLike,
    enabledDictionaryMap: Map<string, unknown>,
): Promise<KanjiRelatedData> {
    const entries = await core.findKanji(character, { enabledDictionaryMap });
    const entry = selectRelatedDataKanjiEntry(entries);
    return entry
        ? parseKanjiRelatedData(entry.definitions)
        : { relatedWords: [], components: [] };
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

function selectRelatedDataKanjiEntry(
    entries: KanjiDictionaryEntry[],
): KanjiDictionaryEntry | null {
    return (
        entries.find((entry) =>
            `${entry.dictionary} ${entry.dictionaryAlias}`
                .toLowerCase()
                .includes(JPDB_DICTIONARY_FRAGMENT),
        ) ??
        entries[0] ??
        null
    );
}
