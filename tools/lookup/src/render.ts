import { selectPreferredDictionaryTitle } from "./dictionaries.js";
import type {
    KanjiDictionaryEntry,
    TermDictionaryEntry,
} from "./yomitan-types.js";

type LookupTag = {
    name?: string;
};

type LookupNode =
    | string
    | LookupElement
    | LookupStructuredContent
    | LookupTextContent
    | LookupImageContent
    | LookupNode[];

type LookupElement = {
    tag?: string;
    content?: LookupNode;
    style?: Record<string, string | number>;
    lang?: string;
    title?: string;
    href?: string;
    data?: Record<string, unknown>;
};

type LookupStructuredContent = {
    type: "structured-content";
    content: LookupNode;
};

type LookupTextContent = {
    type: "text";
    text: string;
};

type LookupImageContent = {
    type: "image";
};

type LookupDefinition = {
    dictionary?: string;
    dictionaryAlias?: string;
    tags?: LookupTag[];
    entries?: LookupNode[];
};

export async function renderSelectedEntryHtml(
    entry: TermDictionaryEntry,
    dictionaryStylesMap: Map<string, string>,
    preferredDefinitionNames: string[] | undefined,
): Promise<string> {
    const definitions = entry.definitions as LookupDefinition[];
    const availableTitles = [
        ...new Set(
            definitions.map(
                (definition) =>
                    definition.dictionaryAlias || definition.dictionary || "",
            ),
        ),
    ].filter(Boolean);
    const selectedTitle = selectPreferredDictionaryTitle(
        availableTitles,
        preferredDefinitionNames,
    );
    const selectedDefinitions = selectedTitle
        ? definitions.filter(
              (definition) =>
                  (definition.dictionaryAlias || definition.dictionary) ===
                  selectedTitle,
          )
        : definitions;

    if (selectedDefinitions.length === 0) {
        return '<div class="lapis-lookup-empty">No dictionary definition available.</div>';
    }

    const entryHtml = selectedDefinitions
        .map((definition) => renderDefinition(definition))
        .join("");
    const styles = selectedTitle
        ? (dictionaryStylesMap.get(selectedTitle) ?? "").trim()
        : "";

    return `
        <div class="yomitan-glossary">
            ${entryHtml}
            ${styles ? `<style>${styles}</style>` : ""}
        </div>
    `.trim();
}

export function renderFallbackKanjiHtml(entry: KanjiDictionaryEntry): string {
    const definitions = entry.definitions
        .map((definition) => `<li>${escapeHtml(definition)}</li>`)
        .join("");
    const readings = [
        ...entry.onyomi.map((reading) => `<span>${escapeHtml(reading)}</span>`),
        ...entry.kunyomi.map(
            (reading) => `<span>${escapeHtml(reading)}</span>`,
        ),
    ].join(" ");

    return `
        <div class="yomitan-glossary">
            ${readings ? `<div class="lapis-lookup-fallback-readings">${readings}</div>` : ""}
            ${definitions ? `<ul>${definitions}</ul>` : "<div>No kanji definitions available.</div>"}
        </div>
    `.trim();
}

function renderDefinition(definition: LookupDefinition): string {
    const tags = (definition.tags ?? [])
        .map((tag) =>
            tag.name
                ? `<span class="lapis-lookup-definition-tag">${escapeHtml(tag.name)}</span>`
                : "",
        )
        .join("");
    const entries = (definition.entries ?? [])
        .map((item) => renderLookupNode(item))
        .join("");

    return `
        <section class="lapis-lookup-definition-entry">
            ${tags ? `<div class="lapis-lookup-definition-tags">${tags}</div>` : ""}
            ${entries || '<div class="lapis-lookup-empty">No definition content available.</div>'}
        </section>
    `.trim();
}

function renderLookupNode(node: LookupNode): string {
    if (typeof node === "string") {
        return escapeHtml(node).replaceAll("\n", "<br>");
    }

    if (Array.isArray(node)) {
        return node.map((item) => renderLookupNode(item)).join("");
    }

    if (!node || typeof node !== "object") {
        return "";
    }

    if ("type" in node) {
        switch (node.type) {
            case "structured-content":
                return renderLookupNode(node.content);
            case "text":
                return escapeHtml(node.text).replaceAll("\n", "<br>");
            case "image":
                return '<div class="lapis-lookup-empty">Image content omitted.</div>';
            default:
                return "";
        }
    }

    return renderLookupElement(node);
}

function renderLookupElement(node: LookupElement): string {
    const tag = sanitizeTag(node.tag);
    if (!tag) {
        return renderLookupNode(node.content ?? "");
    }

    if (tag === "br") {
        return "<br>";
    }

    const attributes = buildAttributes(node);
    const content = renderLookupNode(node.content ?? "");
    return `<${tag}${attributes}>${content}</${tag}>`;
}

function buildAttributes(node: LookupElement): string {
    const attributes: string[] = [];
    const className = getClassName(node.data);
    if (className) {
        attributes.push(` class="${escapeHtml(className)}"`);
    }
    if (node.lang) {
        attributes.push(` lang="${escapeHtml(node.lang)}"`);
    }
    if (node.title) {
        attributes.push(` title="${escapeHtml(node.title)}"`);
    }
    if (node.href) {
        attributes.push(` href="${escapeHtml(node.href)}"`);
        attributes.push(' target="_blank" rel="noopener noreferrer"');
    }

    const style = serializeStyle(node.style);
    if (style) {
        attributes.push(` style="${escapeHtml(style)}"`);
    }

    attributes.push(...buildDataAttributes(node.data));

    return attributes.join("");
}

function getClassName(data: Record<string, unknown> | undefined): string {
    if (!data) {
        return "";
    }

    const value = data.class;
    return typeof value === "string" ? value : "";
}

function serializeStyle(
    style: Record<string, string | number> | undefined,
): string {
    if (!style) {
        return "";
    }

    return Object.entries(style)
        .map(([key, value]) => `${camelToKebab(key)}:${String(value)}`)
        .join(";");
}

function buildDataAttributes(
    data: Record<string, unknown> | undefined,
): string[] {
    if (!data) {
        return [];
    }

    return Object.entries(data).flatMap(([key, value]) => {
        if (
            key === "class" ||
            !(
                typeof value === "string" ||
                typeof value === "number" ||
                typeof value === "boolean"
            )
        ) {
            return [];
        }

        return [` data-sc-${camelToKebab(key)}="${escapeHtml(String(value))}"`];
    });
}

function camelToKebab(value: string): string {
    return value.replace(
        /[A-Z]/g,
        (character) => `-${character.toLowerCase()}`,
    );
}

function sanitizeTag(tag: string | undefined): string {
    if (!tag) {
        return "span";
    }

    const normalized = tag.toLowerCase();
    return ALLOWED_TAGS.has(normalized) ? normalized : "span";
}

function escapeHtml(value: string): string {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

const ALLOWED_TAGS = new Set([
    "a",
    "blockquote",
    "br",
    "code",
    "dd",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "i",
    "li",
    "ol",
    "p",
    "rp",
    "rt",
    "ruby",
    "s",
    "section",
    "small",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
]);
