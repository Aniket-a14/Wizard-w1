"""The analysis workflow.

This replaces ``LangGraphAgent`` plus the hand-copied node loop that lived in the
WebSocket handler. There is now exactly one implementation of the sequence, and
it streams: the manager's reasoning, the plan and the final answer are all
emitted token-by-token as the model produces them.

Flow
----
    cache lookup -> plan -> [approval gate] -> generate -> execute
                                                  ^          |
                                                  +-- correct-+   (bounded retries)
                                                             |
                                                       review -> answer

Fixes carried in from the audit
-------------------------------
* ``state.error`` is cleared on a successful execution. It previously persisted,
  so the ``if code and not error`` condition in the review step was always False
  after a self-heal -- meaning the semantic cache and the trajectory memory were
  never written in exactly the situation they exist to capture.
* Guard verdicts distinguish "malformed code" (retry) from "policy violation"
  (stop), instead of terminating the run as ``completed`` in both cases.
* The Council and the vision model are awaited concurrently and are individually
  optional, rather than serialising three extra LLM calls into every response.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.config import settings
from src.core.agent.council import TheCouncil
from src.core.agent.events import Emitter, EventType, Phase, emit
from src.core.execution import ExecutionResult
from src.core.feedback_store import FeedbackStore
from src.core.llm import LLMRole, llm_provider
from src.core.llm.provider import LLMUnavailableError
from src.core.memory import working_memory
from src.core.prompts import (
    create_answer_prompt,
    create_planning_prompt,
    create_prompt,
    create_replan_prompt,
)
from src.core.rag.retriever import context_retriever
from src.core.semantic_cache import semantic_cache
from src.core.tools.evaluator import Evaluator
from src.utils.logging import logger


if TYPE_CHECKING:
    from src.core.session import Session


THOUGHT_PATTERN = re.compile(r"<thought>(.*?)</thought>", re.DOTALL)
OPEN_THOUGHT = re.compile(r"<thought>", re.IGNORECASE)
CLOSE_THOUGHT = re.compile(r"</thought>", re.IGNORECASE)
SEARCH_PATTERN = re.compile(r'SEARCH:\s*"(.*?)"')
STEP_PATTERN = re.compile(r"^\s*(?:\d+[.)]\s+|[-*]\s+)(.+)$", re.MULTILINE)

VISUAL_KEYWORDS = frozenset(
    {"color", "colour", "legend", "font", "axis", "label", "grid", "title", "theme", "style", "palette", "annotate"}
)

SIMPLE_PATTERNS = (
    "show first",
    "show top",
    "show head",
    "display head",
    "display first",
    "show last",
    "show tail",
    "display tail",
    "display last",
    "show columns",
    "list columns",
    "what columns",
    "column names",
    "shape of",
    "how many rows",
    "number of rows",
    "dataset dimensions",
    "preview dataset",
    "preview table",
    "describe the data",
    "head of",
)


@dataclass
class RunState:
    """Everything one analysis turn needs to carry."""

    instruction: str
    mode: str = "planning"
    phase: Phase = Phase.IDLE

    thought: str = ""
    plan: str = ""
    code: str = ""
    output: str = ""
    answer: str = ""
    image: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    error: str | None = None
    retry_count: int = 0
    blocked: bool = False

    steps: list[str] = field(default_factory=list)
    step_outputs: list[str] = field(default_factory=list)
    current_step: int = 0

    failed_code: str = ""
    failed_error: str = ""
    from_cache: bool = False
    warnings: list[str] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    started_at: float = field(default_factory=time.time)

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)


@dataclass
class RunResult:
    answer: str
    code: str
    thought: str
    plan: str
    image: str | None
    status: str  # "completed" | "awaiting_approval" | "failed"
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    downloads: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.answer,
            "code": self.code,
            "thought": self.thought,
            "plan": self.plan,
            "image": self.image,
            "status": self.status,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "approval": self.pending_approval,
            "downloads": self.downloads,
            "elapsed_ms": self.elapsed_ms,
        }


class AnalysisOrchestrator:
    """Drives one analysis turn for one session."""

    def __init__(self):
        self.council = TheCouncil()
        self.feedback = FeedbackStore()

    # ------------------------------------------------------------------ #
    # Routing helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def is_simple(instruction: str) -> bool:
        """Cheap keyword routing so trivial requests skip a planning round-trip."""
        lowered = instruction.lower().strip()
        return any(pattern in lowered for pattern in SIMPLE_PATTERNS)

    @staticmethod
    def is_visual_revision(instruction: str, previous_code: str | None) -> bool:
        if not previous_code:
            return False
        if not any(marker in previous_code for marker in ("plt.", "sns.", "px.", "go.")):
            return False
        lowered = instruction.lower()
        return any(keyword in lowered for keyword in VISUAL_KEYWORDS)

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    async def run(
        self,
        session: Session,
        instruction: str,
        mode: str = "planning",
        emitter: Emitter | None = None,
        approved_plan: str | None = None,
        approved_search: str | None = None,
        previous_code: str | None = None,
    ) -> RunResult:
        """Executes one turn. Returns when the run completes or pauses for approval."""
        state = RunState(instruction=instruction, mode=mode)

        if session.df is None:
            await emit(emitter, EventType.ERROR, content="No dataset is loaded for this session.")
            return self._result(state, "failed")

        try:
            if approved_search is not None:
                await self._run_search(state, session, approved_search, emitter)
            elif approved_plan is not None:
                # The user confirmed a plan produced by an earlier turn.
                state.plan = approved_plan
                state.steps = self._extract_steps(approved_plan)
            else:
                should_continue = await self._plan(state, session, emitter, previous_code)
                if not should_continue:
                    return self._result(state, "awaiting_approval")

            await self._execute_loop(state, session, emitter, previous_code)

            if state.blocked:
                await self._finalize(state, session, emitter)
                return self._result(state, "completed")

            if state.error and state.retry_count > settings.MAX_CORRECTION_RETRIES:
                state.phase = Phase.FAILED
                await self._answer(state, session, emitter)
                await self._finalize(state, session, emitter)
                return self._result(state, "completed")

            await self._review(state, session, emitter)
            await self._answer(state, session, emitter)
            await self._finalize(state, session, emitter)
            return self._result(state, "completed")

        except LLMUnavailableError as exc:
            message = (
                f"Could not reach the language model: {exc}. "
                "Check that Ollama is running and the selected model is installed."
            )
            logger.error("Run aborted, LLM unavailable", error=str(exc))
            await emit(emitter, EventType.ERROR, content=message)
            state.answer = message
            return self._result(state, "failed")
        except Exception as exc:
            logger.error("Run failed unexpectedly", error=str(exc))
            await emit(emitter, EventType.ERROR, content=f"Unexpected failure: {exc}")
            state.answer = f"The analysis failed unexpectedly: {exc}"
            return self._result(state, "failed")

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #
    async def _plan(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        previous_code: str | None,
    ) -> bool:
        """Produces a plan. Returns False when the run pauses for user approval."""
        columns = [str(c) for c in session.df.columns]

        # 1. Exact/semantic cache: skip planning and code generation entirely.
        cached = semantic_cache.lookup(state.instruction, columns)
        if cached:
            state.code = cached
            state.from_cache = True
            state.plan = "Reused a previously verified solution for this question."
            await emit(emitter, EventType.STATUS, content="Reusing a verified solution", phase=Phase.GENERATING.value)
            return True

        # 2. Keyword fast path for trivial inspection requests.
        if self.is_simple(state.instruction):
            state.plan = f"Directly answer the inspection request: {state.instruction}"
            await emit(
                emitter, EventType.STATUS, content="Simple request, skipping planning", phase=Phase.GENERATING.value
            )
            return True

        state.phase = Phase.PLANNING
        await emit(emitter, EventType.STEP_START, id="plan", label="Planning the analysis", kind="plan")
        await emit(emitter, EventType.STATUS, content="Planning the analysis", phase=Phase.PLANNING.value)

        prompt = create_planning_prompt(
            state.instruction,
            session.df,
            catalog=session.catalog,
            mode=state.mode,
            memory_context=working_memory.get_context_string(state.instruction, session_id=session.id),
            previous_code=previous_code if self.is_visual_revision(state.instruction, previous_code) else None,
            session_id=session.id,
            history=session.history_prompt(),
        )

        raw = await self._stream_plan(prompt, session, emitter)

        thought_match = THOUGHT_PATTERN.search(raw)
        if thought_match:
            state.thought = thought_match.group(1).strip()
            state.plan = THOUGHT_PATTERN.sub("", raw).strip()
        else:
            state.plan = raw.strip()

        await emit(emitter, EventType.STEP_END, id="plan", ok=True, duration_ms=state.elapsed_ms)

        # A plan may request a web search; that requires explicit consent.
        search_match = SEARCH_PATTERN.search(state.plan)
        if search_match:
            query = search_match.group(1)
            state.pending_approval = {
                "tool": "web_search",
                "query": query,
                "prompt": f"Wizard wants to search the web for: “{query}”. Allow?",
                "plan": state.plan,
            }
            state.phase = Phase.AWAITING_APPROVAL
            await emit(emitter, EventType.APPROVAL_REQUIRED, **state.pending_approval)
            return False

        state.steps = self._extract_steps(state.plan)

        if state.mode == "planning":
            state.pending_approval = {
                "tool": "execute_plan",
                "plan": state.plan,
                "prompt": "Review the plan and confirm to run it.",
            }
            state.phase = Phase.AWAITING_APPROVAL
            await emit(emitter, EventType.APPROVAL_REQUIRED, **state.pending_approval)
            return False

        return True

    async def _stream_plan(self, prompt: str, session: Session, emitter: Emitter | None) -> str:
        """Streams the manager response, splitting reasoning from plan as it arrives.

        The model emits ``<thought>…</thought>`` then the plan. Rather than waiting
        for the whole response and regex-splitting it afterwards, the tag boundary
        is tracked incrementally so the UI can render a live "thinking" panel that
        switches to the plan at the right moment.
        """
        buffer: list[str] = []
        inside_thought = False
        seen_thought = False
        pending = ""

        async def on_delta(delta: str):
            nonlocal inside_thought, seen_thought, pending
            buffer.append(delta)
            pending += delta

            while pending:
                if not inside_thought:
                    open_match = OPEN_THOUGHT.search(pending)
                    if open_match:
                        before = pending[: open_match.start()]
                        if before.strip():
                            await emit(emitter, EventType.PLAN_DELTA, content=before)
                        pending = pending[open_match.end() :]
                        inside_thought = True
                        seen_thought = True
                        continue
                    # Hold back a partial "<thought" prefix rather than leaking it.
                    if "<" in pending and len(pending) < 16:
                        return
                    if pending:
                        await emit(
                            emitter,
                            EventType.REASONING_DELTA if not seen_thought else EventType.PLAN_DELTA,
                            content=pending,
                        )
                        pending = ""
                    return

                close_match = CLOSE_THOUGHT.search(pending)
                if close_match:
                    inner = pending[: close_match.start()]
                    if inner:
                        await emit(emitter, EventType.REASONING_DELTA, content=inner)
                    pending = pending[close_match.end() :]
                    inside_thought = False
                    continue
                if "<" in pending and len(pending) < 16:
                    return
                await emit(emitter, EventType.REASONING_DELTA, content=pending)
                pending = ""
                return

        await llm_provider.stream_to(
            prompt,
            on_delta=on_delta,
            role=LLMRole.MANAGER,
            model=session.models.manager,
            temperature=session.models.temperature,
            provider=session.models.manager_provider,
        )
        if pending:
            await emit(emitter, EventType.PLAN_DELTA, content=pending)
        return "".join(buffer)

    @staticmethod
    def _extract_steps(plan: str) -> list[str]:
        """Splits a numbered plan into individually executable steps."""
        steps = [match.strip() for match in STEP_PATTERN.findall(plan)]
        steps = [step for step in steps if len(step) > 8]
        return steps if len(steps) >= 2 else []

    # ------------------------------------------------------------------ #
    # Web search
    # ------------------------------------------------------------------ #
    async def _run_search(self, state: RunState, session: Session, query: str, emitter: Emitter | None):
        state.phase = Phase.SEARCHING
        await emit(emitter, EventType.STEP_START, id="search", label=f"Searching: {query}", kind="tool")

        from src.core.tools.search import WebSearchTool

        try:
            results = await asyncio.to_thread(WebSearchTool().search, query)
        except Exception as exc:
            logger.warning("Web search failed", error=str(exc))
            results = []
            state.warnings.append(f"Web search failed ({exc}); planning continued without it.")

        await emit(emitter, EventType.STEP_END, id="search", ok=bool(results), duration_ms=state.elapsed_ms)

        prompt = create_replan_prompt(state.instruction, results, state.thought)
        state.plan = await self._stream_plan(prompt, session, emitter)
        state.steps = self._extract_steps(state.plan)

    # ------------------------------------------------------------------ #
    # Generation + execution
    # ------------------------------------------------------------------ #
    async def _execute_loop(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        previous_code: str | None,
    ):
        """Generates and runs code, retrying on recoverable failures.

        Handles both the single-shot case and the multi-step case where a plan is
        executed one numbered step at a time with prior outputs fed forward.
        """
        total_steps = max(1, len(state.steps))

        while state.current_step < total_steps:
            state.retry_count = 0
            state.error = None
            if not state.from_cache:
                state.code = ""

            while True:
                await self._generate(state, session, emitter, previous_code)
                if state.error and not state.code:
                    return

                result = await self._execute(state, session, emitter)

                if result.blocked:
                    state.blocked = True
                    state.output = result.output
                    state.answer = result.output
                    return

                if result.ok:
                    # Clearing the error here is what makes caching and trajectory
                    # learning fire after a successful self-heal.
                    state.error = None
                    state.output = result.output
                    state.image = result.image or state.image
                    state.warnings.extend(result.warnings)
                    break

                state.failed_code = state.code
                state.failed_error = result.output
                state.error = result.output
                state.retry_count += 1
                state.from_cache = False

                if state.retry_count > settings.MAX_CORRECTION_RETRIES:
                    state.output = result.output
                    logger.warning("Exhausted correction retries", attempts=state.retry_count)
                    return

                state.phase = Phase.CORRECTING
                await emit(
                    emitter,
                    EventType.STATUS,
                    content=f"Fixing an execution error (attempt {state.retry_count} of {settings.MAX_CORRECTION_RETRIES})",
                    phase=Phase.CORRECTING.value,
                )

            state.step_outputs.append(state.output)
            state.current_step += 1

        if len(state.step_outputs) > 1:
            state.output = "\n\n".join(
                f"Step {index}: {text}" for index, text in enumerate(state.step_outputs, start=1)
            )

    async def _generate(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        previous_code: str | None,
    ):
        if state.from_cache and state.code and not state.error:
            await emit(emitter, EventType.CODE, content=state.code, language="python", cached=True)
            return

        state.phase = Phase.GENERATING
        step_id = f"code-{state.current_step}-{state.retry_count}"
        await emit(emitter, EventType.STEP_START, id=step_id, label="Writing Python", kind="code")
        await emit(emitter, EventType.STATUS, content="Writing Python", phase=Phase.GENERATING.value)

        instruction = state.instruction
        if state.steps:
            step_text = state.steps[state.current_step]
            prior = "\n".join(
                f"# Step {index} output: {text[:200]}" for index, text in enumerate(state.step_outputs, start=1)
            )
            instruction = (
                f"Overall request: {state.instruction}\n\n"
                f"You are implementing step {state.current_step + 1} of {len(state.steps)}:\n{step_text}\n\n"
                f"{prior}\n\n"
                "Write code for THIS step only. Variables from previous steps are still in scope."
            )

        columns = [str(c) for c in session.df.columns]
        negative = context_retriever.retrieve_trajectories(state.instruction, columns)

        prompt = create_prompt(
            instruction,
            session.df,
            plan=state.plan,
            previous_error=state.error,
            catalog=session.catalog,
            few_shot_examples=self.feedback.get_similar_examples(state.instruction),
            previous_code=previous_code if self.is_visual_revision(state.instruction, previous_code) else None,
            session_id=session.id,
            negative_example=negative.text if negative else None,
        )

        raw = await llm_provider.acomplete(
            prompt,
            role=LLMRole.WORKER,
            model=session.models.worker,
            temperature=session.models.temperature,
            provider=session.models.worker_provider,
        )
        state.code = self._extract_code(raw)

        await emit(emitter, EventType.STEP_END, id=step_id, ok=bool(state.code), duration_ms=state.elapsed_ms)
        if state.code:
            await emit(emitter, EventType.CODE, content=state.code, language="python", cached=False)
        else:
            state.error = "The model did not return any code."

    @staticmethod
    def _extract_code(response: str) -> str:
        """Pulls the python block out of a model response."""
        fenced = re.search(r"```(?:python|py)?\s*\n(.*?)```", response, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        stripped = response.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
        return stripped

    async def _execute(self, state: RunState, session: Session, emitter: Emitter | None) -> ExecutionResult:
        state.phase = Phase.EXECUTING
        step_id = f"run-{state.current_step}-{state.retry_count}"
        await emit(emitter, EventType.STEP_START, id=step_id, label="Running code", kind="execute")
        await emit(emitter, EventType.STATUS, content="Running code in the sandbox", phase=Phase.EXECUTING.value)

        # Remove a stale chart so a failed run cannot present the previous plot.
        plot_path = session.workspace / "plot.html"
        plot_path.unlink(missing_ok=True)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        def on_stdout(chunk: str):
            # Called from the executor thread; hop back onto the loop safely.
            loop.call_soon_threadsafe(queue.put_nowait, chunk)

        async def drain():
            while True:
                chunk = await queue.get()
                if chunk == "":
                    return
                await emit(emitter, EventType.STDOUT, content=chunk)

        drainer = asyncio.ensure_future(drain())
        try:
            result = await asyncio.to_thread(session.executor.execute, state.code, session.df, on_stdout)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, "")
            await drainer

        if settings.PLOT_FORMAT == "html" and plot_path.exists():
            state.artifacts.append({"kind": "plot_html", "name": "plot.html", "session_scoped": True})
            await emit(emitter, EventType.ARTIFACT, kind="plot_html", name="plot.html")
            result.image = None
        elif result.image:
            state.artifacts.append({"kind": "plot_png", "name": "plot.png"})
            await emit(emitter, EventType.ARTIFACT, kind="plot_png", name="plot.png", data=result.image)

        for warning in result.warnings:
            await emit(emitter, EventType.WARNING, content=warning)

        await emit(emitter, EventType.STEP_END, id=step_id, ok=result.ok, duration_ms=state.elapsed_ms)
        return result

    # ------------------------------------------------------------------ #
    # Review
    # ------------------------------------------------------------------ #
    async def _review(self, state: RunState, session: Session, emitter: Emitter | None):
        if not settings.COUNCIL_ENABLED or state.error:
            return

        state.phase = Phase.REVIEWING
        await emit(emitter, EventType.STEP_START, id="review", label="Reviewing results", kind="review")

        tasks: list[asyncio.Task] = [
            asyncio.ensure_future(self.council.adjudicate(state.plan, state.code, state.output, session.models))
        ]
        if settings.VISION_ENABLED and state.image:
            tasks.append(asyncio.ensure_future(self._describe_plot(state.image, session)))

        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=settings.COUNCIL_TIMEOUT
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            logger.info("Review timed out; continuing without it")
            outcomes = []

        review = outcomes[0] if outcomes and not isinstance(outcomes[0], Exception) else None
        if isinstance(review, dict):
            notes = [
                f"{entry['agent']}: {', '.join(entry['feedback'])}"
                for entry in review.get("reviews", [])
                if entry.get("feedback")
            ]
            if notes:
                state.warnings.extend(notes)

        if len(outcomes) > 1 and isinstance(outcomes[1], str) and outcomes[1]:
            state.artifacts.append({"kind": "plot_description", "text": outcomes[1]})

        await emit(emitter, EventType.STEP_END, id="review", ok=True, duration_ms=state.elapsed_ms)

    async def _describe_plot(self, image: str, session: Session) -> str:
        try:
            return await llm_provider.describe_image(
                image, model=session.models.vision, provider=session.models.vision_provider
            )
        except Exception as exc:
            logger.debug("Vision description unavailable", error=str(exc))
            return ""

    # ------------------------------------------------------------------ #
    # Answer synthesis
    # ------------------------------------------------------------------ #
    async def _answer(self, state: RunState, session: Session, emitter: Emitter | None):
        """Streams a written answer built from the real execution output.

        Previously the raw stdout was returned and the *frontend* stripped
        tracebacks, numeric rows and code blocks out of it with regexes -- which
        also deleted legitimate results. Synthesis belongs here, with the output
        available.
        """
        state.phase = Phase.ANSWERING
        await emit(emitter, EventType.STATUS, content="Writing the answer", phase=Phase.ANSWERING.value)

        prompt = create_answer_prompt(state.instruction, state.code, state.output, state.plan)

        chunks: list[str] = []

        async def on_delta(delta: str):
            chunks.append(delta)
            await emit(emitter, EventType.CONTENT_DELTA, content=delta)

        try:
            await llm_provider.stream_to(
                prompt,
                on_delta=on_delta,
                role=LLMRole.MANAGER,
                model=session.models.manager,
                temperature=session.models.temperature,
                provider=session.models.manager_provider,
            )
            state.answer = "".join(chunks).strip()
        except LLMUnavailableError:
            # Falling back to raw output is strictly better than failing the turn.
            state.answer = state.output
            await emit(emitter, EventType.CONTENT_DELTA, content=state.answer)

        if not state.answer:
            state.answer = state.output or "The analysis completed but produced no output."

    # ------------------------------------------------------------------ #
    async def _finalize(self, state: RunState, session: Session, emitter: Emitter | None):
        """Persists what was learned and emits the terminal event."""
        columns = [str(c) for c in session.df.columns] if session.df is not None else []

        if state.code and not state.error and not state.blocked:
            semantic_cache.add(state.instruction, columns, state.code)

            if state.retry_count > 0 and state.failed_code:
                try:
                    from src.core.database import db_mgr
                    from src.core.embeddings import embedding_service

                    db_mgr.save_trajectory(
                        instruction=state.instruction,
                        columns=columns,
                        failed_code=state.failed_code,
                        error_message=state.failed_error,
                        corrected_code=state.code,
                        embedding=embedding_service.encode(state.instruction.strip().lower()),
                    )
                    logger.info("Recorded a failure-recovery trajectory")
                except Exception as exc:
                    logger.error("Could not record trajectory", error=str(exc))

        quality = Evaluator.score_execution(state.output, instruction=state.instruction)
        working_memory.add_interaction(
            instruction=state.instruction,
            plan=state.plan,
            code=state.code,
            result=state.answer or state.output,
            meta={"quality_score": quality.get("score", 100), "cached": state.from_cache},
            session_id=session.id,
        )
        session.append_message("assistant", state.answer, {"code": state.code})

        state.phase = Phase.DONE
        downloads = self._collect_downloads(state, session)
        await emit(
            emitter,
            EventType.FINAL,
            response=state.answer,
            code=state.code,
            artifacts=state.artifacts,
            warnings=state.warnings,
            downloads=downloads,
            elapsed_ms=state.elapsed_ms,
        )

    @staticmethod
    def _collect_downloads(state: RunState, session: Session) -> list[str]:
        """Files the run actually produced in the session workspace."""
        reserved = {"dataset.csv", "dataset.feather", "plot.html"}
        try:
            return sorted(
                path.name
                for path in session.workspace.iterdir()
                if path.is_file() and path.name not in reserved and not path.name.startswith(".")
            )
        except OSError:
            return []

    @staticmethod
    def _result(state: RunState, status: str) -> RunResult:
        return RunResult(
            answer=state.answer,
            code=state.code,
            thought=state.thought,
            plan=state.plan,
            image=state.image,
            status=status,
            artifacts=state.artifacts,
            warnings=state.warnings,
            pending_approval=state.pending_approval,
            elapsed_ms=state.elapsed_ms,
        )


orchestrator = AnalysisOrchestrator()
