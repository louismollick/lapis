import { stdin as input, stdout as output } from "node:process";
import { runLookup } from "./lookup.js";
import type { LookupCliInput } from "./types.js";

async function main(): Promise<void> {
    const payload = await readStdin();
    const parsedInput = JSON.parse(payload) as LookupCliInput;
    const result = await runLookup(parsedInput);
    output.write(`${JSON.stringify(result)}\n`);
}

async function readStdin(): Promise<string> {
    const chunks: Buffer[] = [];
    for await (const chunk of input) {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }

    return Buffer.concat(chunks).toString("utf8");
}

main().catch((error: unknown) => {
    const message =
        error instanceof Error
            ? `${error.message}\n${error.stack ?? ""}`
            : String(error);
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
});
