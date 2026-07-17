import React from "react";

// Lightweight, dependency-free Markdown renderer.
//
// Renders to React text nodes only (never dangerouslySetInnerHTML), so it is
// XSS-safe by construction. Supports the subset that actually shows up in LLM
// chat: fenced code, headings, bullet/numbered lists, blockquotes, rules, and
// inline bold/italic/code/links. Anything unrecognised falls back to plain text.

interface MarkdownProps {
  text: string;
}

// ---- inline parsing -------------------------------------------------------

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const parts = text.split(INLINE);
  parts.forEach((part, i) => {
    if (!part) return;
    const key = `${keyPrefix}-${i}`;
    if ((part.startsWith("**") && part.endsWith("**")) || (part.startsWith("__") && part.endsWith("__"))) {
      nodes.push(<strong key={key}>{part.slice(2, -2)}</strong>);
    } else if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_"))) {
      nodes.push(<em key={key}>{part.slice(1, -1)}</em>);
    } else if (part.startsWith("`") && part.endsWith("`")) {
      nodes.push(<code key={key} style={styles.inlineCode}>{part.slice(1, -1)}</code>);
    } else {
      const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (link) {
        const href = link[2];
        const safe = /^https?:\/\//i.test(href) ? href : undefined;
        nodes.push(
          <a key={key} href={safe} target="_blank" rel="noreferrer noopener" style={styles.link}>
            {link[1]}
          </a>
        );
      } else {
        nodes.push(<React.Fragment key={key}>{part}</React.Fragment>);
      }
    }
  });
  return nodes;
}

// ---- code block with copy -------------------------------------------------

const CodeBlock: React.FC<{ code: string; lang?: string }> = ({ code, lang }) => {
  const [copied, setCopied] = React.useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div style={styles.codeWrap}>
      <div style={styles.codeHeader}>
        <span style={styles.codeLang}>{lang || "code"}</span>
        <button type="button" onClick={copy} style={styles.copyBtn}>
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre style={styles.pre}>
        <code>{code}</code>
      </pre>
    </div>
  );
};

// ---- block parsing --------------------------------------------------------

export const Markdown: React.FC<MarkdownProps> = ({ text }) => {
  const blocks: React.ReactNode[] = [];
  // Split on fenced code first so their contents are never re-parsed.
  const segments = text.split(/(```[\s\S]*?```)/g);

  segments.forEach((seg, si) => {
    if (seg.startsWith("```")) {
      const nl = seg.indexOf("\n");
      const lang = seg.slice(3, nl).trim();
      const code = seg.slice(nl + 1, seg.lastIndexOf("```")).replace(/\n$/, "");
      blocks.push(<CodeBlock key={`c-${si}`} code={code} lang={lang} />);
      return;
    }

    const lines = seg.split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const key = `b-${si}-${i}`;

      if (!line.trim()) { i++; continue; }

      // Headings
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        const level = Math.min(h[1].length + 2, 6);
        const tag = `h${level}`;
        blocks.push(
          React.createElement(tag, { key, style: styles.heading }, renderInline(h[2], key))
        );
        i++;
        continue;
      }

      // Horizontal rule
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
        blocks.push(<hr key={key} style={styles.hr} />);
        i++;
        continue;
      }

      // Blockquote
      if (line.startsWith(">")) {
        const quote: string[] = [];
        while (i < lines.length && lines[i].startsWith(">")) {
          quote.push(lines[i].replace(/^>\s?/, ""));
          i++;
        }
        blocks.push(
          <blockquote key={key} style={styles.quote}>{renderInline(quote.join(" "), key)}</blockquote>
        );
        continue;
      }

      // Unordered / ordered lists
      if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\.\s+/.test(line);
        const items: React.ReactNode[] = [];
        while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
          const content = lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, "");
          items.push(<li key={`${key}-${i}`}>{renderInline(content, `${key}-${i}`)}</li>);
          i++;
        }
        blocks.push(
          ordered
            ? <ol key={key} style={styles.list}>{items}</ol>
            : <ul key={key} style={styles.list}>{items}</ul>
        );
        continue;
      }

      // Paragraph: gather consecutive non-blank, non-special lines.
      const para: string[] = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !/^(#{1,6}\s|>|\s*([-*+]|\d+\.)\s)/.test(lines[i]) &&
        !/^(-{3,}|\*{3,}|_{3,})$/.test(lines[i].trim())
      ) {
        para.push(lines[i]);
        i++;
      }
      blocks.push(<p key={key} style={styles.paragraph}>{renderInline(para.join("\n"), key)}</p>);
    }
  });

  return <>{blocks}</>;
};

const styles: { [key: string]: React.CSSProperties } = {
  paragraph: { margin: "0 0 10px", whiteSpace: "pre-wrap", lineHeight: 1.6 },
  heading: { margin: "14px 0 8px", fontWeight: 600, lineHeight: 1.3 },
  list: { margin: "0 0 10px", paddingLeft: "22px", lineHeight: 1.6 },
  quote: {
    margin: "0 0 10px",
    padding: "6px 14px",
    borderLeft: "3px solid var(--primary)",
    color: "#c4c4cc",
    background: "rgba(255,255,255,0.03)",
  },
  hr: { border: "none", borderTop: "1px solid var(--panel-border)", margin: "14px 0" },
  inlineCode: {
    background: "rgba(255,255,255,0.08)",
    padding: "1px 5px",
    borderRadius: "4px",
    fontSize: "0.9em",
    fontFamily: "var(--font-mono, monospace)",
  },
  link: { color: "#818cf8", textDecoration: "underline" },
  codeWrap: {
    margin: "10px 0",
    border: "1px solid var(--panel-border)",
    borderRadius: "8px",
    overflow: "hidden",
    background: "rgba(0,0,0,0.35)",
  },
  codeHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "4px 10px",
    background: "rgba(255,255,255,0.04)",
    borderBottom: "1px solid var(--panel-border)",
  },
  codeLang: { fontSize: "11px", color: "#71717a", textTransform: "uppercase", letterSpacing: "0.04em" },
  copyBtn: {
    fontSize: "11px",
    color: "#a1a1aa",
    background: "transparent",
    border: "1px solid var(--panel-border)",
    borderRadius: "4px",
    padding: "2px 8px",
    cursor: "pointer",
  },
  pre: {
    margin: 0,
    padding: "12px 14px",
    overflowX: "auto",
    fontSize: "13px",
    lineHeight: 1.5,
    fontFamily: "var(--font-mono, monospace)",
  },
};
