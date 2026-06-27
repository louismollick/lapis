export type LookupCliInputMode = "lookupOnly" | "convertLegacy";

export type LookupCliInputItem = {
    noteId: number;
    mode: LookupCliInputMode;
    expression: string;
};

export type LookupCliInput = {
    items: LookupCliInputItem[];
    maxWordsPerKanji?: number;
    definitionDictionaryNames?: string[];
    frequencyDictionaryNames?: string[];
    streamResults?: boolean;
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
    wordRefs: string[];
    components?: string[];
};

export type LookupCardPayload = {
    version: 2;
    expression: string;
    kanji: LookupKanjiPayload[];
};

export type LookupSharedTermsPayload = Record<string, LookupRelatedWordPayload>;

export type LookupCliResultItem = {
    noteId: number;
    mode: LookupCliInputMode;
    status: "ok" | "skipped";
    expression: string;
    payload?: LookupCardPayload;
    sharedTerms?: LookupSharedTermsPayload;
    generatedFields?: Record<string, string>;
    warnings: string[];
};

export type LookupCliProgressItem = {
    type: "progress";
    completed: number;
    total: number;
    noteId: number;
    expression: string;
};

export type LookupCliStreamItem = LookupCliProgressItem | LookupCliResultItem;

export type LookupCliOutput = {
    results: LookupCliResultItem[];
};
