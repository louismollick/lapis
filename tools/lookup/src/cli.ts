import { stdin as input, stdout as output } from "node:process";
import { runLookup, streamLookupResults } from "./lookup.js";
import type { LookupCliInput } from "./types.js";

async function main(): Promise<void> {
    const payload = await readStdin();
    const parsedInput = JSON.parse(payload) as LookupCliInput;

    if (parsedInput.streamResults) {
        for await (const result of streamLookupResults(parsedInput)) {
            await writeStreamItem(result);
        }
        return;
    }

    const result = await runLookup(parsedInput);
    output.write(`${JSON.stringify(result)}\n`);
}

async function writeStreamItem(value: unknown): Promise<void> {
    const frame = Buffer.from(JSON.stringify(value), "utf8").toString("base64");
    if (!output.write(`${frame}\n`)) {
        await new Promise<void>((resolve) => output.once("drain", resolve));
    }
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
