import {
    DEFAULT_DEFINITION_DICTIONARY_NAMES,
    DEFAULT_DICTIONARY_DB_PATH,
    DEFAULT_FREQUENCY_DICTIONARY_NAMES,
    DEFAULT_MAX_WORDS_PER_KANJI,
} from "./constants.js";
import {
    buildDictionaryStylesMap,
    buildKanjiDictionaryMap,
    buildTermDictionaryMap,
    ensureDictionaryDatabasePresent,
    selectPreferredDictionaryTitle,
    selectPreferredFrequency,
} from "./dictionaries.js";
import { getRelatedDataForKanji } from "./kanji-provider.js";
import { renderFallbackKanjiHtml } from "./render.js";
import type {
    LookupCardPayload,
    LookupCliInput,
    LookupCliInputItem,
    LookupCliOutput,
    LookupCliProgressItem,
    LookupCliResultItem,
    LookupCliStreamItem,
    LookupKanjiPayload,
    LookupRelatedWordPayload,
    LookupSharedTermsPayload,
} from "./types.js";
import type {
    AnkiFieldRenderInput,
    BuildAnkiNoteResult,
    DictionarySummary,
    KanjiDictionaryEntry,
    TermDictionaryEntry,
    YomitanCoreLike,
} from "./yomitan-types.js";
import { createYomitanCore } from "./yomitan.js";

type LookupRuntime = {
    core: YomitanCoreLike;
    dictionaryInfo: DictionarySummary[];
    dictionaryStylesMap: Map<string, string>;
    termDictionaryMap: ReturnType<typeof buildTermDictionaryMap>;
    kanjiDictionaryMap: ReturnType<typeof buildKanjiDictionaryMap>;
    cache: LookupCache;
};

type LookupOptions = {
    maxWordsPerKanji: number;
    definitionDictionaryNames: string[];
    frequencyDictionaryNames: string[];
};

type CachedValue<T> = {
    value: T;
    warnings: string[];
};

type LookupPayloadBuild = {
    payload: LookupCardPayload;
    sharedTerms: LookupSharedTermsPayload;
};

type LookupKanjiBuild = {
    kanji: LookupKanjiPayload;
    sharedTerms: LookupSharedTermsPayload;
};

type LookupCache = {
    generatedFieldsByExpression: Map<string, Promise<BuildAnkiNoteResult>>;
    payloadByExpression: Map<string, Promise<CachedValue<LookupPayloadBuild>>>;
    kanjiByCharacter: Map<string, Promise<CachedValue<LookupKanjiBuild>>>;
    relatedWordByTerm: Map<
        string,
        Promise<CachedValue<LookupRelatedWordPayload>>
    >;
};

export function createLookupCache(): LookupCache {
    return {
        generatedFieldsByExpression: new Map(),
        payloadByExpression: new Map(),
        kanjiByCharacter: new Map(),
        relatedWordByTerm: new Map(),
    };
}

export async function runLookup(
    input: LookupCliInput,
): Promise<LookupCliOutput> {
    const databasePath = input.dictionaryDbPath ?? DEFAULT_DICTIONARY_DB_PATH;
    await ensureDictionaryDatabasePresent(databasePath);
    const runtime = await createRuntime(databasePath);

    try {
        const results: LookupCliResultItem[] = [];
        const options = buildLookupOptions(input);
        for (const item of input.items) {
            results.push(await buildLookupResult(item, runtime, options));
        }

        return { results };
    } finally {
        await runtime.core.dispose();
    }
}

export async function* streamLookupResults(
    input: LookupCliInput,
): AsyncGenerator<LookupCliStreamItem> {
    const databasePath = input.dictionaryDbPath ?? DEFAULT_DICTIONARY_DB_PATH;
    await ensureDictionaryDatabasePresent(databasePath);
    const runtime = await createRuntime(databasePath);

    try {
        const options = buildLookupOptions(input);
        for (const [index, item] of input.items.entries()) {
            yield buildProgressItem(item, index, input.items.length);
            yield await buildLookupResult(item, runtime, options);
        }
    } finally {
        await runtime.core.dispose();
    }
}

export function buildProgressItem(
    item: LookupCliInputItem,
    index: number,
    total: number,
): LookupCliProgressItem {
    return {
        type: "progress",
        completed: index,
        total,
        noteId: item.noteId,
        expression: item.expression,
    };
}

