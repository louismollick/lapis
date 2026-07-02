import type { YomitanCoreLike } from "./yomitan-types.js";

export async function createYomitanCore(
    databasePath: string,
): Promise<YomitanCoreLike> {
    const [{ default: YomitanCore }, { createNodeSqliteDictionaryDB }] =
        await Promise.all([
            import("yomitan-core"),
            import("yomitan-core/database/node-sqlite"),
        ]);
    return new YomitanCore({
        storageAdapter: createNodeSqliteDictionaryDB(databasePath),
    }) as YomitanCoreLike;
}
