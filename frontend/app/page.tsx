"use client"

import { ArrowRight, ArrowUpRight, Check, Terminal } from "lucide-react"
import Link from "next/link"
import { useEffect } from "react"

import { AnimatedOrb } from "@/components/animated-orb"
import { Reveal } from "@/components/reveal"
import { SoundToggle } from "@/components/sound-toggle"
import { preloadSounds, useSound } from "@/lib/use-sound"

/* -------------------------------------------------------------------------- */
/* Content                                                                     */
/* -------------------------------------------------------------------------- */

const PIPELINE = [
  {
    index: "01",
    title: "It reasons before it writes",
    body: "The manager model reads your schema, decides what the question actually requires, and drafts a plan. You see the thinking stream in as it happens — and in planning mode, nothing runs until you approve it.",
    detail: "Streamed token by token. No spinner, no fake typing.",
  },
  {
    index: "02",
    title: "The code runs sealed",
    body: "A second model writes the pandas. Before it executes, an AST analyser rejects imports, reflection and paths outside the workspace. What survives runs in a container of its own — capabilities dropped, memory capped, PIDs bounded.",
    detail: "One container per session. Nothing is shared between users.",
  },
  {
    index: "03",
    title: "Failures repair themselves",
    body: "A traceback goes back to the model with the code that produced it, and the loop tries again — bounded, never infinite. Fixes that work are remembered, so the same mistake gets cheaper every time it is made.",
    detail: "Bounded by MAX_CORRECTION_RETRIES. Always terminates.",
  },
  {
    index: "04",
    title: "You get prose, not a dump",
    body: "The answer is written from the real execution output — the actual numbers, the actual chart. Charts, tables and files land in a workspace panel you can open, sort and download.",
    detail: "Synthesised from stdout. Nothing invented.",
  },
] as const

const GUARANTEES = [
  { label: "Runs on", value: "your hardware" },
  { label: "Sends data to", value: "nobody" },
  { label: "Models", value: "yours to pick" },
  { label: "Requires", value: "no account" },
] as const

const SPECS = [
  {
    heading: "Models",
    items: [
      "Ollama and LM Studio, discovered live",
      "A different provider per role if you want one",
      "Any OpenAI-compatible server via one URL",
      "Switch mid-session; nothing restarts",
    ],
  },
  {
    heading: "Isolation",
    items: [
      "One Docker container per session",
      "cap_drop ALL, no-new-privileges",
      "Memory, PID and CPU ceilings",
      "Optional gVisor kernel isolation",
    ],
  },
  {
    heading: "Data",
    items: [
      "CSV, Excel, JSON, Parquet, Feather",
      "Files up to 512 MB, sampled past 2M rows",
      "Wide frames sent column-relevant, not whole",
      "Everything stays in your workspace",
    ],
  },
] as const

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function Landing() {
  const { playSound } = useSound()

  useEffect(() => {
    // Warm the decoder now so the first click is not gated on a fetch, and let
    // the hook try the startup chime. Browsers block it until the page has been
    // interacted with, in which case it fires on the first real gesture instead.
    preloadSounds()
    playSound("startup")
  }, [playSound])

  return (
    <main className="relative min-h-screen overflow-x-hidden">
      <Nav />
      <Hero onNavigate={() => playSound("click")} />
      <Guarantees />
      <Pipeline />
      <Specs />
      <Closing onNavigate={() => playSound("click")} />
      <Footer />
    </main>
  )
}

/* -------------------------------------------------------------------------- */

function Nav() {
  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <div className="glass border-b border-border/60">
        <nav className="mx-auto flex h-15 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link href="/" className="group flex items-center gap-2.5" aria-label="Wizard home">
            <AnimatedOrb size={26} />
            <span className="text-[15px] font-semibold tracking-[-0.02em]">Wizard</span>
            <span className="hidden rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:inline">
              v3
            </span>
          </Link>

          <div className="flex items-center gap-1">
            <a
              href="https://github.com/Aniket-a14/Wizard-w1"
              target="_blank"
              rel="noreferrer"
              className="hidden items-center gap-1 rounded-lg px-3 py-1.5 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:flex"
            >
              Source
              <ArrowUpRight className="h-3 w-3" />
            </a>
            <SoundToggle />
            <Link
              href="/chat"
              className="ml-1 flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-[13px] font-medium text-primary-foreground shadow-sm transition-all duration-[var(--duration-fast)] hover:shadow-md active:scale-[0.985]"
            >
              Open workspace
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </nav>
      </div>
    </header>
  )
}

