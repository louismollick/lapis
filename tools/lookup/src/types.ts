export type LookupCliInputItem = {
    noteId: number;
    expression: string;
};

export type LookupCliInput = {
    items: LookupCliInputItem[];
    maxWordsPerKanji?: number;
    definitionDictionaryNames?: string[];
    frequencyDictionaryNames?: string[];
};

export type LookupFrequencyPayload = {
    value: number | null;
    source: string | null;
};

export type LookupRelatedWordPayload = {
    term: string;
    reading: string;
    frequency: LookupFrequencyPayload;
    entryHtml: string;
};

export type LookupKanjiPayload = {
    char: string;
    relatedWords: LookupRelatedWordPayload[];
};

export type LookupCardPayload = {
    version: 1;
    expression: string;
    kanji: LookupKanjiPayload[];
};

export type LookupCliResultItem = {
    noteId: number;
    payload: LookupCardPayload;
    warnings: string[];
};

export type LookupCliOutput = {
    results: LookupCliResultItem[];
};
