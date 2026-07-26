"use client"

/**
 * WebSocket chat with genuine token streaming.
 *
 * The previous implementation opened a socket per message, waited for the
 * finished response, then faked a stream by revealing four words every 30ms.
 * This keeps one connection open (with reconnect + heartbeat) and appends each
 * `*_delta` frame to the live message as it arrives, so what you see is the
 * model's actual output rate.
 */

import { useCallback, useEffect, useRef, useState } from "react"

import { storeSessionId, websocketUrl } from "./api"
import type {
  ApprovalRequest,
  Artifact,
  ChatMessage,
  Phase,
  RunStep,
  ServerEvent,
} from "./types"

const HEARTBEAT_MS = 25_000
const MAX_RECONNECT_DELAY_MS = 15_000

function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`
}

function blankAssistant(): ChatMessage {
  return {
    id: newId(),
    role: "assistant",
    content: "",
    createdAt: Date.now(),
    steps: [],
    artifacts: [],
    warnings: [],
    downloads: [],
    streaming: true,
    phase: "planning",
  }
}

export type ConnectionState = "connecting" | "open" | "closed" | "error"

interface UseChatStreamOptions {
  onArtifact?: (artifact: Artifact) => void
  onSessionId?: (id: string) => void
}

export function useChatStream({ onArtifact, onSessionId }: UseChatStreamOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [connection, setConnection] = useState<ConnectionState>("connecting")
  const [isRunning, setIsRunning] = useState(false)
  const [phase, setPhase] = useState<Phase>("idle")

  const socketRef = useRef<WebSocket | null>(null)
  const connectRef = useRef<(() => void) | null>(null)
  const activeIdRef = useRef<string | null>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const attemptsRef = useRef(0)
  const shouldReconnectRef = useRef(true)

  // Callbacks are held in refs so the socket effect does not resubscribe when a
  // parent re-renders with new closures.
  const artifactRef = useRef(onArtifact)
  const sessionRef = useRef(onSessionId)
  useEffect(() => {
    artifactRef.current = onArtifact
    sessionRef.current = onSessionId
  }, [onArtifact, onSessionId])

  /** Applies a mutation to the message currently being streamed. */
  const patchActive = useCallback((mutate: (message: ChatMessage) => ChatMessage) => {
    const id = activeIdRef.current
    if (!id) return
    setMessages((previous) =>
      previous.map((message) => (message.id === id ? mutate(message) : message)),
    )
  }, [])

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case "session": {
          const id = String(event.session_id ?? "")
          if (id) {
            storeSessionId(id)
            sessionRef.current?.(id)
          }
          break
        }

        case "status": {
          const nextPhase = (event.phase as Phase) ?? "idle"
          setPhase(nextPhase)
          patchActive((message) => ({
            ...message,
            phase: nextPhase,
            statusLabel: String(event.content ?? ""),
          }) as ChatMessage)
          break
        }

        case "step_start": {
          const step: RunStep = {
            id: String(event.id),
            label: String(event.label ?? ""),
            kind: (event.kind as RunStep["kind"]) ?? "plan",
            status: "running",
          }
          patchActive((message) => ({ ...message, steps: [...message.steps, step] }))
          break
        }

        case "step_end": {
          patchActive((message) => ({
            ...message,
            steps: message.steps.map((step) =>
              step.id === String(event.id)
                ? {
                    ...step,
                    status: event.ok ? "done" : "failed",
                    durationMs: Number(event.duration_ms ?? 0),
                  }
                : step,
            ),
          }))
          break
        }

        case "reasoning_delta":
          patchActive((message) => ({
            ...message,
            reasoning: (message.reasoning ?? "") + String(event.content ?? ""),
          }))
          break

        case "plan_delta":
          patchActive((message) => ({
            ...message,
            plan: (message.plan ?? "") + String(event.content ?? ""),
          }))
          break

        case "content_delta":
          patchActive((message) => ({
            ...message,
            content: message.content + String(event.content ?? ""),
          }))
          break

        case "code":
          patchActive((message) => ({ ...message, code: String(event.content ?? "") }))
          break

        case "stdout":
          patchActive((message) => ({
            ...message,
            stdout: (message.stdout ?? "") + String(event.content ?? ""),
          }))
          break

        case "artifact": {
          const artifact: Artifact = {
            kind: event.kind as Artifact["kind"],
            name: event.name as string | undefined,
            data: event.data as string | undefined,
            text: event.text as string | undefined,
          }
          patchActive((message) => ({ ...message, artifacts: [...message.artifacts, artifact] }))
          artifactRef.current?.(artifact)
          break
        }

        case "warning":
          patchActive((message) => ({
            ...message,
            warnings: [...message.warnings, String(event.content ?? "")],
          }))
          break

        case "approval_required": {
          const approval: ApprovalRequest = {
            tool: (event.tool as ApprovalRequest["tool"]) ?? "execute_plan",
            prompt: String(event.prompt ?? "Confirm to continue."),
            plan: event.plan as string | undefined,
            query: event.query as string | undefined,
          }
          patchActive((message) => ({
            ...message,
            approval,
            plan: (event.plan as string) ?? message.plan,
            streaming: false,
            phase: "awaiting_approval",
          }))
          setPhase("awaiting_approval")
          setIsRunning(false)
          activeIdRef.current = null
          break
        }

        case "error": {
          const text = String(event.content ?? "Something went wrong.")
          if (activeIdRef.current) {
            patchActive((message) => ({
              ...message,
              error: text,
              streaming: false,
              phase: "failed",
            }))
          } else {
            setMessages((previous) => [
              ...previous,
              { ...blankAssistant(), streaming: false, error: text, phase: "failed" },
            ])
          }
          setIsRunning(false)
          setPhase("idle")
          activeIdRef.current = null
          break
        }

        case "final": {
          const finalText = String(event.response ?? "")
          patchActive((message) => ({
            ...message,
            // The streamed content is authoritative; fall back only if the
            // answer never streamed (e.g. the model returned in one chunk).
            content: message.content || finalText,
            code: (event.code as string) || message.code,
            downloads: (event.downloads as string[]) ?? [],
            warnings: [...message.warnings, ...(((event.warnings as string[]) ?? []) || [])],
            elapsedMs: Number(event.elapsed_ms ?? 0),
            streaming: false,
            phase: "done",
          }))
          setIsRunning(false)
          setPhase("idle")
          activeIdRef.current = null
          break
        }

        default:
          break
      }
    },
    [patchActive],
  )

  const connect = useCallback(() => {
    if (typeof window === "undefined") return
    if (socketRef.current?.readyState === WebSocket.OPEN) return

    // State is deliberately not set here. `connect` is called from an effect on
    // mount, and a synchronous setState in an effect body triggers a cascading
    // render. "connecting" is the initial value, and every later transition is
    // driven by the socket's own lifecycle handlers below.
    let socket: WebSocket
    try {
      socket = new WebSocket(websocketUrl())
    } catch {
      // Construction only throws on a malformed URL. Report it asynchronously so
      // `connect` contains no synchronous setState at all.
      queueMicrotask(() => setConnection("error"))
      return
    }
    socketRef.current = socket

    socket.onopen = () => {
      attemptsRef.current = 0
      setConnection("open")
      heartbeatRef.current = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }))
        }
      }, HEARTBEAT_MS)
    }

    socket.onmessage = (raw) => {
      try {
        handleEvent(JSON.parse(raw.data) as ServerEvent)
      } catch {
        // A malformed frame must not tear down the stream.
      }
    }

    socket.onerror = () => setConnection("error")

    socket.onclose = () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      heartbeatRef.current = null
      socketRef.current = null
      setConnection("closed")

      // A close mid-run would otherwise leave the UI spinning forever.
      if (activeIdRef.current) {
        patchActive((message) => ({
          ...message,
          streaming: false,
          error: message.content ? undefined : "The connection dropped before the answer completed.",
        }))
        activeIdRef.current = null
        setIsRunning(false)
        setPhase("idle")
      }

      if (shouldReconnectRef.current) {
        attemptsRef.current += 1
        const delay = Math.min(1000 * 2 ** (attemptsRef.current - 1), MAX_RECONNECT_DELAY_MS)
        // Reached through a ref so the callback does not have to close over
        // itself, which would make it its own dependency.
        reconnectRef.current = setTimeout(() => {
          setConnection("connecting")
          connectRef.current?.()
        }, delay)
      }
    }
  }, [handleEvent, patchActive])

  // Keeps the reconnect timer pointing at the current `connect` closure.
  useEffect(() => {
    connectRef.current = connect
  }, [connect])

  useEffect(() => {
    shouldReconnectRef.current = true
    connect()
    return () => {
      shouldReconnectRef.current = false
      if (reconnectRef.current) clearTimeout(reconnectRef.current)
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [connect])

  const send = useCallback(
    (payload: Record<string, unknown>) => {
      const socket = socketRef.current
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        setMessages((previous) => [
          ...previous,
          {
            ...blankAssistant(),
            streaming: false,
            error: "Not connected to the analysis server. Retrying automatically…",
            phase: "failed",
          },
        ])
        connect()
        return false
      }
      socket.send(JSON.stringify(payload))
      return true
    },
    [connect],
  )

  const sendMessage = useCallback(
    (content: string, mode: "planning" | "fast") => {
      const trimmed = content.trim()
      if (!trimmed || isRunning) return

      const userMessage: ChatMessage = {
        id: newId(),
        role: "user",
        content: trimmed,
        createdAt: Date.now(),
        steps: [],
        artifacts: [],
        warnings: [],
        downloads: [],
      }
      const assistant = blankAssistant()
      activeIdRef.current = assistant.id

      setMessages((previous) => [...previous, userMessage, assistant])
      setIsRunning(true)
      setPhase("planning")

      if (!send({ type: "message", content: trimmed, mode })) {
        setIsRunning(false)
        activeIdRef.current = null
      }
    },
    [isRunning, send],
  )

  const respondToApproval = useCallback(
    (message: ChatMessage, approved: boolean) => {
      const approval = message.approval
      if (!approval) return

      setMessages((previous) =>
        previous.map((item) => (item.id === message.id ? { ...item, approval: null } : item)),
      )

      if (!approved) {
        setMessages((previous) =>
          previous.map((item) =>
            item.id === message.id
              ? { ...item, content: item.content || "Plan rejected.", phase: "done" }
              : item,
          ),
        )
        return
      }

      // Find the user turn this approval belongs to so the instruction survives.
      const index = messages.findIndex((item) => item.id === message.id)
      const instruction =
        [...messages.slice(0, index)].reverse().find((item) => item.role === "user")?.content ?? ""

      const assistant = blankAssistant()
      activeIdRef.current = assistant.id
      setMessages((previous) => [...previous, assistant])
      setIsRunning(true)
      setPhase("generating")

      send({
        type: "approval",
        approved: true,
        tool: approval.tool,
        content: instruction,
        plan: approval.plan,
        query: approval.query,
      })
    },
    [messages, send],
  )

  const cancel = useCallback(() => {
    send({ type: "cancel" })
    setIsRunning(false)
    setPhase("idle")
    patchActive((message) => ({ ...message, streaming: false, phase: "idle" }))
    activeIdRef.current = null
  }, [patchActive, send])

  const clear = useCallback(() => {
    setMessages([])
    setPhase("idle")
    setIsRunning(false)
    activeIdRef.current = null
  }, [])

  return {
    messages,
    connection,
    isRunning,
    phase,
    sendMessage,
    respondToApproval,
    cancel,
    clear,
    reconnect: connect,
  }
}
