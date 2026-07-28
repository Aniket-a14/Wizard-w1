from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Deliberately not under `core.infra`: `Settings` is constructed at import time,
# and that package's __init__ imports the cache, which imports `settings` back.
from src.utils.hostinfo import host_info


# Every backend the runtime can talk to. "ollama" and "lmstudio" are local
# daemons; the other two are OpenAI-compatible endpoints reached over HTTP.
Provider = Literal["ollama", "lmstudio", "openai", "custom_gateway"]

PROVIDERS: tuple[str, ...] = ("ollama", "lmstudio", "openai", "custom_gateway")

# Providers whose model list can be enumerated without the user configuring a
# URL first, and which therefore always appear in the picker.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "lmstudio"})


# How the agentic loop is sized for the model actually behind it.
#
# The loop asks a model to choose its next action from real execution output.
# A frontier model does that well and is worth giving a long leash; a 1.5B local
# model does it badly and every extra iteration is another chance to wander, so
# it gets a short budget, a smaller action menu and deterministic fallbacks.
# One codebase, three shapes -- rather than three code paths.
AgentTier = Literal["compact", "balanced", "full"]


@dataclass(frozen=True)
class TierBudget:
    """Per-tier limits for one analysis turn."""

    #: Which tier produced this budget. Carried on the object so callers can
    #: report it without reverse-matching the numbers back to a tier.
    tier: str
    #: Iterations allowed in `auto` mode before the agent must answer.
    iterations: int
    #: Iterations allowed when the user explicitly asks for a deep run.
    deep_iterations: int
    #: Columns of schema detail spent per prompt.
    max_columns: int
    #: Retrieved context-document chunks injected per decision.
    doc_chunks: int
    #: Whether the agent may spend a whole iteration on reflection alone.
    #: Small models reliably waste it restating the question.
    allow_reflection: bool
    #: Whether verification re-derives the result with a second execution.
    allow_verification: bool
    #: Characters of prior-step output carried into the next decision.
    observation_chars: int
    #: Whether the *model* chooses the next action, or the loop does.
    #:
    #: Asking costs a manager round-trip per iteration, and on a small model it
    #: buys nothing: it reads a 1500-character transcript and picks from three
    #: options it does not reliably distinguish. Worse, a reasoning distill
    #: spends its whole output budget deliberating and returns nothing usable,
    #: so the round-trip is paid and the default is taken anyway. Below the
    #: balanced tier the loop is therefore deterministic -- run the code, correct
    #: it if it fails, answer -- which is the shape a compact model executes well
    #: and turns a nine-call turn into a three-call one.
    allow_decisions: bool = True


TIER_BUDGETS: dict[str, TierBudget] = {
    "compact": TierBudget(
        tier="compact",
        iterations=3,
        deep_iterations=5,
        max_columns=25,
        doc_chunks=2,
        allow_reflection=False,
        allow_verification=False,
        observation_chars=1500,
        allow_decisions=False,
    ),
    "balanced": TierBudget(
        tier="balanced",
        iterations=8,
        deep_iterations=14,
        max_columns=60,
        doc_chunks=4,
        allow_reflection=True,
        allow_verification=True,
        observation_chars=4000,
    ),
    "full": TierBudget(
        tier="full",
        iterations=12,
        deep_iterations=24,
        max_columns=120,
        doc_chunks=6,
        allow_reflection=True,
        allow_verification=True,
        observation_chars=8000,
    ),
}

# Below this many billions of parameters a model cannot be trusted to steer its
# own multi-step investigation. The boundary is drawn between the 3B and 7B
# classes because that is where instruction-following on structured action
# selection becomes reliable enough to be worth the round-trip.
COMPACT_MAX_PARAMS_B = 4.0
FULL_MIN_PARAMS_B = 30.0


#: Docker's memory-limit suffixes, which are what `SANDBOX_MEM_LIMIT` speaks.
_MEMORY_UNITS: dict[str, int] = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}