function buildLookupOptions(input: LookupCliInput): LookupOptions {
    return {
        maxWordsPerKanji: input.maxWordsPerKanji ?? DEFAULT_MAX_WORDS_PER_KANJI,
        definitionDictionaryNames:
            input.definitionDictionaryNames ??
            DEFAULT_DEFINITION_DICTIONARY_NAMES,
        frequencyDictionaryNames:
            input.frequencyDictionaryNames ??
            DEFAULT_FREQUENCY_DICTIONARY_NAMES,
    };
}

async function createRuntime(databasePath: string): Promise<LookupRuntime> {
    const core = await createYomitanCore(databasePath);
    await core.initialize();

    const dictionaryInfo = await core.getDictionaryInfo();
    return {
        core,
        dictionaryInfo,
        dictionaryStylesMap: buildDictionaryStylesMap(dictionaryInfo),
        termDictionaryMap: buildTermDictionaryMap(dictionaryInfo),
        kanjiDictionaryMap: buildKanjiDictionaryMap(dictionaryInfo),
        cache: createLookupCache(),
    };
}

export async function buildLookupResult(
    item: LookupCliInputItem,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<LookupCliResultItem> {
    const { noteId, expression, mode } = item;
    const warnings: string[] = [];
    let generatedFields: Record<string, string> | undefined;

    if (mode === "convertLegacy") {
        const generatedNote = await generateLapisFieldsCached(
            expression,
            runtime,
        );
        if (generatedNote.status === "no-entry") {
            return {
                noteId,
                mode,
                status: "skipped",
                expression,
                warnings: [
                    `Skipped note ${noteId}: no Yomitan entry for "${expression}".`,
                    ...generatedNote.errors,
                ],
            };
        }
        warnings.push(...generatedNote.errors);
        generatedFields = generatedNote.fields;
    }

    const cachedPayload = await buildLookupPayloadCached(
        expression,
        runtime,
        options,
    );
    warnings.push(...cachedPayload.warnings);

    return {
        noteId,
        mode,
        status: "ok",
        expression,
        generatedFields,
        payload: cachedPayload.value.payload,
        sharedTerms: cachedPayload.value.sharedTerms,
        warnings,
    };
}

function buildLookupPayloadCached(
    expression: string,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<CachedValue<LookupPayloadBuild>> {
    const cacheKey = `${expression}\0${options.maxWordsPerKanji}\0${options.definitionDictionaryNames.join("\0")}\0${options.frequencyDictionaryNames.join("\0")}`;
    let cached = runtime.cache.payloadByExpression.get(cacheKey);
    if (!cached) {
        cached = buildLookupPayload(expression, runtime, options);
        runtime.cache.payloadByExpression.set(cacheKey, cached);
    }
    return cached;
}

async function buildLookupPayload(
    expression: string,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<CachedValue<LookupPayloadBuild>> {
    const warnings: string[] = [];
    const kanjiCharacters = extractUniqueKanji(expression);
    const sharedTerms: LookupSharedTermsPayload = {};
    const payload: LookupCardPayload = {
        version: 2,
        expression,
        kanji: [],
    };

    for (const character of kanjiCharacters) {
        const cachedKanji = await buildKanjiRelatedWordsCached(
            character,
            runtime,
            options,
        );
        warnings.push(...cachedKanji.warnings);

        payload.kanji.push(cachedKanji.value.kanji);
        Object.assign(sharedTerms, cachedKanji.value.sharedTerms);
    }

    return { value: { payload, sharedTerms }, warnings };
}

function buildKanjiRelatedWordsCached(
    character: string,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<CachedValue<LookupKanjiBuild>> {
    const cacheKey = `${character}\0${options.maxWordsPerKanji}\0${options.definitionDictionaryNames.join("\0")}\0${options.frequencyDictionaryNames.join("\0")}`;
    let cached = runtime.cache.kanjiByCharacter.get(cacheKey);
    if (!cached) {
        cached = buildKanjiRelatedWords(character, runtime, options);
        runtime.cache.kanjiByCharacter.set(cacheKey, cached);
    }
    return cached;
}

async function buildKanjiRelatedWords(
    character: string,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<CachedValue<LookupKanjiBuild>> {
    const warnings: string[] = [];
    const relatedData = await getRelatedDataForKanji(
        character,
        runtime.core,
        runtime.kanjiDictionaryMap,
    );
    const limitedWords = relatedData.relatedWords.slice(
        0,
        options.maxWordsPerKanji,
    );
    const wordRefs: string[] = [];
    const sharedTerms: LookupSharedTermsPayload = {};

    for (const word of limitedWords) {
        const relatedWordPayload = await resolveRelatedWordCached(
            word,
            runtime,
            options,
        );
        warnings.push(...relatedWordPayload.warnings);
        wordRefs.push(word);
        sharedTerms[word] = relatedWordPayload.value;
    }

    return {
        value: {
            kanji: {
                char: character,
                wordRefs,
                components: relatedData.components,
            },
            sharedTerms,
        },
        warnings,
    };
}

async function generateLapisFields(
    expression: string,
    runtime: LookupRuntime,
): Promise<BuildAnkiNoteResult> {
    return runtime.core.buildAnkiNoteFromTerm(
        buildLegacyLapisNoteInput(
            expression,
            runtime.dictionaryInfo,
            runtime.termDictionaryMap,
            runtime.dictionaryStylesMap,
        ),
    );
}

function generateLapisFieldsCached(
    expression: string,
    runtime: LookupRuntime,
): Promise<BuildAnkiNoteResult> {
    let cached = runtime.cache.generatedFieldsByExpression.get(expression);
    if (!cached) {
        cached = generateLapisFields(expression, runtime);
        runtime.cache.generatedFieldsByExpression.set(expression, cached);
    }
    return cached;
}

export function buildLegacyLapisNoteInput(
    expression: string,
    dictionaryInfo: DictionarySummary[],
    termDictionaryMap: ReturnType<typeof buildTermDictionaryMap>,
    dictionaryStylesMap: Map<string, string>,
): Parameters<YomitanCoreLike["buildAnkiNoteFromTerm"]>[0] {
    return {
        term: expression,
        enabledDictionaryMap: termDictionaryMap,
        dictionaries: buildEnabledDictionaries(dictionaryInfo),
        dictionaryInfo,
        resultOutputMode: "group",
        dictionaryStylesMap,
        cardFormat: {
            deck: "Lapis",
            model: "Lapis+Lookup",
            fields: Object.fromEntries(
                Object.entries(buildLapisFieldTemplates(dictionaryInfo)).map(
                    ([fieldName, value]) => [fieldName, { value }],
                ),
            ),
        },
        context: {
            url: "",
            query: expression,
            fullQuery: expression,
            documentTitle: "",
        },
        options: {
            matchType: "exact",
            deinflect: true,
            removeNonJapaneseCharacters: false,
        },
    };
}

function buildLapisFieldTemplates(
    _dictionaryInfo: DictionarySummary[],
): Record<string, string> {
    return {
        Expression: "{expression}",
        ExpressionFurigana: "{furigana-plain}",
        ExpressionReading: "{reading}",
        ExpressionAudio: "{audio}",
        SelectionText: "{popup-selection-text}",
        MainDefinition: "",
        Sentence: "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}",
        Glossary: "{glossary}",
        PitchPosition: "{pitch-accent-positions}",
        PitchCategories: "{pitch-accent-categories}",
        Frequency: "{frequencies}",
        FreqSort: "{frequency-harmonic-rank}",
        MiscInfo: "{document-title}",
    };
}

function resolveRelatedWordCached(
    word: string,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<CachedValue<LookupRelatedWordPayload>> {
    const cacheKey = `${word}\0${options.definitionDictionaryNames.join("\0")}\0${options.frequencyDictionaryNames.join("\0")}`;
    let cached = runtime.cache.relatedWordByTerm.get(cacheKey);
    if (!cached) {
        cached = resolveRelatedWord(word, runtime, options);
        runtime.cache.relatedWordByTerm.set(cacheKey, cached);
    }
    return cached;
}

async function resolveRelatedWord(
    word: string,
    runtime: LookupRuntime,
    options: LookupOptions,
): Promise<CachedValue<LookupRelatedWordPayload>> {
    const warnings: string[] = [];
    const termEntry = await lookupBestTermEntry(word, runtime);
    if (termEntry) {
        const frequency = selectPreferredFrequency(
            termEntry.frequencies.map((item) => ({
                dictionary: item.dictionary,
                dictionaryAlias: item.dictionaryAlias,
                frequency: item.frequency,
            })),
            options.frequencyDictionaryNames,
        );

        return {
            value: {
                term: termEntry.headwords[0]?.term ?? word,
                reading: termEntry.headwords[0]?.reading ?? "",
                frequency,
                entryHtml: await renderRelatedWordEntryHtml(
                    word,
                    runtime.core,
                    runtime.dictionaryInfo,
                    runtime.termDictionaryMap,
                    runtime.dictionaryStylesMap,
                    warnings,
                ),
            },
            warnings,
        };
    }

    if ([...word].length === 1) {
        const kanjiEntry = await lookupBestKanjiEntry(
            word,
            runtime,
            options.definitionDictionaryNames,
        );
        if (kanjiEntry) {
            return {
                value: {
                    term: word,
                    reading: joinKanjiReadings(kanjiEntry),
                    frequency: { value: null, source: null },
                    entryHtml: renderFallbackKanjiHtml(kanjiEntry),
                },
                warnings,
            };
        }
    }

    warnings.push(`No dictionary entry found for related word "${word}".`);
    return {
        value: {
            term: word,
            reading: "",
            frequency: { value: null, source: null },
            entryHtml: `<div class="lapis-lookup-empty">No dictionary entry found for ${escapeHtml(word)}.</div>`,
        },
        warnings,
    };
}
async function lookupBestTermEntry(
    word: string,
    runtime: LookupRuntime,
): Promise<TermDictionaryEntry | null> {
    const lookup = await runtime.core.findTerms(word, {
        enabledDictionaryMap: runtime.termDictionaryMap,
        options: {
            matchType: "exact",
            deinflect: true,
            removeNonJapaneseCharacters: false,
        },
    });

    const entries = lookup.entries;
    if (entries.length === 0) {
        return null;
    }

    return (
        entries.find((entry) =>
            entry.headwords.some((headword) => headword.term === word),
        ) ??
        entries.find((entry) =>
            entry.headwords.some((headword) => headword.term.includes(word)),
        ) ??
        entries[0] ??
        null
    );
}

async function lookupBestKanjiEntry(
    word: string,
    runtime: LookupRuntime,
    preferredDefinitionNames: string[],
): Promise<KanjiDictionaryEntry | null> {
    const entries = await runtime.core.findKanji(word, {
        enabledDictionaryMap: runtime.kanjiDictionaryMap,
    });

    if (entries.length === 0) {
        return null;
    }

    const availableTitles = entries.map(
        (entry) => entry.dictionaryAlias || entry.dictionary,
    );
    const selectedTitle = selectPreferredDictionaryTitle(
        availableTitles,
        preferredDefinitionNames,
    );
    return (
        entries.find(
            (entry) =>
                (entry.dictionaryAlias || entry.dictionary) === selectedTitle,
        ) ??
        entries[0] ??
        null
    );
}

export async function renderRelatedWordEntryHtml(
    word: string,
    core: YomitanCoreLike,
    dictionaryInfo: DictionarySummary[],
    termDictionaryMap: ReturnType<typeof buildTermDictionaryMap>,
    dictionaryStylesMap: Map<string, string>,
    warnings: string[] = [],
): Promise<string> {
    const result = await core.buildAnkiNoteFromTerm(
        buildRelatedWordDefinitionInput(
            word,
            dictionaryInfo,
            termDictionaryMap,
            dictionaryStylesMap,
        ),
    );
    warnings.push(...result.errors);

    if (result.status !== "ok") {
        return '<div class="lapis-lookup-empty">No dictionary definition available.</div>';
    }

    return (
        result.fields.Definition ??
        '<div class="lapis-lookup-empty">No dictionary definition available.</div>'
    );
}

export function buildRelatedWordDefinitionInput(
    word: string,
    dictionaryInfo: DictionarySummary[],
    termDictionaryMap: ReturnType<typeof buildTermDictionaryMap>,
    dictionaryStylesMap: Map<string, string>,
): Parameters<YomitanCoreLike["buildAnkiNoteFromTerm"]>[0] {
    return {
        term: word,
        enabledDictionaryMap: termDictionaryMap,
        dictionaries: buildEnabledDictionaries(dictionaryInfo),
        dictionaryInfo,
        resultOutputMode: "group",
        dictionaryStylesMap,
        cardFormat: {
            deck: "Lapis",
            model: "Lapis+Lookup",
            fields: {
                Definition: {
                    value: "{glossary}",
                },
            },
        },
        context: {
            url: "",
            query: word,
            fullQuery: word,
            documentTitle: "",
        },
        options: {
            matchType: "exact",
            deinflect: true,
            removeNonJapaneseCharacters: false,
        },
    };
}

function buildEnabledDictionaries(
    dictionaryInfo: DictionarySummary[],
): { name: string; enabled: boolean }[] {
    return dictionaryInfo.map((dictionary) => ({
        name: dictionary.title,
        enabled: true,
    }));
}

function extractUniqueKanji(expression: string): string[] {
    const uniqueCharacters = new Set<string>();
    for (const character of expression) {
        if (/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(character)) {
            uniqueCharacters.add(character);
        }
    }
    return [...uniqueCharacters];
}

function joinKanjiReadings(entry: KanjiDictionaryEntry): string {
    return [...entry.onyomi, ...entry.kunyomi].filter(Boolean).join(" / ");
}

function escapeHtml(value: string): string {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
