import type { YomitanCoreLike } from "./yomitan-types.js";

export async function createYomitanCore(
    databaseName: string,
): Promise<YomitanCoreLike> {
    const module = await import("yomitan-core");
    const CoreClass = module.default;
    return new CoreClass({ databaseName }) as YomitanCoreLike;
}