def parse_memory(value: str | int | None) -> int | None:
    """``"2g"`` -> bytes. Returns ``None`` for anything unreadable.

    Total by design: this parses a hand-edited .env value, and a typo there
    should cost a default rather than a failed boot.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip().lower().rstrip("ib")  # accepts "2gib" and "2gb"
    if not text:
        return None
    unit = _MEMORY_UNITS.get(text[-1:], None)
    number = text[:-1] if unit else text
    try:
        parsed = float(number)
    except ValueError:
        return None
    return int(parsed * (unit or 1)) or None


def format_memory(num_bytes: int) -> str:
    """Bytes -> a readable Docker suffix form (``"2g"``, ``"512m"``).

    Rounded *down* to a whole gigabyte, or to 256 MB below that. A derived limit
    is an approximation of what the machine can spare, and printing it as
    ``2057637k`` reads like a measurement it is not -- someone comparing it
    against their .env should see a number they could have typed.
    """
    gigabyte = 1024**3
    if num_bytes >= gigabyte:
        return f"{num_bytes // gigabyte}g"
    step = 256 * 1024**2
    return f"{max(1, (num_bytes // step) * step // (1024**2))}m"


def tier_for_parameter_size(parameter_size: str | None) -> AgentTier:
    """Maps a reported parameter count ("1.5B", "7B", "70B") onto a tier.

    Returns ``"balanced"`` for anything unparseable, which is every hosted
    gateway model -- they do not report a size and are not small.
    """
    if not parameter_size:
        return "balanced"
    cleaned = str(parameter_size).strip().upper().rstrip("B")
    try:
        billions = float(cleaned)
    except ValueError:
        return "balanced"
    if billions <= 0:
        return "balanced"
    if billions < COMPACT_MAX_PARAMS_B:
        return "compact"
    if billions >= FULL_MIN_PARAMS_B:
        return "full"
    return "balanced"


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Wizard AI Agent"
    ENV: Literal["dev", "prod", "test"] = "dev"
    BASE_DIR: Path = Path(__file__).parent.parent

    # Adaptive hardware profile. "auto" measures the host at boot; the three
    # named profiles pin it. This was previously read by nothing at all, so
    # every resource default was a server's regardless of what it said.
    SYSTEM_PROFILE: Literal["auto", "laptop", "server", "hpc"] = "auto"

    # Model Configuration
    # NOTE: MODEL_TYPE is retained only so existing .env files keep validating.
    # API_PROVIDER is the value the runtime actually branches on, and it is only
    # the *default*: a session may pick a different provider per role.
    #
    # The three role models default to EMPTY, which means "use whatever this
    # provider actually has installed", resolved through `model_registry`.
    # Naming a model here pins it as an override. They were previously hardcoded
    # to specific Ollama tags, which made those two models load-bearing: the tag
    # is a 404 on LM Studio or any gateway, and a fresh install with different
    # models pulled would fail on the first request with an opaque error.
    MODEL_TYPE: Provider = "ollama"
    MODEL_NAME: str = ""
    WORKER_MODEL_NAME: str = ""
    VISION_MODEL_NAME: str = ""
    OLLAMA_BASE_URL: str = "http://host.docker.internal:11434"
    FEEDBACK_FILE: str = "feedback_data.json"

    # ------------------------------------------------------------------ #
    # Embeddings
    #
    # These used to come from `sentence-transformers`, which depends on torch --
    # and on Linux/x86_64 torch installs eleven NVIDIA CUDA wheels unconditionally,
    # whether or not a GPU exists. That is ~2.8 GB of compressed wheels to run a
    # 90 MB MiniLM model, and it was by far the largest thing in the API image.
    #
    # The model server this app already talks to can embed: Ollama exposes
    # POST /api/embed, and every OpenAI-compatible server exposes /v1/embeddings.
    # Using it costs nothing on disk and follows whichever provider is selected.
    # Resolution order is remote -> local sentence-transformers (only if the user
    # installed it) -> the built-in hashing encoder, which always works offline.
    # ------------------------------------------------------------------ #
    #: Keep-alive for a model that cannot share memory with the other role.
    #: Short on purpose: it must expire while the *other* model is working, so
    #: its memory is released before that one needs it. One deliberate reload per
    #: role change is bounded; two oversized models competing for RAM is not.
    LLM_KEEP_ALIVE_SWAP: str = "30s"
    #: Share of system RAM the model server may be planned against. The rest is
    #: the OS, this backend, the sandbox and the user's desktop. 0 means "use the
    #: built-in default"; raise it on a machine that does nothing else.
    MODEL_MEMORY_FRACTION: float = 0.0

    EMBEDDINGS_REMOTE_ENABLED: bool = True
    #: Which provider to embed against. Empty follows API_PROVIDER.
    EMBEDDING_PROVIDER: str = ""
    #: Remote embedding model id. Empty means "discover one from this provider",
    #: which is right because the name differs per backend and per install.
    EMBEDDING_REMOTE_MODEL: str = ""
    EMBEDDING_TIMEOUT: float = 20.0
    #: Timeout for the *first* call only, which is a different operation: the
    #: server has to read the model off disk before it can embed anything. On a
    #: laptop with a cold page cache that took over 20s while every subsequent
    #: encode took 0.05s -- so the steady-state timeout rejected an encoder that
    #: works, and the install silently fell back to lexical retrieval for good.
    #: It is affordable precisely because warm-up no longer runs inside a turn.
    EMBEDDING_COLD_TIMEOUT: float = 180.0
    #: Resolve the encoder in the background at startup rather than inside the
    #: first question. Turning this off restores lazy resolution, where the cost
    #: of a cold model load is paid by whoever asks first.
    EMBEDDINGS_WARM_ON_STARTUP: bool = True
    #: Local sentence-transformers model, used only when that optional package
    #: is installed. Unchanged so existing .env files keep their meaning.
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    #: Download it if it is not already on disk. Off by default: a 90 MB fetch is
    #: not something a question should trigger, and the provider path is better
    #: anyway. It stays available for deliberately offline installs.
    EMBEDDING_ALLOW_DOWNLOAD: bool = False

    # LM Studio. Stored as a bare root because two API surfaces hang off it:
    # `/v1` (OpenAI-compatible, used for inference) and `/api/v0` (native, used
    # for discovery -- it reports real capabilities and load state).
    # LM Studio binds loopback only by default; enable "Serve on Local Network"
    # for the backend container to reach the host.
    LMSTUDIO_BASE_URL: str = "http://host.docker.internal:1234"
    LMSTUDIO_API_KEY: str = ""  # LM Studio ignores it; present for proxies that don't

    # ------------------------------------------------------------------ #
    # Where generated code runs
    #
    # Two supported backends, not one backend and an apology:
    #
    #   docker     one container per session. Real isolation, ~700 MB image.
    #   local      one *subprocess* per session running the same daemon over a
    #              loopback socket. No Docker, no image, but still a separate
    #              process -- so a runaway allocation, an infinite loop or a
    #              segfault takes down the child and not the API.
    #   inprocess  guarded `exec` inside the API process. No isolation at all.
    #              Kept for CI and for environments where spawning is blocked.
    #
    # "auto" prefers docker and falls back to local, which is what someone who
    # simply has not installed Docker should get.
    # ------------------------------------------------------------------ #
    EXECUTION_BACKEND: Literal["auto", "docker", "local", "inprocess"] = "auto"
    #: Seconds to wait for a freshly spawned local runtime to accept connections.
    #: It imports pandas and matplotlib first, which is seconds on a slow disk.
    LOCAL_RUNTIME_START_TIMEOUT: float = 60.0
    #: Address-space ceiling for a local runtime, mirroring SANDBOX_MEM_LIMIT.
    #: Enforced through RLIMIT_AS on POSIX only -- Windows has no equivalent that
    #: does not require pywin32, so there the cap is documented, not enforced.
    LOCAL_RUNTIME_MEM_LIMIT: str = ""
    #: Whether a local runtime may pip-install a missing package on demand.
    #: Off by default: unlike a container, it would be installing into the
    #: environment the backend itself runs in.
    LOCAL_RUNTIME_ALLOW_PIP: bool = False

    # Sandbox
    #
    # How much of the analysis toolkit the image carries. The libraries are no
    # longer declared to the model from a hand-maintained list -- the runtime is
    # asked what it actually has -- so a smaller image simply advertises less
    # rather than promising something that then fails to import.
    #
    #   core      pandas, numpy, pyarrow, matplotlib, duckdb, openpyxl
    #   standard  + scipy, statsmodels, scikit-learn, xgboost-cpu, lightgbm,
    #             plotly, seaborn, networkx, pillow, xlsxwriter, tabulate
    #   full      + lifelines, geopandas, shapely
    SANDBOX_TIER: Literal["core", "standard", "full"] = "standard"
    #: Overrides the image tag. Empty derives it from the tier, so switching
    #: tiers cannot silently reuse an image built with different libraries.
    SANDBOX_IMAGE: str = ""
    SANDBOX_NETWORK_DISABLED: bool = False
    SANDBOX_DOCKER_RUNTIME: str = ""
    SANDBOX_MEM_LIMIT: str = "2g"
    SANDBOX_CPU_QUOTA: int = 0  # 0 = unlimited; 100000 == 1 CPU
    SANDBOX_PIDS_LIMIT: int = 256
    SANDBOX_EXEC_TIMEOUT: int = 180  # seconds per code execution
    SANDBOX_ALLOW_RUNTIME_PIP: bool = True
    # When False the sandbox container is never created (unit tests / CI / no Docker host).
    SANDBOX_ENABLED: bool = True

    # Enterprise / Cloud API Provider Config
    API_PROVIDER: Provider = "ollama"
    GATEWAY_API_URL: str = ""
    GATEWAY_API_KEY: str = ""
    PLOT_FORMAT: Literal["png", "html"] = "html"

    # ------------------------------------------------------------------ #
    # Inference
    #
    # MAX_TOKENS is a *ceiling*, not a target -- but it used to be the only
    # number, so every call was allowed 4096 tokens of output regardless of what
    # it was for. That is free when a model stops on its own and ruinous when it
    # does not: a reasoning distill asked to pick one word from a three-item menu
    # will happily spend the entire budget deliberating, which on a CPU-bound
    # 1.5B model is four minutes for a decision worth sixty tokens. The per-call
    # budgets below are what each kind of call actually needs.
    # ------------------------------------------------------------------ #
    MAX_TOKENS: int = 4096
    TEMPERATURE: float = 0.0
    #: Context window requested from Ollama. Derived from the host when unset --
    #: this is a *load-time* parameter, so it fixes the KV cache Ollama allocates
    #: for every resident model, and two models at 16k on a 16 GB laptop is the
    #: difference between both staying warm and one being evicted on every
    #: manager/worker alternation. Not sent to OpenAI-compatible servers, which
    #: fix context length when the model is loaded.
    LLM_NUM_CTX: int = 0
    #: Inference threads. Derived from physical cores when unset.
    LLM_NUM_THREAD: int = 0
    LLM_REQUEST_TIMEOUT: int = 300
    #: How long a provider should keep a model resident after answering. The
    #: manager and worker alternate all turn, so an eviction between them costs a
    #: full reload from disk on every single iteration. Ollama's own default is
    #: five minutes, which a slow turn can exceed while it is still running.
    LLM_KEEP_ALIVE: str = "30m"

    #: Output budget per kind of call. Generous enough that a reasoning model can
    #: finish a thought, small enough that it cannot spend a turn on one.
    LLM_MAX_TOKENS_PLAN: int = 1024
    LLM_MAX_TOKENS_DECISION: int = 512
    LLM_MAX_TOKENS_CODE: int = 1536
    LLM_MAX_TOKENS_ANSWER: int = 1024
    LLM_MAX_TOKENS_REVIEW: int = 256

    MAX_CORRECTION_RETRIES: int = 3

    # ------------------------------------------------------------------ #
    # Agentic loop
    #
    # The analysis is an observe -> decide -> act loop, not a fixed pipeline:
    # the agent sees real execution output and revises what it does next. That
    # is the only shape that answers questions needing several dependent steps,
    # but it costs one manager round-trip per iteration -- so every budget here
    # is scaled by the tier, which is what lets the same code run on a 1.5B
    # local model and on a frontier gateway.
    # ------------------------------------------------------------------ #
    AGENT_TIER: Literal["auto", "compact", "balanced", "full"] = "auto"
    # Hard ceiling regardless of tier or mode. A runaway loop on a paid gateway
    # is a billing incident, so this is deliberately not derived.
    AGENT_MAX_ITERATIONS: int = 24
    # How much of one execution's stdout is fed back into the next decision.
    # The old pipeline passed 200 characters between steps, which silently threw
    # away every intermediate result a later step depended on.
    AGENT_OBSERVATION_CHARS: int = 4000
    # Halt for plan approval before anything runs. Off by default: an agent that
    # asks permission for every question is not autonomous. Web search always
    # asks regardless, because that leaves the machine.
    AGENT_REQUIRE_APPROVAL: bool = False
    # Re-derive the headline result a second way before answering.
    AGENT_VERIFY: bool = True
    # Refuse to present numbers that never appeared in real execution output.
    AGENT_GROUNDING_CHECK: bool = True
    # Emit a reproducible standalone script for each completed analysis.
    AGENT_EMIT_SCRIPT: bool = True
    # Wall-clock ceiling for one turn, in seconds. When it is reached the loop
    # stops starting new work and answers from what it already has, so a slow
    # model degrades into a worse answer rather than into no answer at all.
    # `0` disables it. This is a deadline, not a kill: whatever call is in
    # flight finishes, because cancelling it would throw away work already paid
    # for and leave the provider mid-generation.
    AGENT_TURN_TIMEOUT: float = 300.0

    # Council review (each specialist costs an LLM round-trip)
    COUNCIL_ENABLED: bool = True
    COUNCIL_TIMEOUT: float = 20.0
    VISION_ENABLED: bool = False

    # ------------------------------------------------------------------ #
    # Context documents
    #
    # Hard analytical questions are rarely answerable from the tables alone --
    # they turn on a data dictionary, a fee schedule, a metric definition. These
    # are ingested alongside the datasets, chunked, and retrieved during a run.
    # ------------------------------------------------------------------ #
    CONTEXT_DOCS_ENABLED: bool = True
    CONTEXT_DOC_MAX_BYTES: int = 32 * 1024 * 1024
    CONTEXT_CHUNK_CHARS: int = 1200
    CONTEXT_CHUNK_OVERLAP: int = 150
    CONTEXT_TOP_K: int = 5

    # Ingestion limits
    MAX_UPLOAD_BYTES: int = 512 * 1024 * 1024  # 512MB on disk
    MAX_INMEMORY_ROWS: int = 2_000_000
    PROFILE_SAMPLE_ROWS: int = 200_000  # rows used for profiling/catalog on big data
    PROMPT_MAX_COLUMNS: int = 60  # wide-frame guard for prompt context

    # Sessions
    SESSION_TTL_SECONDS: int = 60 * 60 * 6
    SESSION_MAX_ACTIVE: int = 32
    SESSION_HISTORY_TURNS: int = 8

    # Retrieval / RAG
    # Skips the sentence-transformers download entirely and uses the hashing
    # encoder. Needed for air-gapped installs and for CI, where a per-run model
    # download is both slow and a network-flakiness dependency.
    EMBEDDINGS_FORCE_FALLBACK: bool = False
    RAG_ENABLED: bool = True
    RAG_TOP_K: int = 4
    RAG_MIN_SIMILARITY: float = 0.35
    SEMANTIC_CACHE_THRESHOLD: float = 0.92
    TRAJECTORY_MIN_SIMILARITY: float = 0.90

    # Queue / cache backends. Redis is entirely optional: when REDIS_URL is empty
    # (or the redis package is missing) an in-process implementation is used.
    REDIS_URL: str = ""
    QUEUE_MAX_WORKERS: int = 2
    JOB_RESULT_TTL_SECONDS: int = 3600

    # HTTP / transport security
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    API_KEY: str = ""  # when set, every mutating route requires X-API-Key
    RATE_LIMIT_MAX_REQUESTS: int = 60
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    WS_MAX_CONCURRENT_PER_IP: int = 4

    # Paths
    DATA_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "data")
    LOG_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "logs")
    WORKSPACE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent / "workspace")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("CORS_ALLOW_ORIGINS")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @field_validator("LMSTUDIO_BASE_URL")
    @classmethod
    def _normalize_lmstudio_url(cls, value: str) -> str:
        # LM Studio's own UI displays the endpoint as ".../v1", so that is what
        # people paste. Discovery needs the root, so accept either form.
        cleaned = value.strip().rstrip("/")
        if cleaned.endswith("/v1"):
            cleaned = cleaned[: -len("/v1")]
        return cleaned

    @model_validator(mode="after")
    def _size_to_the_host(self) -> "Settings":
        """Fills resource limits from the measured machine.

        Only fields the user did *not* set are touched -- ``model_fields_set``
        carries everything that came from the environment or the .env, so an
        explicit value always wins and this never silently overrides a choice.

        Without this the shipped defaults describe a server: eight inference
        threads (contention on a four-core laptop) and thirty-two sessions at
        2 GB each, which is sixty-four gigabytes of containers on a machine that
        may have four.
        """
        # Snapshotted: assigning below mutates `model_fields_set` in place, and
        # a later check would then read a field this method had just filled in
        # as though the user had chosen it.
        #
        # A blank string counts as unset. `docker-compose.yml` passes optional
        # knobs as `${SANDBOX_MEM_LIMIT:-}`, and an empty environment variable
        # is still *present* -- so without this, every compose deployment would
        # arrive here looking as though the operator had chosen "".
        explicit = {
            name
            for name in self.model_fields_set
            if not (isinstance(getattr(self, name, None), str) and not getattr(self, name).strip())
        }
        host = host_info()

        if "LLM_NUM_THREAD" not in explicit or self.LLM_NUM_THREAD <= 0:
            # Physical cores. More threads than cores makes local inference
            # slower, not faster -- the work is memory-bandwidth bound.
            self.LLM_NUM_THREAD = max(2, min(16, host.cores))

        if "QUEUE_MAX_WORKERS" not in explicit:
            self.QUEUE_MAX_WORKERS = max(1, min(4, host.cores // 2))

        ram = host.ram_bytes

        if "LLM_NUM_CTX" not in explicit or self.LLM_NUM_CTX <= 0:
            # Sized to what the prompts actually reach, not to what the model
            # permits. Everything built here is budgeted -- the dataset context
            # by column relevance, the transcript by `observation_chars` -- so a
            # full-tier prompt lands near 6k tokens and a compact one near 2k.
            # Asking for more than that does not admit a longer prompt; it
            # reserves KV cache that then has to be found for every resident
            # model, which is how a laptop ends up evicting the worker to make
            # room for the manager on every iteration.
            self.LLM_NUM_CTX = {"laptop": 8192, "server": 16384, "hpc": 32768}.get(host.profile, 8192)

        if "OLLAMA_BASE_URL" not in explicit and not host.containerised:
            # `host.docker.internal` is how a container reaches its host, and it
            # is the right default *in* compose. Outside one it is a name Docker
            # Desktop happens to add to the hosts file, so it resolves on a dev
            # machine with Docker installed and fails outright on one without --
            # which is precisely the Docker-less install the local backend exists
            # to serve. Where we are is already measured, so it is not guessed.
            self.OLLAMA_BASE_URL = self.OLLAMA_BASE_URL.replace("host.docker.internal", "127.0.0.1")

        if "LMSTUDIO_BASE_URL" not in explicit and not host.containerised:
            self.LMSTUDIO_BASE_URL = self.LMSTUDIO_BASE_URL.replace("host.docker.internal", "127.0.0.1")
        if "SANDBOX_MEM_LIMIT" not in explicit and ram:
            # An eighth of RAM per sandbox: enough for a real frame, small
            # enough that several sessions plus a local model still fit.
            per_sandbox = max(512 * 1024**2, min(4 * 1024**3, ram // 8))
            self.SANDBOX_MEM_LIMIT = format_memory(per_sandbox)

        if "SESSION_MAX_ACTIVE" not in explicit and ram:
            # Cap concurrent sandboxes so they cannot collectively claim more
            # than half of RAM, whatever the per-sandbox limit works out to.
            budget = ram // 2
            per_sandbox = parse_memory(self.SANDBOX_MEM_LIMIT) or (1024**3)
            self.SESSION_MAX_ACTIVE = max(1, min(32, int(budget // per_sandbox)))

        if "LOCAL_RUNTIME_MEM_LIMIT" not in explicit:
            # The local runtime is bounded like a container, so switching
            # backends does not silently change how much memory code may take.
            self.LOCAL_RUNTIME_MEM_LIMIT = self.SANDBOX_MEM_LIMIT

        return self

    @property
    def system_profile(self) -> str:
        """The profile in force, with ``auto`` already resolved to the host."""
        if self.SYSTEM_PROFILE != "auto":
            return self.SYSTEM_PROFILE
        return host_info().profile

    # ------------------------------------------------------------------ #
    # Provider resolution
    #
    # A session may run each role on a different backend, so nothing may read
    # a provider's URL directly -- it has to go through these, keyed by the
    # provider actually in play for that call.
    # ------------------------------------------------------------------ #
    def resolve_provider(self, provider: str | None = None) -> str:
        """Falls back to the configured default for an empty or unknown value."""
        candidate = (provider or "").strip().lower()
        return candidate if candidate in PROVIDERS else self.API_PROVIDER

    def provider_root_url(self, provider: str | None = None) -> str:
        """Root URL of the daemon, with no API-version suffix."""
        name = self.resolve_provider(provider)
        if name == "ollama":
            return self.OLLAMA_BASE_URL.rstrip("/")
        if name == "lmstudio":
            return self.LMSTUDIO_BASE_URL.rstrip("/")
        return self.GATEWAY_API_URL.rstrip("/")

    def provider_openai_base_url(self, provider: str | None = None) -> str:
        """The `/v1` base an OpenAI-compatible client should be pointed at."""
        name = self.resolve_provider(provider)
        root = self.provider_root_url(name)
        if name == "lmstudio":
            return f"{root}/v1"
        # A gateway URL is configured by hand and already includes its version
        # segment, so appending one here would break every existing install.
        return root

    def provider_api_key(self, provider: str | None = None) -> str:
        name = self.resolve_provider(provider)
        if name == "lmstudio":
            return self.LMSTUDIO_API_KEY
        return self.GATEWAY_API_KEY

    def provider_is_configured(self, provider: str | None = None) -> bool:
        """Whether this provider has somewhere to connect to."""
        name = self.resolve_provider(provider)
        if name in LOCAL_PROVIDERS:
            return bool(self.provider_root_url(name))
        return bool(self.GATEWAY_API_URL.strip())

    # ------------------------------------------------------------------ #
    # Agent budgeting
    # ------------------------------------------------------------------ #
    def resolve_tier(self, parameter_size: str | None = None) -> AgentTier:
        """The tier to run this turn at.

        An explicit ``AGENT_TIER`` always wins. On ``auto`` the tier is inferred
        from the manager model's reported parameter count, which is the only
        signal available without benchmarking: Ollama reports it per tag, LM
        Studio reports it per model, and hosted gateways report nothing -- for
        which ``balanced`` is the right assumption.
        """
        if self.AGENT_TIER != "auto":
            return self.AGENT_TIER  # type: ignore[return-value]
        return tier_for_parameter_size(parameter_size)

    def budget_for(self, mode: str = "auto", parameter_size: str | None = None) -> TierBudget:
        """Concrete limits for one turn, given the mode and the model behind it."""
        tier = self.resolve_tier(parameter_size)
        budget = TIER_BUDGETS[tier]

        if mode == "fast":
            # One shot: write code, run it, answer. No investigation, and no
            # verification either -- a second execution plus an extra worker
            # round-trip is the single most expensive thing the turn could do,
            # and the user asking for `fast` has said they do not want it.
            return replace(
                budget,
                iterations=1,
                allow_reflection=False,
                allow_verification=False,
                observation_chars=min(budget.observation_chars, self.AGENT_OBSERVATION_CHARS),
            )

        iterations = budget.deep_iterations if mode == "deep" else budget.iterations
        return replace(
            budget,
            iterations=min(iterations, self.AGENT_MAX_ITERATIONS),
            observation_chars=min(budget.observation_chars, self.AGENT_OBSERVATION_CHARS),
            # `deep` restores the decision round-trip even on a compact model.
            # The tier's answer to "should this model steer itself" is a default
            # about what is worth paying for, and someone who reached for `deep`
            # has said the cost is acceptable. Leaving it off would make the
            # control a no-op on exactly the setup where the user is most likely
            # to reach for it -- a small model that gave a shallow first answer.
            allow_decisions=budget.allow_decisions or mode == "deep",
        )

    def output_budget(self, purpose: str) -> int:
        """Tokens one kind of call may produce, clamped to ``MAX_TOKENS``.

        Clamped rather than maxed: ``MAX_TOKENS`` is the ceiling someone lowers
        when their context is small, and a per-purpose budget must not quietly
        raise it back.
        """
        budgets = {
            "plan": self.LLM_MAX_TOKENS_PLAN,
            "decision": self.LLM_MAX_TOKENS_DECISION,
            "code": self.LLM_MAX_TOKENS_CODE,
            "answer": self.LLM_MAX_TOKENS_ANSWER,
            "review": self.LLM_MAX_TOKENS_REVIEW,
        }
        return max(64, min(self.MAX_TOKENS, budgets.get(purpose, self.MAX_TOKENS)))

    @property
    def cors_origins(self) -> list[str]:
        """Parsed CORS allowlist. `*` is honoured but disables credentialed requests."""
        raw = [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",")]
        return [origin for origin in raw if origin]

    @property
    def cors_allow_credentials(self) -> bool:
        # Sending credentials with a wildcard origin is rejected by every browser
        # and is a spec violation, so the two settings are resolved here once.
        return "*" not in self.cors_origins

    @property
    def redis_enabled(self) -> bool:
        return bool(self.REDIS_URL.strip())

    # ------------------------------------------------------------------ #
    # Execution backend
    #
    # Which backends this configuration permits. Whether one is *reachable* is
    # a runtime question and belongs to `core.tools.runtime`, which is why these
    # only express permission -- config cannot import the sandbox without a
    # circular import, and should not need to.
    # ------------------------------------------------------------------ #
    @property
    def docker_backend_allowed(self) -> bool:
        return self.SANDBOX_ENABLED and self.EXECUTION_BACKEND in ("auto", "docker")

    @property
    def local_backend_allowed(self) -> bool:
        return self.EXECUTION_BACKEND in ("auto", "local")

    @property
    def sandbox_image(self) -> str:
        """Image tag for the current tier, unless one was named explicitly."""
        return self.SANDBOX_IMAGE.strip() or f"wizard-sandbox:{self.SANDBOX_TIER}"

    @property
    def local_runtime_mem_bytes(self) -> int:
        """Address-space ceiling for a local runtime, 0 when uncapped."""
        return parse_memory(self.LOCAL_RUNTIME_MEM_LIMIT) or 0


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
settings.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
