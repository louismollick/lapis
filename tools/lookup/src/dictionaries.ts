import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import {
    DEFAULT_DEFINITION_DICTIONARY_NAMES,
    DEFAULT_FREQUENCY_DICTIONARY_NAMES,
    DICTIONARY_ARCHIVES,
    DICTIONARY_CACHE_DIR,
} from "./constants.js";
import type { DictionarySummary, YomitanCoreLike } from "./yomitan-types.js";

type EnabledDictionary = {
    index: number;
    priority: number;
    alias: string;
    allowSecondarySearches?: boolean;
    partsOfSpeechFilter?: boolean;
    useDeinflections?: boolean;
};

const execFileAsync = promisify(execFile);
const ZIP_READ_OPTIONS = {
    encoding: "utf8" as const,
    maxBuffer: 32 * 1024 * 1024,
};

export async function ensureDictionaryArchivesPresent(): Promise<void> {
    for (const archive of DICTIONARY_ARCHIVES) {
        const archivePath = path.join(DICTIONARY_CACHE_DIR, archive.fileName);
        try {
            await fs.access(archivePath);
        } catch (_error) {
            throw new Error(
                `Missing dictionary archive: ${archive.fileName}. Run "node dist/scripts/fetch-dictionaries.js" in tools/lookup first.`,
            );
        }
    }
}

export async function importSuggestedDictionaries(
    core: YomitanCoreLike,
): Promise<DictionarySummary[]> {
    for (const archive of DICTIONARY_ARCHIVES) {
        const archiveBuffer = await fs.readFile(
            path.join(DICTIONARY_CACHE_DIR, archive.fileName),
        );
        await core.importDictionary(bufferToArrayBuffer(archiveBuffer));
    }

    return core.getDictionaryInfo();
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

export async function readArchiveText(
    archiveFileName: string,
    fileNameInArchive: string,
): Promise<string> {
    const unzip = process.platform === "win32" ? "tar" : "unzip";
    if (process.platform === "win32") {
        const archivePath = path.join(DICTIONARY_CACHE_DIR, archiveFileName);
        const { stdout } = await execFileAsync(
            unzip,
            ["-xOf", archivePath, fileNameInArchive],
            ZIP_READ_OPTIONS,
        );
        return stdout;
    }

    const archivePath = path.join(DICTIONARY_CACHE_DIR, archiveFileName);
    const { stdout } = await execFileAsync(
        unzip,
        ["-p", archivePath, fileNameInArchive],
        ZIP_READ_OPTIONS,
    );
    return stdout;
}

function normalizeFragment(value: string): string {
    return value.trim().toLowerCase();
}

function bufferToArrayBuffer(buffer: Buffer): ArrayBuffer {
    return Uint8Array.from(buffer).buffer;
}
