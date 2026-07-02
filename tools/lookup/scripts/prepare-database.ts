import fs from "node:fs/promises";
import path from "node:path";
import Database from "better-sqlite3";
import {
    DEFAULT_DICTIONARY_DB_PATH,
    DICTIONARY_ARCHIVES,
    DICTIONARY_CACHE_DIR,
    DICTIONARY_DATA_DIR,
} from "../src/constants.js";
import { createYomitanCore } from "../src/yomitan.js";

async function main(): Promise<void> {
    await ensureDictionaryArchivesPresent();
    await fs.mkdir(DICTIONARY_DATA_DIR, { recursive: true });

    const temporaryPath = `${DEFAULT_DICTIONARY_DB_PATH}.tmp-${process.pid}`;
    await removeIfExists(temporaryPath);
    await removeSqliteSidecars(temporaryPath);

    const core = await createYomitanCore(temporaryPath);
    await core.initialize();
    try {
        for (const archive of DICTIONARY_ARCHIVES) {
            const archiveBuffer = await fs.readFile(
                path.join(DICTIONARY_CACHE_DIR, archive.fileName),
            );
            await core.importDictionary(bufferToArrayBuffer(archiveBuffer));
            process.stdout.write(`Imported ${archive.fileName}\n`);
        }
    } finally {
        await core.dispose();
    }

    vacuumDatabase(temporaryPath);
    await removeSqliteSidecars(DEFAULT_DICTIONARY_DB_PATH);
    await fs.rename(temporaryPath, DEFAULT_DICTIONARY_DB_PATH);
    await removeSqliteSidecars(temporaryPath);
    process.stdout.write(`Prepared ${DEFAULT_DICTIONARY_DB_PATH}\n`);
}

async function ensureDictionaryArchivesPresent(): Promise<void> {
    const missing: string[] = [];
    for (const archive of DICTIONARY_ARCHIVES) {
        try {
            await fs.access(path.join(DICTIONARY_CACHE_DIR, archive.fileName));
        } catch (_error) {
            missing.push(archive.fileName);
        }
    }
    if (missing.length > 0) {
        throw new Error(
            `Missing dictionary archives: ${missing.join(", ")}. Run "npm run build && npm run fetch-dictionaries" in tools/lookup first.`,
        );
    }
}

async function removeIfExists(filePath: string): Promise<void> {
    try {
        await fs.rm(filePath, { force: true });
    } catch (_error) {
        // Best-effort cleanup only.
    }
}

async function removeSqliteSidecars(filePath: string): Promise<void> {
    await Promise.all([
        removeIfExists(`${filePath}-shm`),
        removeIfExists(`${filePath}-wal`),
    ]);
}

function vacuumDatabase(filePath: string): void {
    const database = new Database(filePath);
    try {
        database.pragma("wal_checkpoint(TRUNCATE)");
        database.exec("VACUUM");
    } finally {
        database.close();
    }
}

function bufferToArrayBuffer(buffer: Buffer): ArrayBuffer {
    return Uint8Array.from(buffer).buffer;
}

main().catch((error: unknown) => {
    const message =
        error instanceof Error
            ? `${error.message}\n${error.stack ?? ""}`
            : String(error);
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
});
