"use client"

import { Check, Copy } from "lucide-react"
import { Fragment, useMemo, useState, type ReactNode } from "react"

import { cn } from "@/lib/utils"

interface MarkdownRendererProps {
  content: string
  className?: string
}

/**
 * Purely presentational markdown renderer.
 *
 * Deliberately stateless with respect to streaming: it re-renders from whatever
 * `content` currently holds. The previous version kept internal "static" and
 * "animating" buffers and applied a per-word blur, which fought with real token
 * streaming (each delta re-triggered the split) and read its own state inside
 * its effect dependency list.
 */
export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  const blocks = useMemo(() => parseBlocks(content), [content])

  return (
    <div className={cn("space-y-3 break-words", className)}>
      {blocks.map((block, index) => (
        <Block key={index} block={block} />
      ))}
    </div>
  )
}

type Block =
  | { type: "code"; language: string; content: string }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "heading"; level: number; content: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "quote"; content: string }
  | { type: "rule" }
  | { type: "paragraph"; content: string }

/** Splits markdown source into renderable blocks. Tolerates unterminated fences. */
function parseBlocks(source: string): Block[] {
  const lines = source.split("\n")
  const blocks: Block[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (line.trim().startsWith("```")) {
      const language = line.trim().slice(3).trim()
      const body: string[] = []
      index += 1
      // An unclosed fence is normal mid-stream, so consume to EOF rather than bail.
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push({ type: "code", language, content: body.join("\n") })
      continue
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ type: "rule" })
      index += 1
      continue
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push({ type: "heading", level: heading[1].length, content: heading[2] })
      index += 1
      continue
    }

    // A markdown table needs a header row followed by a separator row.
    const nextLine = index + 1 < lines.length ? lines[index + 1] : ""
    if (line.includes("|") && /^[\s|:-]+$/.test(nextLine) && nextLine.includes("-")) {
      const header = splitRow(line)
      index += 2
      const rows: string[][] = []
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitRow(lines[index]))
        index += 1
      }
      blocks.push({ type: "table", header, rows })
      continue
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      const ordered = Boolean(numbered)
      const items: string[] = []
      while (index < lines.length) {
        const match = ordered
          ? /^\s*\d+[.)]\s+(.*)$/.exec(lines[index])
          : /^\s*[-*+]\s+(.*)$/.exec(lines[index])
        if (!match) break
        items.push(match[1])
        index += 1
      }
      blocks.push({ type: "list", ordered, items })
      continue
    }

    if (line.trim().startsWith(">")) {
      const quoted: string[] = []
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoted.push(lines[index].replace(/^\s*>\s?/, ""))
        index += 1
      }
      blocks.push({ type: "quote", content: quoted.join("\n") })
      continue
    }

    if (!line.trim()) {
      index += 1
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    if (paragraph.length === 0) {
      // Defensive: always consume at least one line so the loop terminates.
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push({ type: "paragraph", content: paragraph.join("\n") })
  }

  return blocks
}

function isBlockStart(line: string): boolean {
  return (
    line.trim().startsWith("```") ||
    /^#{1,6}\s/.test(line) ||
    /^\s*[-*+]\s/.test(line) ||
    /^\s*\d+[.)]\s/.test(line) ||
    line.trim().startsWith(">")
  )
}

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((cell) => cell.trim())
}

function Block({ block }: { block: Block }) {
  switch (block.type) {
    case "code":
      return <CodeBlock language={block.language} content={block.content} />

    case "table":
      return (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-muted/60">
              <tr>
                {block.header.map((cell, index) => (
                  <th key={index} className="whitespace-nowrap px-3 py-2 font-semibold">
                    <Inline text={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-border/60">
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="whitespace-nowrap px-3 py-1.5 tabular-nums">
                      <Inline text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )

    case "heading": {
      const sizes = ["text-xl", "text-lg", "text-base", "text-sm", "text-sm", "text-xs"]
      const Tag = `h${Math.min(block.level, 6)}` as "h1"
      return (
        <Tag className={cn("font-semibold", sizes[block.level - 1] ?? "text-sm")}>
          <Inline text={block.content} />
        </Tag>
      )
    }

    case "list": {
      const Tag = block.ordered ? "ol" : "ul"
      return (
        <Tag
          className={cn(
            "space-y-1 pl-5 marker:text-muted-foreground",
            block.ordered ? "list-decimal" : "list-disc",
          )}
        >
          {block.items.map((item, index) => (
            <li key={index}>
              <Inline text={item} />
            </li>
          ))}
        </Tag>
      )
    }

    case "quote":
      return (
        <blockquote className="border-l-2 border-border pl-3 text-muted-foreground">
          <Inline text={block.content} />
        </blockquote>
      )

    case "rule":
      return <hr className="border-border" />

    default:
      return (
        <p className="whitespace-pre-wrap leading-7">
          <Inline text={block.content} />
        </p>
      )
  }
}

function CodeBlock({ language, content }: { language: string; content: string }) {
  const [copied, setCopied] = useState(false)

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-muted/50">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {language || "code"}
        </span>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(content).then(() => {
              setCopied(true)
              setTimeout(() => setCopied(false), 1600)
            })
          }}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:text-foreground"
          aria-label="Copy code"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      <pre className="max-h-96 overflow-auto p-3 text-[12px] leading-relaxed">
        <code className="font-mono">{content}</code>
      </pre>
    </div>
  )
}

/** Renders inline emphasis, code spans and links. */
function Inline({ text }: { text: string }): ReactNode {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\))/g
  const parts = text.split(pattern).filter((part) => part !== undefined && part !== "")

  return (
    <>
      {parts.map((part, index) => {
        if (part.length > 1 && part.startsWith("`") && part.endsWith("`")) {
          return (
            <code
              key={index}
              className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] text-foreground"
            >
              {part.slice(1, -1)}
            </code>
          )
        }
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={index} className="font-semibold">
              {part.slice(2, -2)}
            </strong>
          )
        }
        if (
          part.length > 2 &&
          ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_")))
        ) {
          return (
            <em key={index} className="italic">
              {part.slice(1, -1)}
            </em>
          )
        }
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
        if (link) {
          return (
            <a
              key={index}
              href={link[2]}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2"
            >
              {link[1]}
            </a>
          )
        }
        return <Fragment key={index}>{part}</Fragment>
      })}
    </>
  )
}
