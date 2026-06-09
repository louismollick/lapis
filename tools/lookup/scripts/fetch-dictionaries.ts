import fs from "node:fs/promises";
import path from "node:path";
import { DICTIONARY_ARCHIVES, DICTIONARY_CACHE_DIR } from "../src/constants.js";

async function main(): Promise<void> {
    await fs.mkdir(DICTIONARY_CACHE_DIR, { recursive: true });

    for (const archive of DICTIONARY_ARCHIVES) {
        const destination = path.join(DICTIONARY_CACHE_DIR, archive.fileName);
        const response = await fetch(archive.url);
        if (!response.ok) {
            throw new Error(
                `Failed to download ${archive.url}: ${response.status} ${response.statusText}`,
            );
        }

        const archiveBuffer = Buffer.from(await response.arrayBuffer());
        await fs.writeFile(destination, archiveBuffer);
        process.stdout.write(`Downloaded ${archive.fileName}\n`);
    }
}

main().catch((error: unknown) => {
    const message =
        error instanceof Error
            ? `${error.message}\n${error.stack ?? ""}`
            : String(error);
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
});
