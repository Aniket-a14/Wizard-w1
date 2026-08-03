"""The analysis loop.

This is an observe -> decide -> act agent, not a pipeline. Each iteration the
manager sees what has actually been run and what it produced, and chooses the
next move; the loop ends when the agent says it can answer, or when its budget
runs out.

    orient  ->  [approval gate]  ->  loop  ->  verify  ->  answer
                                      |
                       inspect / code+execute / consult / reflect
                                      |
                                 (correct on failure)

Why not the previous shape
--------------------------
It used to fix a plan before touching the data, then execute it step by step,
feeding 200 characters of each step's output into the next. That cannot recover
when the data contradicts the plan -- which is the ordinary case for a real
question, where you learn the join key is dirty or the status column has four
spellings only after you look. `DABstep <https://arxiv.org/abs/2506.23719>`_
measures this directly: its hard tasks need six or more dependent steps, the
best model scores 14.55% on them against 76.39% on single-step ones, and the
largest error category is planning -- agents "missed necessary intermediate
calculations" or "hallucinate incorrect analysis plans" precisely because the
plan was committed before the evidence existed.

Sizing
------
Every iteration costs a manager round-trip, so the budget comes from
``settings.budget_for(mode, parameter_size)``. A 1.5B local model gets four
iterations, no reflection and no verification pass; a frontier model gets
twenty-four. Same code, three shapes.

Fixes carried in from the earlier audit, still load-bearing
-----------------------------------------------------------
* ``error`` is cleared on a successful execution, so the semantic cache and the
  trajectory memory are written after a self-heal -- the exact situation they
  exist to capture.
* Guard verdicts distinguish "malformed code" (retry) from "policy violation"
  (stop), rather than terminating the run as ``completed`` in both cases.
* The Council and the vision model are awaited concurrently and are individually
  optional, rather than serialising extra LLM calls into every response.
"""

from __future__ import annotations

import asyncio
import posixpath
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.config import TierBudget, settings
from src.core.agent.actions import ActionKind, Decision, Investigation, Step, parse_decision
from src.core.agent.consent import ConsentRequest, consent_broker
from src.core.agent.council import TheCouncil
from src.core.agent.events import Emitter, EventType, Phase, emit
from src.core.agent.grounding import (
    GroundingReport,
    assumptions_from_code,
    assumptions_from_profile,
    check_grounding,
)
from src.core.data_mode import should_redact, tool_allowed, tool_refusal
from src.core.execution import ExecutionResult
from src.core.feedback_store import FeedbackStore
from src.core.llm import LLMRole, llm_provider, model_registry
from src.core.llm.provider import DataModeViolation, LLMUnavailableError
from src.core.llm.reasoning import ReasoningStream, split_reasoning, strip_reasoning
from src.core.llm.usage import usage_ledger
from src.core.memory import working_memory
from src.core.permissions import denial_reason, unattended_reason
from src.core.prompts import (
    create_answer_prompt,
    create_decision_prompt,
    create_planning_prompt,
    create_prompt,
    create_reflection_prompt,
    create_replan_prompt,
    create_verification_prompt,
)
from src.core.rag.retriever import context_retriever
from src.core.security.code_guard import imported_modules
from src.core.semantic_cache import semantic_cache
from src.core.tools import runtime as runtime_backend
from src.core.tools.evaluator import Evaluator
from src.utils.logging import logger


if TYPE_CHECKING:
    from src.core.session import Session


SEARCH_PATTERN = re.compile(r'SEARCH:\s*"(.*?)"')

#: Lines the verification step is asked to print, and what they mean.
VERIFIED_MARKER = "VERIFIED:"
MISMATCH_MARKER = "MISMATCH:"

VISUAL_KEYWORDS = frozenset(
    {"color", "colour", "legend", "font", "axis", "label", "grid", "title", "theme", "style", "palette", "annotate"}
)

#: Requests whose answer is a single deterministic frame operation. Routing
#: these without a planning round-trip is the one piece of the old keyword
#: router worth keeping: it is free, it is never wrong for these phrasings, and
#: it saves a full manager call on the most common question a user asks first.
#: Everything else now goes to the loop, which decides its own depth.
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

#: Modes accepted from the transport. ``planning`` is the legacy name for
#: "investigate thoroughly but let me approve the plan first", kept so existing
#: clients and stored sessions keep working.
MODES = ("auto", "fast", "deep", "planning")


