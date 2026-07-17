// Splits raw assistant output into reasoning ("thinking") and the final answer.
//
// Reasoning models (DeepSeek-R1 distills, Qwen, Phi, etc.) emit their chain of
// thought wrapped in <think>...</think> before the actual answer. Rendered
// raw, that reasoning leaked into the chat bubble — which is the "it gives
// thinking, why?" bug. We pull it out so the UI can hide it behind a toggle.

export interface ParsedContent {
  thinking: string;
  answer: string;
  // True while a <think> block is still open (closing tag not yet streamed).
  thinkingInProgress: boolean;
}

// Some models use <think>, others use <thinking>. Match either.
const OPEN = /<think(?:ing)?>/i;
const CLOSE = /<\/think(?:ing)?>/i;

// Attached document text is appended to a user message (so the model sees it as
// context) after this delimiter. The chat bubble parses it back out to show
// filename chips instead of the raw dumped text.
export const ATTACH_DELIM = "\n\n===LOCALY_ATTACHMENTS===\n";

export function buildUserContent(text: string, files: { name: string; text: string }[]): string {
  if (files.length === 0) return text;
  const blob = files.map((f) => `[file: ${f.name}]\n${f.text}`).join("\n\n");
  return `${text}${ATTACH_DELIM}${blob}`;
}

export function parseUserContent(content: string): { text: string; files: string[] } {
  const idx = content.indexOf(ATTACH_DELIM);
  if (idx === -1) return { text: content, files: [] };
  const text = content.slice(0, idx);
  const blob = content.slice(idx + ATTACH_DELIM.length);
  const files = Array.from(blob.matchAll(/\[file: (.+?)\]/g)).map((m) => m[1]);
  return { text, files };
}

export function parseThinking(raw: string): ParsedContent {
  if (!raw || !OPEN.test(raw)) {
    return { thinking: "", answer: raw || "", thinkingInProgress: false };
  }

  let thinking = "";
  let answer = "";
  let rest = raw;
  let inProgress = false;

  while (rest.length > 0) {
    const open = rest.match(OPEN);
    if (!open || open.index === undefined) {
      answer += rest;
      break;
    }
    // Text before the opening tag is part of the answer.
    answer += rest.slice(0, open.index);
    const afterOpen = rest.slice(open.index + open[0].length);
    const close = afterOpen.match(CLOSE);
    if (!close || close.index === undefined) {
      // Unclosed block: everything remaining is still-streaming reasoning.
      thinking += afterOpen;
      inProgress = true;
      break;
    }
    thinking += afterOpen.slice(0, close.index);
    rest = afterOpen.slice(close.index + close[0].length);
  }

  return {
    thinking: thinking.trim(),
    answer: answer.trim(),
    thinkingInProgress: inProgress,
  };
}
