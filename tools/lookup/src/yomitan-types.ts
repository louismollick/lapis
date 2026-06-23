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

export type BuildAnkiNoteResult =
    | {
          status: "ok";
          fields: Record<string, string>;
          errors: string[];
      }
    | {
          status: "no-entry";
          errors: string[];
      };

export interface YomitanCoreLike {
    initialize(): Promise<void>;
    dispose(): Promise<void>;
    importDictionary(archive: ArrayBuffer): Promise<unknown>;
    getDictionaryInfo(): Promise<DictionarySummary[]>;
    buildAnkiNoteFromTerm(input: {
        term: string;
        enabledDictionaryMap: Map<string, unknown>;
        dictionaries: { name: string; enabled: boolean }[];
        dictionaryInfo: DictionarySummary[];
        resultOutputMode?: "split" | "group" | "merge";
        dictionaryStylesMap?: Map<string, string>;
        cardFormat: {
            deck: string;
            model: string;
            fields: Record<string, { value: string }>;
        };
        context: {
            url: string;
            query: string;
            fullQuery: string;
            documentTitle: string;
        };
        options?: Record<string, unknown>;
    }): Promise<BuildAnkiNoteResult>;
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
