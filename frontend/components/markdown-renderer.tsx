"use client"

import { cn } from "@/lib/utils"
import type React from "react"
import { useState, useEffect } from "react"
import { AnalysisWordSpan } from "./analysis-word-span"

interface MarkdownRendererProps {
  content: string
  className?: string
  isStreaming?: boolean
}

export function MarkdownRenderer({ content, className, isStreaming = false }: MarkdownRendererProps) {
  const [staticContent, setStaticContent] = useState("")
  const [animatingContent, setAnimatingContent] = useState("")

  useEffect(() => {
    if (isStreaming) {
      // New content is everything after what we've already rendered as static
      const newContent = content.slice(staticContent.length)
      setAnimatingContent(newContent)
    } else {
      // Streaming ended - move all content to static
      setStaticContent(content)
      setAnimatingContent("")
    }
  }, [content, isStreaming, staticContent.length])

  // When animating content gets long enough, move older parts to static
  useEffect(() => {
    if (animatingContent.length > 200) {
      // Move first 150 chars to static (finding a word boundary)
      const cutPoint = animatingContent.lastIndexOf(" ", 150)
      if (cutPoint > 50) {
        setStaticContent((prev) => prev + animatingContent.slice(0, cutPoint + 1))
        setAnimatingContent(animatingContent.slice(cutPoint + 1))
      }
    }
  }, [animatingContent])

  const renderPlainInlineMarkdown = (text: string) => {
    const elements: (string | React.ReactNode)[] = []
    let remaining = text
    let keyIndex = 0

    while (remaining.length > 0) {
      // Check for inline code
      const codeMatch = remaining.match(/^`([^`]+)`/)
      if (codeMatch) {
        elements.push(
          <code key={keyIndex++} className="px-1.5 py-0.5 bg-stone-100 text-stone-700 rounded text-sm font-mono">
            {codeMatch[1]}
          </code>,
        )
        remaining = remaining.slice(codeMatch[0].length)
        continue
      }

      // Check for bold
      const boldMatch = remaining.match(/^\*\*([^*]+)\*\*/)
      if (boldMatch) {
        elements.push(<strong key={keyIndex++}>{boldMatch[1]}</strong>)
        remaining = remaining.slice(boldMatch[0].length)
        continue
      }

      // Check for italic
      const italicMatch = remaining.match(/^\*([^*]+)\*/)
      if (italicMatch) {
        elements.push(<em key={keyIndex++}>{italicMatch[1]}</em>)
        remaining = remaining.slice(italicMatch[0].length)
        continue
      }

      // Check for links
      const linkMatch = remaining.match(/^\[([^\]]+)\]\(([^)]+)\)/)
      if (linkMatch) {
        elements.push(
          <a
            key={keyIndex++}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-600 hover:text-emerald-700 underline underline-offset-2 transition-colors"
          >
            {linkMatch[1]}
          </a>,
        )
        remaining = remaining.slice(linkMatch[0].length)
        continue
      }

      // Find next special character or add remaining text
      const nextSpecial = remaining.search(/[`*[\]()]/)
      if (nextSpecial === -1) {
        elements.push(remaining)
        break
      } else if (nextSpecial === 0) {
        elements.push(remaining[0])
        remaining = remaining.slice(1)
      } else {
        elements.push(remaining.slice(0, nextSpecial))
        remaining = remaining.slice(nextSpecial)
      }
    }

    return elements
  }

  const renderAnimatedInlineMarkdown = (text: string) => {
    const elements: (string | React.ReactNode)[] = []
    let remaining = text
    let keyIndex = 0

    while (remaining.length > 0) {
      // Check for inline code
      const codeMatch = remaining.match(/^`([^`]+)`/)
      if (codeMatch) {
        elements.push(
          <code key={keyIndex++} className="px-1.5 py-0.5 bg-stone-100 text-stone-700 rounded text-sm font-mono">
            {codeMatch[1]}
          </code>,
        )
        remaining = remaining.slice(codeMatch[0].length)
        continue
      }

      // Check for bold
      const boldMatch = remaining.match(/^\*\*([^*]+)\*\*/)
      if (boldMatch) {
        const words = boldMatch[1].split(/(\s+)/)
        elements.push(
          <strong key={keyIndex++}>
            {words.map((word, i) => {
              if (word.match(/\s+/)) return word
              if (!word) return null
              return <AnalysisWordSpan key={`b-${keyIndex}-${i}`} word={word} />
            })}
          </strong>,
        )
        remaining = remaining.slice(boldMatch[0].length)
        continue
      }

      // Check for italic
      const italicMatch = remaining.match(/^\*([^*]+)\*/)
      if (italicMatch) {
        const words = italicMatch[1].split(/(\s+)/)
        elements.push(
          <em key={keyIndex++}>
            {words.map((word, i) => {
              if (word.match(/\s+/)) return word
              if (!word) return null
              return <AnalysisWordSpan key={`i-${keyIndex}-${i}`} word={word} />
            })}
          </em>,
        )
        remaining = remaining.slice(italicMatch[0].length)
        continue
      }

      // Check for links
      const linkMatch = remaining.match(/^\[([^\]]+)\]\(([^)]+)\)/)
      if (linkMatch) {
        elements.push(
          <a
            key={keyIndex++}
            href={linkMatch[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-600 hover:text-emerald-700 underline underline-offset-2 transition-colors"
          >
            {linkMatch[1]}
          </a>,
        )
        remaining = remaining.slice(linkMatch[0].length)
        continue
      }

      // Find next special character or add remaining text
      const nextSpecial = remaining.search(/[`*[\]()]/)
      if (nextSpecial === -1) {
        const words = remaining.split(/(\s+)/)
        elements.push(
          ...words.map((word, i) => {
            if (word.match(/\s+/)) return word
            if (!word) return null
            return <AnalysisWordSpan key={`w-${keyIndex++}-${i}`} word={word} />
          }),
        )
        break
      } else if (nextSpecial === 0) {
        elements.push(remaining[0])
        remaining = remaining.slice(1)
      } else {
        const textPart = remaining.slice(0, nextSpecial)
        const words = textPart.split(/(\s+)/)
        elements.push(
          ...words.map((word, i) => {
            if (word.match(/\s+/)) return word
            if (!word) return null
            return <AnalysisWordSpan key={`t-${keyIndex++}-${i}`} word={word} />
          }),
        )
        remaining = remaining.slice(nextSpecial)
      }
    }

    return elements
  }

  const renderCodeBlock = (part: string, partIndex: number) => {
    const codeContent = part.slice(3, -3)
    const firstNewline = codeContent.indexOf("\n")
    const language = firstNewline > 0 ? codeContent.slice(0, firstNewline).trim() : ""
    const code = firstNewline > 0 ? codeContent.slice(firstNewline + 1) : codeContent

    return (
      <pre
        key={partIndex}
        className="my-2 p-3 bg-stone-900 text-stone-100 rounded-lg overflow-x-auto text-sm font-mono"
        style={{
          boxShadow:
            "rgba(14, 63, 126, 0.04) 0px 0px 0px 1px, rgba(42, 51, 69, 0.04) 0px 1px 1px -0.5px, rgba(42, 51, 70, 0.04) 0px 3px 3px -1.5px, rgba(42, 51, 70, 0.04) 0px 6px 6px -3px, rgba(14, 63, 126, 0.04) 0px 12px 12px -6px, rgba(14, 63, 126, 0.04) 0px 24px 24px -12px",
        }}
      >
        {language && <span className="text-xs text-stone-400 block mb-2">{language}</span>}
        <code>{code}</code>
      </pre>
    )
  }

  const renderTable = (text: string, partIndex: number) => {
    const rows = text.trim().split("\n")
    const headerRow = rows[0].split("|").filter((cell) => cell.trim() !== "")
    const bodyRows = rows.slice(2).map((row) => row.split("|").filter((cell) => cell.trim() !== ""))

    return (
      <div key={partIndex} className="markdown-table-container">
        <table className="markdown-table">
          <thead>
            <tr>
              {headerRow.map((header, i) => (
                <th key={i}>
                  {header.trim()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>
                    {renderPlainInlineMarkdown(cell.trim())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  const renderContent = (text: string, animated: boolean) => {
    if (!text) return null

    // Split by code blocks first
    const parts = text.split(/(```[\s\S]*?```)/g)

    return (
      <div className="markdown-content">
        {parts.map((part, partIndex) => {
          if (part.startsWith("```") && part.endsWith("```")) {
            return renderCodeBlock(part, partIndex)
          }

          // More robust check for tables in the part
          const lines = part.split("\n")
          // Check if any line looks like a table row (contains | and isn't just whitespace)
          const hasTable = lines.some((line) => line.trim().startsWith("|") || (line.includes("|") && line.trim().length > 2))

          if (hasTable) {
            // Find the table block
            const nonTableBefore: string[] = []
            const tableLines: string[] = []
            const nonTableAfter: string[] = []

            let tableStarted = false
            let tableEnded = false

            for (const line of lines) {
              const isTableRow = line.trim().startsWith("|") || (line.includes("|") && line.trim().length > 2)

              if (!tableStarted && isTableRow) {
                tableStarted = true
                tableLines.push(line)
              } else if (tableStarted && !tableEnded && isTableRow) {
                tableLines.push(line)
              } else if (tableStarted && !tableEnded && !isTableRow) {
                // Check if it's just a gap
                if (line.trim() === "" && tableLines.length < 2) {
                  // Ignore empty line before table actually starts with data
                  nonTableBefore.push(line)
                } else {
                  tableEnded = true
                  if (line.trim() !== "") nonTableAfter.push(line)
                }
              } else if (!tableStarted) {
                nonTableBefore.push(line)
              } else {
                nonTableAfter.push(line)
              }
            }

            // Only render as a table if we have a header AND at least the separator row
            if (tableLines.length >= 2) {
              return (
                <div key={partIndex} className="flex flex-col gap-1">
                  {nonTableBefore.length > 0 && (
                    <span className="block">
                      {animated
                        ? renderAnimatedInlineMarkdown(nonTableBefore.join("\n"))
                        : renderPlainInlineMarkdown(nonTableBefore.join("\n"))}
                    </span>
                  )}
                  {renderTable(tableLines.join("\n"), partIndex)}
                  {nonTableAfter.length > 0 && (
                    <span className="block">
                      {animated
                        ? renderAnimatedInlineMarkdown(nonTableAfter.join("\n"))
                        : renderPlainInlineMarkdown(nonTableAfter.join("\n"))}
                    </span>
                  )}
                </div>
              )
            }
          }

          if (animated) {
            return <span key={partIndex}>{renderAnimatedInlineMarkdown(part)}</span>
          }

          return <span key={partIndex}>{renderPlainInlineMarkdown(part)}</span>
        })}
      </div>
    )
  }

  return (
    <div className={cn("text-sm whitespace-pre-wrap break-words", className)}>
      {renderContent(staticContent, false)}
      {renderContent(animatingContent, true)}
    </div>
  )
}