/* -------------------------------------------------------------------------- */

function Hero({ onNavigate }: { onNavigate: () => void }) {
  return (
    <section className="relative flex min-h-[92svh] flex-col items-center justify-center px-5 pt-15 text-center sm:px-8">
      <div className="grid-field pointer-events-none absolute inset-0" aria-hidden="true" />

      <div className="relative flex flex-col items-center">
        {/* The orb leads. Everything else arrives underneath it, in sequence. */}
        <div className="orb-intro float-slow mb-9">
          <AnimatedOrb size={128} />
        </div>

        <div
          className="reveal mb-7 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3.5 py-1.5 text-[12px] shadow-xs backdrop-blur"
          style={{ animationDelay: "260ms" }}
        >
          <span className="relative flex h-1.5 w-1.5 text-success">
            <span className="pulse-ring absolute inset-0 rounded-full" />
            <span className="relative h-1.5 w-1.5 rounded-full bg-current" />
          </span>
          <span className="text-muted-foreground">Local-first · nothing leaves this machine</span>
        </div>

        <h1
          className="reveal max-w-4xl text-balance text-[clamp(2.6rem,7.5vw,5.25rem)] font-semibold leading-[0.95] tracking-[-0.04em]"
          style={{ animationDelay: "360ms" }}
        >
          Ask harder questions
          <br />
          <span className="text-gradient">of your own data.</span>
        </h1>

        <p
          className="reveal mt-7 max-w-xl text-pretty text-[17px] leading-relaxed text-muted-foreground"
          style={{ animationDelay: "460ms" }}
        >
          Wizard plans the analysis, writes the Python, runs it inside a sealed container and tells
          you what it found. On your hardware. With the models you chose.
        </p>

        <div className="reveal mt-10 flex flex-col items-center gap-3 sm:flex-row" style={{ animationDelay: "560ms" }}>
          <Link
            href="/chat"
            onClick={onNavigate}
            className="group flex h-13 items-center gap-2 rounded-xl bg-[linear-gradient(120deg,var(--brand),var(--brand-2))] px-7 text-[15px] font-medium text-brand-foreground shadow-brand transition-all duration-[var(--duration-base)] ease-[var(--ease-out-expo)] hover:shadow-lg hover:brightness-105 active:scale-[0.985]"
          >
            Start analysing
            <ArrowRight className="h-4 w-4 transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)] group-hover:translate-x-0.5" />
          </Link>
          <a
            href="#pipeline"
            className="flex h-13 items-center gap-2 rounded-xl border border-border bg-card/70 px-6 text-[15px] text-muted-foreground shadow-xs backdrop-blur transition-colors duration-[var(--duration-fast)] hover:border-brand/40 hover:text-foreground"
          >
            See how it works
          </a>
        </div>

        {/* A real command, not decoration — this is the actual quick start. */}
        <div
          className="reveal mt-14 flex items-center gap-2.5 rounded-xl border border-border bg-card px-4 py-2.5 font-mono text-[12.5px] shadow-sm"
          style={{ animationDelay: "680ms" }}
        >
          <Terminal className="h-3.5 w-3.5 shrink-0 text-brand" />
          <code className="text-muted-foreground">
            <span className="text-foreground">docker compose</span> up --build -d
          </code>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function Guarantees() {
  return (
    <section className="border-y border-border/70 bg-card/40">
      <div className="mx-auto grid max-w-6xl grid-cols-2 gap-px overflow-hidden bg-border/70 md:grid-cols-4">
        {GUARANTEES.map((item, index) => (
          <Reveal
            key={item.label}
            delay={index * 70}
            className="bg-background px-5 py-8 sm:px-7 sm:py-10"
          >
            <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
              {item.label}
            </p>
            <p className="mt-2 text-[19px] font-medium tracking-[-0.02em] sm:text-[21px]">{item.value}</p>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function Pipeline() {
  return (
    <section id="pipeline" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-28 sm:px-8 sm:py-36">
      <Reveal className="max-w-2xl">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-brand">The loop</p>
        <h2 className="mt-4 text-balance text-[clamp(2rem,4.6vw,3.25rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
          Four steps, and you can watch every one.
        </h2>
        <p className="mt-5 text-[16px] leading-relaxed text-muted-foreground">
          Most tools hand you an answer and ask for trust. This one shows the reasoning, the code it
          wrote, the output that came back, and where each of those came from.
        </p>
      </Reveal>

      <ol className="mt-16 space-y-px overflow-hidden rounded-2xl border border-border bg-border">
        {PIPELINE.map((step, index) => (
          <Reveal
            as="li"
            key={step.index}
            delay={index * 60}
            className="group bg-card transition-colors duration-[var(--duration-base)] hover:bg-accent/40"
          >
            <div className="grid gap-5 px-6 py-9 sm:px-10 sm:py-12 md:grid-cols-[7rem_1fr_16rem] md:gap-10">
              <span className="font-mono text-[13px] text-muted-foreground transition-colors duration-[var(--duration-base)] group-hover:text-brand">
                {step.index}
              </span>

              <div className="max-w-2xl">
                <h3 className="text-[21px] font-medium tracking-[-0.025em] sm:text-[24px]">{step.title}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-muted-foreground">{step.body}</p>
              </div>

              <p className="self-end border-l border-border pl-4 font-mono text-[11.5px] leading-relaxed text-muted-foreground md:border-l-0 md:border-t md:pl-0 md:pt-4">
                {step.detail}
              </p>
            </div>
          </Reveal>
        ))}
      </ol>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function Specs() {
  return (
    <section className="border-t border-border bg-card/40">
      <div className="mx-auto max-w-6xl px-5 py-28 sm:px-8 sm:py-36">
        <Reveal className="max-w-2xl">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-brand">Specifics</p>
          <h2 className="mt-4 text-balance text-[clamp(2rem,4.6vw,3.25rem)] font-semibold leading-[1.05] tracking-[-0.035em]">
            The parts that matter to whoever signs off on it.
          </h2>
        </Reveal>

        <div className="mt-16 grid gap-10 md:grid-cols-3 md:gap-8">
          {SPECS.map((group, index) => (
            <Reveal key={group.heading} delay={index * 80}>
              <h3 className="border-b border-border pb-4 text-[13px] font-semibold uppercase tracking-[0.1em]">
                {group.heading}
              </h3>
              <ul className="mt-6 space-y-3.5">
                {group.items.map((item) => (
                  <li key={item} className="flex gap-3 text-[14.5px] leading-relaxed text-muted-foreground">
                    <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-success" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function Closing({ onNavigate }: { onNavigate: () => void }) {
  return (
    <section className="relative overflow-hidden border-t border-border px-5 py-32 text-center sm:px-8 sm:py-44">
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 h-[36rem] w-[36rem] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-60 blur-3xl"
        style={{
          background:
            "radial-gradient(circle, oklch(0.6 0.18 285 / 0.16), oklch(0.72 0.13 205 / 0.09) 45%, transparent 70%)",
        }}
        aria-hidden="true"
      />

      <Reveal className="relative mx-auto max-w-2xl">
        <div className="mb-10 flex justify-center">
          <AnimatedOrb size={72} className="float-slow" />
        </div>
        <h2 className="text-balance text-[clamp(2.1rem,5.2vw,3.75rem)] font-semibold leading-[1.02] tracking-[-0.04em]">
          Your data stays where it is.
        </h2>
        <p className="mt-6 text-[16.5px] leading-relaxed text-muted-foreground">
          Pull two small models, start the stack, drop in a file. There is no signup, no key to
          paste and no upload — the whole thing runs on the machine in front of you.
        </p>
        <Link
          href="/chat"
          onClick={onNavigate}
          className="group mt-11 inline-flex h-13 items-center gap-2 rounded-xl bg-primary px-8 text-[15px] font-medium text-primary-foreground shadow-md transition-all duration-[var(--duration-base)] ease-[var(--ease-out-expo)] hover:shadow-lg active:scale-[0.985]"
        >
          Open the workspace
          <ArrowRight className="h-4 w-4 transition-transform duration-[var(--duration-base)] ease-[var(--ease-out-expo)] group-hover:translate-x-0.5" />
        </Link>
      </Reveal>
    </section>
  )
}

/* -------------------------------------------------------------------------- */

function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-5 px-5 py-9 text-[12.5px] text-muted-foreground sm:flex-row sm:px-8">
        <div className="flex items-center gap-2.5">
          <AnimatedOrb size={18} />
          <span>Wizard — local-first data analysis</span>
        </div>
        <div className="flex items-center gap-6">
          <a
            href="https://github.com/Aniket-a14/Wizard-w1"
            target="_blank"
            rel="noreferrer"
            className="transition-colors hover:text-foreground"
          >
            GitHub
          </a>
          <Link href="/chat" className="transition-colors hover:text-foreground">
            Workspace
          </Link>
        </div>
      </div>
    </footer>
  )
}
