import fs from "node:fs/promises";
import {
    DEFAULT_DEFINITION_DICTIONARY_NAMES,
    DEFAULT_DICTIONARY_DB_PATH,
    DEFAULT_FREQUENCY_DICTIONARY_NAMES,
} from "./constants.js";
import type { DictionarySummary } from "./yomitan-types.js";

type EnabledDictionary = {
    index: number;
    priority: number;
    alias: string;
    allowSecondarySearches?: boolean;
    partsOfSpeechFilter?: boolean;
    useDeinflections?: boolean;
};

export async function ensureDictionaryDatabasePresent(
    databasePath = DEFAULT_DICTIONARY_DB_PATH,
): Promise<void> {
    try {
        await fs.access(databasePath);
    } catch (_error) {
        throw new Error(
            `Missing dictionary database: ${databasePath}. Run "npm run build && npm run prepare-database" in tools/lookup first.`,
        );
    }
}

export function buildTermDictionaryMap(
    dictionaryInfo: DictionarySummary[],
): Map<string, EnabledDictionary> {
    const map = new Map<string, EnabledDictionary>();

    dictionaryInfo.forEach((dictionary, index) => {
        const termCount = dictionary.counts?.terms?.total ?? 0;
        const termMetaCount = Object.values(
            dictionary.counts?.termMeta ?? {},
        ).reduce((total, value) => total + value, 0);
        if (termCount === 0 && termMetaCount === 0) {
            return;
        }

        map.set(dictionary.title, {
            index,
            priority: 0,
            alias: dictionary.title,
            allowSecondarySearches: true,
            partsOfSpeechFilter: false,
            useDeinflections: true,
        });
    });

    return map;
}

export function buildKanjiDictionaryMap(
    dictionaryInfo: DictionarySummary[],
): Map<string, EnabledDictionary> {
    const map = new Map<string, EnabledDictionary>();

    dictionaryInfo.forEach((dictionary, index) => {
        const kanjiCount = dictionary.counts?.kanji?.total ?? 0;
        if (kanjiCount === 0) {
            return;
        }

        map.set(dictionary.title, {
            index,
            priority: 0,
            alias: dictionary.title,
        });
    });

    return map;
}

export function buildDictionaryStylesMap(
    dictionaryInfo: DictionarySummary[],
): Map<string, string> {
    return new Map(
        dictionaryInfo.map((dictionary) => [
            dictionary.title,
            dictionary.styles ?? "",
        ]),
    );
}

export function selectPreferredDictionaryTitle(
    availableTitles: string[],
    preferredNames: string[] | undefined,
): string | null {
    const normalizedPreferred = (
        preferredNames && preferredNames.length > 0
            ? preferredNames
            : DEFAULT_DEFINITION_DICTIONARY_NAMES
    ).map(normalizeFragment);

    for (const fragment of normalizedPreferred) {
        const match = availableTitles.find((title) =>
            normalizeFragment(title).includes(fragment),
        );
        if (match) {
            return match;
        }
    }

    return availableTitles[0] ?? null;
}

export function selectPreferredFrequency(
    availableFrequencies: {
        dictionary: string;
        dictionaryAlias: string;
        frequency: number;
    }[],
    preferredNames: string[] | undefined,
): { value: number | null; source: string | null } {
    const normalizedPreferred = (
        preferredNames && preferredNames.length > 0
            ? preferredNames
            : DEFAULT_FREQUENCY_DICTIONARY_NAMES
    ).map(normalizeFragment);

    for (const fragment of normalizedPreferred) {
        const match = availableFrequencies.find(
            (frequency) =>
                normalizeFragment(frequency.dictionary).includes(fragment) ||
                normalizeFragment(frequency.dictionaryAlias).includes(fragment),
        );
        if (match) {
            return {
                value: match.frequency,
                source: match.dictionaryAlias || match.dictionary,
            };
        }
    }

    const fallback = availableFrequencies[0];
    return {
        value: fallback?.frequency ?? null,
        source: fallback
            ? fallback.dictionaryAlias || fallback.dictionary
            : null,
    };
}

export function normalizeDictionaryTitle(value: string): string {
    const lowered = value.toLowerCase();
    if (lowered.includes("jitendex")) {
        return "jitendex";
    }
    if (lowered.includes("jmdict")) {
        return "jmdict";
    }
    return lowered;
}

function normalizeFragment(value: string): string {
    return value.trim().toLowerCase();
}
