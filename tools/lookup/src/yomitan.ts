import type { YomitanCoreLike } from "./yomitan-types.js";

const YOMITAN_CORE_ENTRY = "/Users/mollicl/personal/yomitan-core/dist/index.js";

export async function createYomitanCore(
    databaseName: string,
): Promise<YomitanCoreLike> {
    const module = await import(YOMITAN_CORE_ENTRY);
    const CoreClass = module.default;
    return new CoreClass({ databaseName }) as YomitanCoreLike;
}