@dataclass
class RunState:
    """Everything one analysis turn needs to carry."""

    instruction: str
    mode: str = "auto"
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

    investigation: Investigation = field(default_factory=Investigation)
    iterations_used: int = 0
    tier: str = "balanced"

    failed_code: str = ""
    failed_error: str = ""
    from_cache: bool = False
    warnings: list[str] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    #: Whether the caller can carry a consent question back to a human. False for
    #: REST and the CLI, where an `ask` has nobody to ask and must resolve to a
    #: stated denial rather than parking the request.
    can_prompt: bool = False
    verification: str = ""
    grounding: GroundingReport = field(default_factory=GroundingReport)
    usage: dict[str, Any] = field(default_factory=dict)
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
    findings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    iterations: int = 0
    tier: str = "balanced"
    mode: str = "auto"
    verification: str = ""
    grounding: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

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
            "findings": self.findings,
            "assumptions": self.assumptions,
            "iterations": self.iterations,
            "tier": self.tier,
            "mode": self.mode,
            "verification": self.verification,
            "grounding": self.grounding,
            "usage": self.usage,
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
        """Cheap keyword routing so trivial inspection skips a planning round-trip."""
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

    @staticmethod
    def normalise_mode(mode: str | None) -> str:
        candidate = (mode or "auto").strip().lower()
        return candidate if candidate in MODES else "auto"

    @staticmethod
    def _redact_for(session: Session, role: str) -> bool:
        """Whether the prompt for ``role`` must be stripped of real values.

        Asked per role rather than once per turn: under hybrid the manager may be
        on a cloud provider while the worker is local, and only the cloud-bound
        prompt should lose its sample rows.
        """
        provider = settings.resolve_provider(session.models.provider_for(role))
        # The active dataset, so a table marked more sensitive than the session
        # default is treated that way rather than averaged with the others.
        return should_redact(session.data_mode, session.data_policy, provider, dataset=session.active_dataset)

    async def _budget_for(self, session: Session, mode: str) -> TierBudget:
        """Sizes this turn to the model actually behind the manager role.

        Discovery is a blocking HTTP call with its own cache, so it runs off the
        event loop and never fails the turn -- an unreachable daemon simply
        yields the mid tier.
        """
        parameter_size: str | None = None
        try:
            spec = llm_provider.resolve(
                LLMRole.MANAGER,
                model=session.models.manager,
                provider=session.models.manager_provider,
                # The session's mode, not the configured default: sizing a turn
                # must not be the one call that disagrees about which provider
                # is in play.
                data_mode=session.data_mode,
            )
            parameter_size = await asyncio.to_thread(model_registry.parameter_size_of, spec.model, spec.provider)
        except Exception as exc:
            logger.debug("Could not size the agent budget from the model", error=str(exc))
        return settings.budget_for(mode, parameter_size)

    # ------------------------------------------------------------------ #
    # Consent for actions within a run
    # ------------------------------------------------------------------ #
    async def _permit(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        category: str,
        subject: str,
        prompt: str,
        detail: str = "",
    ) -> bool:
        """Whether one gated action may proceed, asking the user if the profile says to.

        The single place the permission profile is consulted. Every gated action
        goes through here so that adding one is a call site rather than another
        bespoke pause somewhere in the loop -- which is what the plan gate and the
        old web-search prompt had each grown into separately.

        A denial is recorded as a warning rather than raising: the turn continues
        and the loop can route around the step, which is the same way it already
        treats a sub-task that failed.
        """
        permissions = session.permissions
        if permissions.granted(category, subject):
            return True

        ruling = permissions.ruling_for(category)
        if ruling == "allow":
            return True

        if ruling == "deny":
            await self._refuse(state, emitter, denial_reason(category, subject, asked=False))
            return False

        if not state.can_prompt:
            await self._refuse(state, emitter, unattended_reason(category, subject))
            return False

        resume_phase = state.phase
        state.phase = Phase.AWAITING_APPROVAL
        decision = await consent_broker.ask(
            session.id,
            ConsentRequest(category=category, subject=subject, prompt=prompt, detail=detail),
            emitter,
            timeout=settings.AGENT_CONSENT_TIMEOUT,
        )
        # Back to whatever the turn was doing, not to a fixed phase: this gate is
        # reached from planning and from execution alike.
        state.phase = resume_phase

        if not decision.approved:
            reason = decision.reason or denial_reason(category, subject, asked=True)
            await self._refuse(state, emitter, reason)
            return False

        # Remembered for the rest of the session, so an investigation that needs
        # the same library at iterations 4, 5 and 6 asks once rather than thrice.
        permissions.grant(category, subject)
        return True

    async def _refuse(self, state: RunState, emitter: Emitter | None, reason: str) -> None:
        state.warnings.append(reason)
        await emit(emitter, EventType.WARNING, content=reason)

    async def _permit_install(self, state: RunState, session: Session, emitter: Emitter | None, code: str) -> bool:
        """Gates an install the generated code would otherwise trigger.

        Checked statically, before execution. The runtime installs reactively on
        ``ModuleNotFoundError``, which happens *after* the program has started
        running -- so a gate waiting for that signal would be asking permission
        for something that had already happened.
        """
        missing = runtime_backend.missing_modules(imported_modules(code), session.id)
        if not missing:
            return True

        subject = ", ".join(sorted(missing))
        return await self._permit(
            state,
            session,
            emitter,
            "library_install",
            subject,
            f"The analysis needs {subject}, which is not installed. Install it?",
            detail="Installs into the analysis runtime, not into your system Python.",
        )

    async def _permit_paths(self, state: RunState, session: Session, emitter: Emitter | None, paths: list[str]) -> bool:
        """Gates a read or write the guard rejected for being outside the workspace."""
        subject = ", ".join(sorted(set(paths)))
        allowed = await self._permit(
            state,
            session,
            emitter,
            "workspace_write",
            subject,
            f"The analysis wants to use a file outside its workspace: {subject}. Allow it?",
            detail="Grants access for the rest of this session.",
        )
        if not allowed:
            return False

        # The grant widens the guard's roots rather than bypassing the guard, so
        # everything else it checks still applies to the re-scan.
        for path in set(paths):
            session.permissions.allow_root(posixpath.dirname(path.replace("\\", "/")) or path)
        return True

    @staticmethod
    def _drop_search(state: RunState, reason: str) -> None:
        """Strips the SEARCH directive so the run continues without it.

        The plan is still worth carrying out; it just has to be carried out from
        the data at hand. Leaving the directive in would send the model's own
        unmet request into every later prompt as if it had been satisfied.
        """
        state.plan = SEARCH_PATTERN.sub("", state.plan).strip() or state.instruction
        if reason:
            state.warnings.append(reason)

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    async def run(
        self,
        session: Session,
        instruction: str,
        mode: str = "auto",
        emitter: Emitter | None = None,
        approved_plan: str | None = None,
        approved_search: str | None = None,
        previous_code: str | None = None,
        can_prompt: bool = False,
    ) -> RunResult:
        """Executes one turn. Returns when the run completes or pauses for approval.

        ``can_prompt`` says whether this transport can deliver a mid-run consent
        question and carry an answer back. Only the WebSocket can; a REST turn
        has no reply channel, so there an `ask` becomes a denial with a reason
        rather than a request nobody will ever see.
        """
        mode = self.normalise_mode(mode)
        state = RunState(instruction=instruction, mode=mode, can_prompt=can_prompt)

        if session.df is None:
            await emit(emitter, EventType.ERROR, content="No dataset is loaded for this session.")
            return self._result(state, "failed")

        try:
            budget = await self._budget_for(session, mode)
            state.tier = budget.tier

            if approved_search is not None:
                await self._run_search(state, session, approved_search, emitter)
            elif approved_plan is not None:
                # The user confirmed a plan produced by an earlier turn.
                state.plan = approved_plan
            else:
                should_continue = await self._orient(state, session, emitter, previous_code, budget)
                if not should_continue:
                    return self._result(state, "awaiting_approval")

            await self._investigate(state, session, emitter, previous_code, budget)

            if state.blocked:
                await self._finalize(state, session, emitter)
                return self._result(state, "completed")

            await self._verify(state, session, emitter, budget)
            await self._review(state, session, emitter)
            await self._answer(state, session, emitter)
            await self._finalize(state, session, emitter)
            return self._result(state, "completed")

        except DataModeViolation as exc:
            # A policy decision, not a fault: the user's own words back, with no
            # "check that the provider is running" advice attached to them.
            logger.info("Run refused by the data mode", reason=str(exc))
            await emit(emitter, EventType.ERROR, content=str(exc))
            state.answer = str(exc)
            return self._result(state, "failed")
        except LLMUnavailableError as exc:
            message = (
                f"Could not reach the language model: {exc}. "
                "Check that the provider is running and that a model is installed."
            )
            logger.error("Run aborted, LLM unavailable", error=str(exc))
            await emit(emitter, EventType.ERROR, content=message)
            state.answer = message
            return self._result(state, "failed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Run failed unexpectedly", error=str(exc))
            await emit(emitter, EventType.ERROR, content=f"Unexpected failure: {exc}")
            state.answer = f"The analysis failed unexpectedly: {exc}"
            return self._result(state, "failed")

    # ------------------------------------------------------------------ #
    # Orientation: the opening plan
    # ------------------------------------------------------------------ #
    async def _orient(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        previous_code: str | None,
        budget: TierBudget,
    ) -> bool:
        """Produces the opening plan. Returns False when the run pauses for approval.

        The plan is a starting hypothesis, not a contract -- the loop revises it
        as evidence arrives. It is still worth producing: it orients the first
        few actions and it is what the user reads to decide whether the agent
        understood the question.
        """
        columns = [str(c) for c in session.df.columns]

        # 1. Exact/semantic cache: a verified solution for this exact question.
        cached = semantic_cache.lookup(state.instruction, columns)
        if cached:
            state.code = cached
            state.from_cache = True
            state.plan = "Reused a previously verified solution for this question."
            await emit(emitter, EventType.STATUS, content="Reusing a verified solution", phase=Phase.GENERATING.value)
            return True

        # 2. Deterministic fast path for trivial inspection.
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
            # A compact model gets the terse prompt whatever the mode. The
            # standard one asks for a `<thought>` block, which on a reasoning
            # distill means it thinks twice -- once natively and once to order --
            # for a plan that the loop is about to revise from real output anyway.
            mode="fast" if state.mode == "fast" or budget.tier == "compact" else "standard",
            memory_context=working_memory.get_context_string(state.instruction, session_id=session.id),
            previous_code=previous_code if self.is_visual_revision(state.instruction, previous_code) else None,
            session_id=session.id,
            history=session.history_prompt(),
            max_columns=budget.max_columns,
            redact=self._redact_for(session, "manager"),
        )

        raw = await self._stream_plan(prompt, session, emitter)

        # Reasoning is separated here, not just rendered separately. `state.plan`
        # is embedded in every later decision prompt and in the answer prompt, so
        # a chain of thought left in it is re-read by the model on every
        # subsequent call -- which is how one unrecognised tag pair turned into
        # most of a turn.
        state.thought, state.plan = split_reasoning(raw)
        if not state.plan:
            # The model spent its whole budget thinking. Its reasoning is the
            # only thing it produced, and it is better than an empty plan.
            state.plan = state.thought[:1000] or f"Answer the question directly: {state.instruction}"

        await emit(emitter, EventType.STEP_END, id="plan", ok=True, duration_ms=state.elapsed_ms)

        # A plan may request a web search, which leaves the machine. Two layers
        # decide, in this order and never the other way round: the data mode says
        # whether it is possible at all, and only then the permission profile
        # says whether to ask. No profile can consent past the mode.
        search_match = SEARCH_PATTERN.search(state.plan)
        if search_match and not tool_allowed(session.data_mode, "web_search"):
            # Not an approval prompt: under local-only there is no consent that
            # would make this allowed, so asking would be theatre.
            self._drop_search(state, tool_refusal("web_search"))
            await emit(emitter, EventType.WARNING, content=state.warnings[-1])
        elif search_match:
            query = search_match.group(1)
            prompt = f"Wizard wants to search the web for: “{query}”. Allow?"
            if state.can_prompt:
                # Suspend rather than end the turn: the plan is already made, and
                # the old two-turn dance re-planned from scratch on resume.
                allowed = await self._permit(state, session, emitter, "network", query, prompt, detail="Web search")
                if not allowed:
                    self._drop_search(state, "")
                else:
                    await self._run_search(state, session, query, emitter)
            elif session.permissions.ruling_for("network") == "allow":
                await self._run_search(state, session, query, emitter)
            elif session.permissions.ruling_for("network") == "deny":
                self._drop_search(state, denial_reason("network", query, asked=False))
                await emit(emitter, EventType.WARNING, content=state.warnings[-1])
            else:
                # No reply channel, but the search is genuinely worth asking
                # about, so this is the one place the old turn-terminating gate
                # is still the right shape: REST returns and the caller re-asks.
                state.pending_approval = {
                    "tool": "web_search",
                    "query": query,
                    "prompt": prompt,
                    "plan": state.plan,
                }
                state.phase = Phase.AWAITING_APPROVAL
                await emit(emitter, EventType.APPROVAL_REQUIRED, **state.pending_approval)
                return False

        # Plan approval is opt-in. `planning` mode is the legacy way of asking
        # for it per-request; AGENT_REQUIRE_APPROVAL is the deployment-wide way.
        if state.mode == "planning" or settings.AGENT_REQUIRE_APPROVAL:
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

        The model emits a reasoning block then the plan. Rather than waiting for
        the whole response and regex-splitting it afterwards, the tag boundary is
        tracked incrementally so the UI can render a live "thinking" panel that
        switches to the plan at the right moment.

        The tags come from :mod:`src.core.llm.reasoning` rather than being
        spelled out here, because the set that matters is not the one this
        prompt asks for -- a reasoning model emits ``<think>`` whatever it was
        asked for, and that block was previously streamed to the UI as the plan.
        """
        buffer: list[str] = []
        splitter = ReasoningStream()

        async def emit_chunks(chunks: list[tuple[bool, str]]):
            for is_reasoning, text in chunks:
                if not text:
                    continue
                # Text outside a reasoning block is the plan, whether or not a
                # block was ever seen. It previously became a `reasoning_delta`
                # until the first tag arrived, so a plan produced without one --
                # which is every `fast` plan, since that prompt asks for no
                # reasoning block at all -- streamed entirely into the thinking
                # panel and left the plan panel empty.
                await emit(
                    emitter,
                    EventType.REASONING_DELTA if is_reasoning else EventType.PLAN_DELTA,
                    content=text,
                )

        async def on_delta(delta: str):
            buffer.append(delta)
            await emit_chunks(splitter.feed(delta))

        await llm_provider.stream_to(
            prompt,
            on_delta=on_delta,
            role=LLMRole.MANAGER,
            model=session.models.manager,
            temperature=session.models.temperature,
            provider=session.models.manager_provider,
            max_tokens=settings.output_budget("plan"),
            data_mode=session.data_mode,
            session_id=session.id,
        )
        await emit_chunks(splitter.flush())
        return "".join(buffer)

    # ------------------------------------------------------------------ #
    # Web search
    # ------------------------------------------------------------------ #
    async def _run_search(self, state: RunState, session: Session, query: str, emitter: Emitter | None):
        # Re-checked here: the mode can change between the approval and the run.
        if not tool_allowed(session.data_mode, "web_search"):
            refusal = tool_refusal("web_search")
            state.warnings.append(refusal)
            await emit(emitter, EventType.WARNING, content=refusal)
            return

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

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #
    async def _investigate(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        previous_code: str | None,
        budget: TierBudget,
    ):
        """Runs the observe -> decide -> act loop until the agent answers."""
        allowed = self._allowed_actions(session, budget)

        for iteration in range(1, budget.iterations + 1):
            # Checked before the iteration is claimed, never during it: a call
            # in flight is already paid for, and cancelling it would leave the
            # provider mid-generation with nothing to show for the tokens. It
            # also must not increment `iterations_used` first -- the turn would
            # then report an iteration it abandoned before doing any work.
            if iteration > 1 and self._out_of_time(state):
                note = (
                    f"Stopped exploring after {state.elapsed_ms // 1000}s and answered from what was "
                    f"already established. Raise AGENT_TURN_TIMEOUT, or use a smaller model, for a longer run."
                )
                state.warnings.append(note)
                await emit(emitter, EventType.WARNING, content=note)
                logger.info("Turn deadline reached", elapsed_ms=state.elapsed_ms, iteration=iteration)
                break

            state.iterations_used = iteration
            remaining = budget.iterations - iteration

            await emit(
                emitter,
                EventType.ITERATION_START,
                n=iteration,
                budget=budget.iterations,
                mode=state.mode,
            )

            decision = await self._decide(state, session, emitter, iteration, remaining, allowed, budget)

            await emit(
                emitter,
                EventType.ACTION,
                kind=decision.kind.value,
                goal=decision.goal,
                rationale=decision.rationale,
                inferred=decision.inferred,
            )

            if decision.kind is ActionKind.ANSWER:
                break

            if decision.kind is ActionKind.INSPECT:
                await self._act_inspect(state, session, emitter, decision, budget)
            elif decision.kind is ActionKind.CONSULT:
                await self._act_consult(state, session, emitter, decision, budget)
            elif decision.kind is ActionKind.REFLECT:
                await self._act_reflect(state, session, emitter, decision, budget)
            else:
                await self._act_code(state, session, emitter, decision, previous_code, budget)
                if state.blocked:
                    return

        # Whatever the loop produced is what the answer is built from.
        state.output = state.investigation.executed_output or state.output
        state.code = state.investigation.last_successful_code or state.code

    def _allowed_actions(self, session: Session, budget: TierBudget) -> tuple[ActionKind, ...]:
        """The menu offered this turn.

        Options are removed when they cannot succeed: a session with no attached
        documents has nothing to consult, and a compact-tier model reliably
        wastes a reflection iteration restating the question.
        """
        allowed = [ActionKind.INSPECT, ActionKind.CODE, ActionKind.ANSWER]
        if budget.allow_reflection:
            allowed.insert(2, ActionKind.REFLECT)
        if settings.CONTEXT_DOCS_ENABLED and session.has_documents:
            allowed.insert(2, ActionKind.CONSULT)
        return tuple(allowed)

    async def _decide(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        iteration: int,
        remaining: int,
        allowed: tuple[ActionKind, ...],
        budget: TierBudget,
    ) -> Decision:
        """Chooses the next action.

        The first iteration is not put to the model: there is nothing to observe
        yet, so asking costs a round-trip to be told what is already known --
        write the code. In ``fast`` mode that is the only iteration, which makes
        a fast run exactly as cheap as the old single-shot pipeline.
        """
        if iteration == 1:
            return Decision(kind=ActionKind.CODE, goal=state.instruction)

        # A cached solution is executed, not re-decided.
        if state.from_cache and not state.error:
            return Decision(kind=ActionKind.ANSWER, goal="Report the cached result.")

        # Below the balanced tier the loop decides for itself. See
        # `TierBudget.allow_decisions`: the round-trip is real and the choice is
        # not, so it is made from what actually happened instead.
        if not budget.allow_decisions:
            return self._decide_deterministically(state)

        state.phase = Phase.DECIDING
        await emit(emitter, EventType.STATUS, content="Deciding what to do next", phase=Phase.DECIDING.value)

        prompt = create_decision_prompt(
            instruction=state.instruction,
            plan=state.plan,
            transcript=state.investigation.render(budget.observation_chars),
            iteration=iteration,
            remaining=remaining,
            allowed=[kind.value for kind in allowed],
            findings=state.investigation.findings,
        )

        try:
            raw = await llm_provider.acomplete(
                prompt,
                role=LLMRole.MANAGER,
                model=session.models.manager,
                temperature=session.models.temperature,
                provider=session.models.manager_provider,
                max_tokens=settings.output_budget("decision"),
                data_mode=session.data_mode,
                session_id=session.id,
            )
        except LLMUnavailableError:
            # Losing the manager mid-run should not lose the work already done.
            logger.warning("Manager unavailable mid-loop; answering with what is known")
            return Decision(kind=ActionKind.ANSWER, goal="Report what has been established.", inferred=True)

        # Parsed from the visible text only. A chain of thought names every
        # option while it weighs them, so parsing the raw response makes the
        # choice a race between whichever keyword the model happened to mention
        # first while deliberating.
        visible = strip_reasoning(raw)

        # On the last iteration the only useful choice is to answer, so it is
        # made here rather than trusted to a model watching its own budget.
        default = self._decide_deterministically(state).kind if remaining > 0 else ActionKind.ANSWER
        decision = parse_decision(visible, allowed=allowed, default=default)
        if remaining <= 0:
            decision.kind = ActionKind.ANSWER
        return decision

    @staticmethod
    def _decide_deterministically(state: RunState) -> Decision:
        """What to do next, read off what has already happened.

        Used as the whole decision on the compact tier, and as the *default* on
        every tier when the model's answer is unparseable. The old default was
        ``code`` unconditionally, which spent another generate-and-execute cycle
        every time a small model returned prose -- so the failure mode of asking
        a weak model to choose was to keep working rather than to stop.

        Succeeding is the signal to stop. An analysis that ran and printed
        something has produced the material an answer is written from; carrying
        on is how a one-step question turns into a four-iteration turn.
        """
        last = state.investigation.steps[-1] if state.investigation.steps else None
        if last is not None and last.ok and (last.observation or "").strip():
            return Decision(
                kind=ActionKind.ANSWER,
                goal="Report the result that has already been computed.",
                inferred=True,
            )
        return Decision(kind=ActionKind.CODE, goal=state.instruction, inferred=True)

    @staticmethod
    def _out_of_time(state: RunState) -> bool:
        """Whether this turn has spent its wall-clock budget."""
        limit = settings.AGENT_TURN_TIMEOUT
        return limit > 0 and state.elapsed_ms >= limit * 1000

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    async def _act_inspect(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        decision: Decision,
        budget: TierBudget,
    ):
        """Answers a question about the data's shape without an LLM call.

        Schema, dtypes, null structure and value distributions are facts about a
        frame, not something a model needs to write code to discover. Serving
        them directly makes ``inspect`` free, which is what makes it worth
        offering as an action at all.
        """
        state.phase = Phase.INSPECTING
        await emit(emitter, EventType.STATUS, content="Examining the data", phase=Phase.INSPECTING.value)

        summary = await asyncio.to_thread(session.inspect, decision.goal, budget.max_columns)

        state.investigation.record(
            Step(
                index=state.iterations_used,
                kind=ActionKind.INSPECT,
                goal=decision.goal,
                observation=summary,
                ok=True,
            )
        )
        await emit(
            emitter,
            EventType.OBSERVATION,
            summary=summary[: budget.observation_chars],
            ok=True,
            truncated=len(summary) > budget.observation_chars,
            chars=len(summary),
        )

    async def _act_consult(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        decision: Decision,
        budget: TierBudget,
    ):
        """Retrieves from the session's attached reference documents."""
        state.phase = Phase.CONSULTING
        await emit(emitter, EventType.STATUS, content="Consulting reference documents", phase=Phase.CONSULTING.value)

        query = decision.goal or state.instruction
        passages = await asyncio.to_thread(session.search_documents, query, budget.doc_chunks)

        if passages:
            body = "\n\n".join(f"From `{name}`:\n{text}" for name, text in passages)
            for _, text in passages:
                state.investigation.note_finding(text.strip().splitlines()[0][:200])
        else:
            body = "No relevant passage was found in the attached documents."

        state.investigation.record(
            Step(
                index=state.iterations_used,
                kind=ActionKind.CONSULT,
                goal=query,
                observation=body,
                ok=bool(passages),
            )
        )
        await emit(
            emitter,
            EventType.OBSERVATION,
            summary=body[: budget.observation_chars],
            ok=bool(passages),
            truncated=len(body) > budget.observation_chars,
            chars=len(body),
        )

    async def _act_reflect(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        decision: Decision,
        budget: TierBudget,
    ):
        """Rewrites the plan from what execution actually showed."""
        state.phase = Phase.REFLECTING
        await emit(emitter, EventType.STATUS, content="Revising the plan", phase=Phase.REFLECTING.value)

        prompt = create_reflection_prompt(
            state.instruction,
            state.plan,
            state.investigation.render(budget.observation_chars),
        )
        try:
            revised = await llm_provider.acomplete(
                prompt,
                role=LLMRole.MANAGER,
                model=session.models.manager,
                temperature=session.models.temperature,
                provider=session.models.manager_provider,
                max_tokens=settings.output_budget("plan"),
                data_mode=session.data_mode,
                session_id=session.id,
            )
        except LLMUnavailableError:
            return

        # The revised plan replaces `state.plan`, which every later prompt
        # embeds, so a chain of thought left in here is paid for repeatedly.
        revised = strip_reasoning(revised)
        if not revised:
            return

        previous, state.plan = state.plan, revised
        lead = revised.splitlines()[0].strip() if revised.splitlines() else ""
        if lead:
            state.investigation.note_finding(lead)

        state.investigation.record(
            Step(
                index=state.iterations_used,
                kind=ActionKind.REFLECT,
                goal=decision.goal or "Revise the plan",
                observation=revised,
                ok=True,
            )
        )
        await emit(emitter, EventType.PLAN_REVISED, plan=revised, why=lead, previous=previous)

    async def _act_code(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        decision: Decision,
        previous_code: str | None,
        budget: TierBudget,
    ):
        """Writes and runs Python for one subgoal, correcting on failure."""
        goal = decision.goal or state.instruction
        state.error = None
        state.retry_count = 0

        while True:
            await self._generate(state, session, emitter, previous_code, goal, budget)
            if state.error and not state.code:
                state.investigation.record(
                    Step(
                        index=state.iterations_used,
                        kind=ActionKind.CODE,
                        goal=goal,
                        observation=state.error,
                        ok=False,
                    )
                )
                return

            if not await self._permit_install(state, session, emitter, state.code):
                state.investigation.record(
                    Step(
                        index=state.iterations_used,
                        kind=ActionKind.CODE,
                        goal=goal,
                        observation=state.warnings[-1] if state.warnings else "Permission declined.",
                        ok=False,
                        code=state.code,
                    )
                )
                # Not `state.blocked`: the turn continues and the loop can try a
                # route that does not need the library, the same way it routes
                # around a step that failed for any other reason.
                return

            result = await self._execute(state, session, emitter)

            if result.blocked and result.blocked_paths:
                if await self._permit_paths(state, session, emitter, result.blocked_paths):
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
                for note in assumptions_from_code(state.code):
                    state.investigation.note_assumption(note)
                    await emit(emitter, EventType.ASSUMPTION, text=note, kind="code")

                state.investigation.record(
                    Step(
                        index=state.iterations_used,
                        kind=ActionKind.CODE,
                        goal=goal,
                        observation=result.output,
                        ok=True,
                        code=state.code,
                    )
                )
                await emit(
                    emitter,
                    EventType.OBSERVATION,
                    summary=result.output[: budget.observation_chars],
                    ok=True,
                    truncated=len(result.output) > budget.observation_chars,
                    chars=len(result.output),
                )
                return

            state.failed_code = state.code
            state.failed_error = result.output
            state.error = result.output
            state.retry_count += 1
            state.from_cache = False

            if state.retry_count > settings.MAX_CORRECTION_RETRIES:
                state.output = result.output
                logger.warning("Exhausted correction retries", attempts=state.retry_count)
                state.investigation.record(
                    Step(
                        index=state.iterations_used,
                        kind=ActionKind.CODE,
                        goal=goal,
                        observation=result.output,
                        ok=False,
                        code=state.code,
                    )
                )
                await emit(
                    emitter,
                    EventType.OBSERVATION,
                    summary=result.output[: budget.observation_chars],
                    ok=False,
                    truncated=False,
                    chars=len(result.output),
                )
                # The loop continues: a failed sub-task is information, and the
                # agent can route around it on the next iteration.
                return

            state.phase = Phase.CORRECTING
            await emit(
                emitter,
                EventType.STATUS,
                content=f"Fixing an execution error (attempt {state.retry_count} of {settings.MAX_CORRECTION_RETRIES})",
                phase=Phase.CORRECTING.value,
            )

    async def _generate(
        self,
        state: RunState,
        session: Session,
        emitter: Emitter | None,
        previous_code: str | None,
        goal: str,
        budget: TierBudget,
    ):
        if state.from_cache and state.code and not state.error:
            await emit(emitter, EventType.CODE, content=state.code, language="python", cached=True)
            return

        state.phase = Phase.GENERATING
        step_id = f"code-{state.iterations_used}-{state.retry_count}"
        await emit(emitter, EventType.STEP_START, id=step_id, label="Writing Python", kind="code")
        await emit(emitter, EventType.STATUS, content="Writing Python", phase=Phase.GENERATING.value)

        instruction = goal
        if state.investigation.steps:
            # Prior results are carried in full rather than as a 200-character
            # comment, which is what previously made later steps guess at values
            # earlier steps had already computed.
            instruction = (
                f"Overall question: {state.instruction}\n\n"
                f"Work already done:\n{state.investigation.render(budget.observation_chars)}\n\n"
                f"Your task now: {goal}\n\n"
                "Variables defined by earlier successful steps are still in scope. "
                "Write code for THIS task only."
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
            max_columns=budget.max_columns,
            redact=self._redact_for(session, "worker"),
        )

        raw = await llm_provider.acomplete(
            prompt,
            role=LLMRole.WORKER,
            model=session.models.worker,
            temperature=session.models.temperature,
            provider=session.models.worker_provider,
            max_tokens=settings.output_budget("code"),
        )
        state.code = self._extract_code(raw)

        await emit(emitter, EventType.STEP_END, id=step_id, ok=bool(state.code), duration_ms=state.elapsed_ms)
        if state.code:
            await emit(emitter, EventType.CODE, content=state.code, language="python", cached=False)
        else:
            state.error = "The model did not return any code."

    @staticmethod
    def _extract_code(response: str) -> str:
        """Pulls the python block out of a model response.

        Reasoning is removed *first*, and that ordering is the whole point: a
        model thinking out loud drafts code inside ``<think>``, discards it, and
        writes the real answer afterwards -- while this takes the **first**
        fenced block it finds. Searching the raw response therefore runs the
        draft the model already rejected.
        """
        response = strip_reasoning(response)
        fenced = re.search(r"```(?:python|py)?\s*\n(.*?)```", response, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        stripped = response.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
        return stripped

    async def _execute(self, state: RunState, session: Session, emitter: Emitter | None) -> ExecutionResult:
        state.phase = Phase.EXECUTING
        step_id = f"run-{state.iterations_used}-{state.retry_count}"
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
            result = await asyncio.to_thread(
                session.executor.execute,
                state.code,
                session.df,
                on_stdout,
                session.tables,
                session.permissions.extra_roots,
            )
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
    # Verification
    # ------------------------------------------------------------------ #
    async def _verify(self, state: RunState, session: Session, emitter: Emitter | None, budget: TierBudget):
        """Re-derives the headline result by a different route.

        A wrong join grain, a filter in the wrong order or a mean over the wrong
        denominator all produce confident, plausible, wrong numbers that no
        self-review catches -- because the model reviewing is the model that made
        the mistake. An independent recomputation does catch them.
        """
        if not settings.AGENT_VERIFY or not budget.allow_verification:
            return
        if state.blocked or state.error or not state.code or state.from_cache:
            return
        if self._out_of_time(state):
            # A second code generation *and* a second execution. It is the most
            # expensive thing left in the turn, so it is the first thing a
            # deadline gives up.
            logger.info("Skipping verification, turn deadline reached", elapsed_ms=state.elapsed_ms)
            return

        state.phase = Phase.VERIFYING
        await emit(emitter, EventType.STEP_START, id="verify", label="Verifying the result", kind="verify")
        await emit(emitter, EventType.STATUS, content="Verifying the result", phase=Phase.VERIFYING.value)

        try:
            raw = await llm_provider.acomplete(
                create_verification_prompt(state.instruction, state.code, state.output),
                role=LLMRole.WORKER,
                model=session.models.worker,
                temperature=session.models.temperature,
                provider=session.models.worker_provider,
                max_tokens=settings.output_budget("code"),
                data_mode=session.data_mode,
                session_id=session.id,
            )
        except LLMUnavailableError:
            await emit(emitter, EventType.STEP_END, id="verify", ok=False, duration_ms=state.elapsed_ms)
            return

        code = self._extract_code(raw)
        if not code:
            await emit(emitter, EventType.STEP_END, id="verify", ok=False, duration_ms=state.elapsed_ms)
            return

        # Verification is independently generated code, so it can want a library
        # the analysis itself did not. Gating it here is what stops the check
        # being a way round the gate on the thing it is checking.
        if not await self._permit_install(state, session, emitter, code):
            await emit(emitter, EventType.STEP_END, id="verify", ok=False, duration_ms=state.elapsed_ms)
            return

        result = await asyncio.to_thread(
            session.executor.execute, code, session.df, None, session.tables, session.permissions.extra_roots
        )
        output = (result.output or "").strip()

        if not result.ok:
            # A verification that cannot run says nothing about the analysis.
            status, detail = "inconclusive", "The verification step could not be executed."
        elif MISMATCH_MARKER in output:
            status, detail = "mismatch", output
            state.warnings.append(
                "Independent verification disagreed with the analysis. The result below is not trustworthy."
            )
        elif VERIFIED_MARKER in output:
            status, detail = "verified", output
        else:
            status, detail = "inconclusive", output

        state.verification = detail
        await emit(emitter, EventType.VERIFICATION, status=status, detail=detail[:2000])
        await emit(emitter, EventType.STEP_END, id="verify", ok=status != "mismatch", duration_ms=state.elapsed_ms)

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
                image,
                model=session.models.vision,
                provider=session.models.vision_provider,
                data_mode=session.data_mode,
                session_id=session.id,
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
        also deleted legitimate results. Synthesis belongs here, with the whole
        investigation available.
        """
        state.phase = Phase.ANSWERING
        await emit(emitter, EventType.STATUS, content="Writing the answer", phase=Phase.ANSWERING.value)

        handle = session.active_handle
        if handle is not None:
            for note in assumptions_from_profile(handle.profile):
                state.investigation.note_assumption(note)
                await emit(emitter, EventType.ASSUMPTION, text=note, kind="dataset")

        prompt = create_answer_prompt(
            state.instruction,
            state.code,
            state.output,
            state.plan,
            findings=state.investigation.findings,
            assumptions=state.investigation.assumptions,
            verification=state.verification,
        )

        chunks: list[str] = []
        splitter = ReasoningStream()

        async def emit_chunks(pieces: list[tuple[bool, str]]):
            for is_reasoning, text in pieces:
                if not text:
                    continue
                if is_reasoning:
                    # Shown in the thinking panel, never as the answer. A
                    # reasoning manager streamed its whole chain of thought into
                    # the message body, so the user watched it deliberate and
                    # then read the deliberation as the result.
                    await emit(emitter, EventType.REASONING_DELTA, content=text)
                    continue
                chunks.append(text)
                await emit(emitter, EventType.CONTENT_DELTA, content=text)

        async def on_delta(delta: str):
            await emit_chunks(splitter.feed(delta))

        try:
            await llm_provider.stream_to(
                prompt,
                on_delta=on_delta,
                role=LLMRole.MANAGER,
                model=session.models.manager,
                temperature=session.models.temperature,
                provider=session.models.manager_provider,
                max_tokens=settings.output_budget("answer"),
                data_mode=session.data_mode,
                session_id=session.id,
            )
            await emit_chunks(splitter.flush())
            state.answer = "".join(chunks).strip()
        except LLMUnavailableError:
            # Falling back to raw output is strictly better than failing the turn.
            state.answer = state.output
            await emit(emitter, EventType.CONTENT_DELTA, content=state.answer)

        if not state.answer:
            state.answer = state.output or "The analysis completed but produced no output."

        await self._check_grounding(state, emitter)

    async def _check_grounding(self, state: RunState, emitter: Emitter | None):
        """Flags figures in the answer that were never actually computed.

        This reports; it does not edit. Rewriting model output after the fact is
        the mistake this codebase already made once, when the frontend stripped
        numeric rows out of responses and removed real results with them.
        """
        if not settings.AGENT_GROUNDING_CHECK or state.blocked:
            return

        state.grounding = check_grounding(
            state.answer,
            state.investigation.executed_output or state.output,
            state.instruction,
        )
        warning = state.grounding.warning()
        if warning:
            state.warnings.append(warning)
            await emit(emitter, EventType.WARNING, content=warning)
            logger.info(
                "Answer contained ungrounded figures",
                checked=state.grounding.checked,
                ungrounded=len(state.grounding.ungrounded),
            )

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

        script = self._write_script(state, session)
        if script:
            state.artifacts.append({"kind": "script", "name": script})
            await emit(emitter, EventType.ARTIFACT, kind="script", name=script)

        for note in state.investigation.assumptions:
            await emit(emitter, EventType.ASSUMPTION, text=note, kind="summary")

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
        state.usage = usage_ledger.totals(session.id)
        # Only where a meter means something. Under local-only nothing was spent
        # and the honest surface is silence, not a row of zeroes.
        if state.usage.get("any_cloud"):
            await emit(emitter, EventType.USAGE, **state.usage)
        await emit(
            emitter,
            EventType.FINAL,
            response=state.answer,
            code=state.code,
            artifacts=state.artifacts,
            warnings=state.warnings,
            downloads=downloads,
            elapsed_ms=state.elapsed_ms,
            findings=state.investigation.findings,
            assumptions=state.investigation.assumptions,
            iterations=state.iterations_used,
            tier=state.tier,
            grounding=state.grounding.to_dict(),
            verification=state.verification,
            usage=state.usage,
        )

    @staticmethod
    def _write_script(state: RunState, session: Session) -> str:
        """Writes the analysis out as a runnable standalone script.

        An answer is a one-off; a script is an asset that can be re-run next
        month against fresh data, which is what turns ad-hoc analysis into
        something reusable rather than a question someone has to ask again.
        """
        if not settings.AGENT_EMIT_SCRIPT or state.blocked or not state.code:
            return ""

        blocks = [step for step in state.investigation.steps if step.kind is ActionKind.CODE and step.ok and step.code]
        if not blocks:
            return ""

        header = [
            '"""Analysis generated by Wizard.',
            "",
            f"Question: {state.instruction}",
            "",
            "Run against the same dataset to reproduce the result. `df` is loaded",
            "from the exported CSV; point it at fresh data to re-run the analysis.",
            '"""',
            "",
            "import matplotlib.pyplot as plt",
            "import numpy as np",
            "import pandas as pd",
            "import seaborn as sns",
            "",
            'df = pd.read_csv("dataset.csv")',
            "",
        ]
        body: list[str] = []
        for index, step in enumerate(blocks, start=1):
            body.append(f"# --- Step {index}: {step.goal or 'analysis'} " + "-" * 20)
            body.append(step.code)
            body.append("")

        name = "analysis.py"
        try:
            (session.workspace / name).write_text("\n".join(header + body), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write the analysis script", error=str(exc))
            return ""
        return name

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
            findings=state.investigation.findings,
            assumptions=state.investigation.assumptions,
            iterations=state.iterations_used,
            tier=state.tier,
            mode=state.mode,
            verification=state.verification,
            grounding=state.grounding.to_dict(),
            usage=state.usage,
        )


orchestrator = AnalysisOrchestrator()
