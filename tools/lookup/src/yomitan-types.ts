export type DictionarySummary = {
    title: string;
    styles?: string;
    counts?: {
        terms?: { total: number };
        termMeta?: Record<string, number>;
        kanji?: { total: number };
    };
};

export type TermFrequency = {
    dictionary: string;
    dictionaryAlias: string;
    frequency: number;
};

export type TermHeadword = {
    term: string;
    reading: string;
};

export type TermDefinition = {
    dictionary: string;
    dictionaryAlias: string;
};

export type TermDictionaryEntry = {
    headwords: TermHeadword[];
    definitions: TermDefinition[];
    frequencies: TermFrequency[];
};

export type KanjiDictionaryEntry = {
    dictionary: string;
    dictionaryAlias: string;
    onyomi: string[];
    kunyomi: string[];
    definitions: string[];
};

export type FindTermsResult = {
    entries: TermDictionaryEntry[];
    originalTextLength: number;
};

export interface YomitanCoreLike {
    initialize(): Promise<void>;
    dispose(): Promise<void>;
    importDictionary(archive: ArrayBuffer): Promise<unknown>;
    getDictionaryInfo(): Promise<DictionarySummary[]>;
    findTerms(
        text: string,
        config: {
            enabledDictionaryMap: Map<string, unknown>;
            options?: Record<string, unknown>;
        },
    ): Promise<FindTermsResult>;
    findKanji(
        text: string,
        config: {
            enabledDictionaryMap: Map<string, unknown>;
        },
    ): Promise<KanjiDictionaryEntry[]>;
}
