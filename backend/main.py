"""Command-line interface.

A thin REPL over the same session + orchestrator stack the API uses, so CLI
behaviour cannot drift from the web behaviour -- and, since Milestone 6, the
``skills`` subcommands over the same install machinery the REST routes use, for
the same reason.

Milestone 8 replaces this with a static ``wizard`` binary. It will front these
functions rather than reimplement the fetch: a second implementation of "resolve
a ref, refuse an executable payload, show the contents before installing" is a
second place for that boundary to be got wrong.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import settings  # noqa: E402
from src.core.agent.flow import science_agent  # noqa: E402
from src.core.ingest.loader import DatasetLoader  # noqa: E402
from src.core.session import session_manager  # noqa: E402
from src.core.skills import install  # noqa: E402
from src.core.skills.fetch import FetchError, save_token, token_saved  # noqa: E402
from src.core.skills.index import install_index  # noqa: E402
from src.core.skills.registry import skill_registry  # noqa: E402
from src.core.skills.spec import SkillError  # noqa: E402
from src.core.tools.catalog import CatalogEngine  # noqa: E402


def load_dataset_local(file_path: str):
    """Loads a dataset from disk using the same loader the API uses."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    return DatasetLoader.load(path)


def run_repl(dataset_path: str, mode: str) -> int:
    try:
        result = load_dataset_local(dataset_path)
    except Exception as exc:
        print(f"Could not load the dataset: {exc}", file=sys.stderr)
        return 1

    session = session_manager.create()
    session.add_dataset(
        name=Path(dataset_path).name,
        df=result.df,
        catalog=CatalogEngine.analyze(result.df),
        profile=result.profile.to_dict(),
        source_format=result.source_format,
    )

    print(f"\n{settings.APP_NAME} — CLI ({settings.ENV})")
    print(f"Loaded {len(result.df):,} rows x {len(result.df.columns)} columns from {dataset_path}")
    for warning in result.warnings:
        print(f"  note: {warning}")
    print("Columns:", ", ".join(map(str, result.df.columns[:20])))
    print("\nType a question, 'help' for commands, or 'exit' to quit.\n")

    try:
        while True:
            instruction = input("you > ").strip()
            if not instruction:
                continue
            if instruction.lower() in {"exit", "quit"}:
                break
            if instruction.lower() == "help":
                print("  exit          quit\n  columns       list columns\n  reset         clear sandbox variables")
                continue
            if instruction.lower() == "columns":
                print(", ".join(map(str, result.df.columns)))
                continue
            if instruction.lower() == "reset":
                session.executor.reset()
                print("Sandbox namespace cleared.")
                continue

            session.append_message("user", instruction)
            print("\nthinking...\n")
            answer, code, _image, thought, status = science_agent.run(instruction, session, mode=mode)

            if thought:
                print(f"[reasoning] {thought}\n")
            if status == "waiting_confirmation":
                print(f"[plan]\n{answer}\n")
                if input("Run this plan? [y/N] ").strip().lower() in {"y", "yes"}:
                    answer, code, _image, _thought, _status = science_agent.run(
                        instruction, session, mode="fast", approved_plan=answer
                    )
                else:
                    print("Cancelled.\n")
                    continue

            if code:
                print(f"[code]\n{code}\n")
            print(f"wizard > {answer}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")
    finally:
        session_manager.drop(session.id)
    return 0


# ---------------------------------------------------------------------- #
# Skills
# ---------------------------------------------------------------------- #
def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def skills_add(url: str, assume_yes: bool) -> int:
    """Fetches a source, prints every skill in full, and installs what is approved.

    The contents are printed **before** the question, every time. This is the
    milestone's "never silent-install-and-run" in its most literal form: the thing
    being consented to is on the screen at the moment of consent, and `--yes` is
    the only way past it -- which is what a user asks for when they are scripting
    a machine they already trust.
    """
    try:
        staged = install.preview(url)
    except FetchError as exc:
        print(f"Could not fetch: {exc}", file=sys.stderr)
        return 1
    except SkillError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    if not staged:
        print("Nothing to install.")
        return 1

    print(f"\nPinned to commit {staged[0].sha} ({staged[0].short_sha}) — this is what gets installed.")
    print("An update later is a deliberate step that shows a diff first.\n")

    installed = 0
    for item in staged:
        print("=" * 72)
        print(f"{item.name} — {item.description}")
        print(f"from {item.source.url}")
        if item.conflicts_with:
            print(f"NOTE: a {item.conflict_layer} skill called '{item.conflicts_with}' already exists.")
            if item.conflict_layer == "project":
                print("      That one takes precedence, so this copy would not be the one the agent reads.")
        print("=" * 72)
        print(item.body)
        print("=" * 72)

        if not assume_yes and not _confirm(f"Install '{item.name}'?"):
            install.discard(item.id)
            print(f"Skipped '{item.name}'. Nothing was written.\n")
            continue
        try:
            skill = install.approve(item.id)
        except SkillError as exc:
            print(f"Could not install '{item.name}': {exc}", file=sys.stderr)
            continue
        installed += 1
        print(f"Installed '{skill.name}' to {skill.path}\n")

    print(f"{installed} skill(s) installed.")
    return 0 if installed else 1


def skills_list() -> int:
    for skill in skill_registry.list(include_shadowed=True):
        record = install_index.get(skill.name)
        origin = f"{record.source.url} @ {record.short_sha}" if record else skill.path
        shadow = f"  (overridden by the {skill.shadowed_by} copy)" if skill.shadowed_by else ""
        print(f"{skill.layer.value:<8} {skill.name:<28} {origin}{shadow}")

    staged = install.pending()
    if staged:
        print(f"\n{len(staged)} skill(s) fetched and awaiting review:")
        for item in staged:
            print(f"  {item.id}  {item.name} — {item.source.url} @ {item.short_sha}")
        print("Review them in the app, or discard with `skills remove <name>` after installing.")
    return 0


def skills_update(name: str | None, assume_yes: bool) -> int:
    """Shows what upstream changed, and applies it only when told to."""
    targets = [name] if name else [record.name for record in install_index.list()]
    if not targets:
        print("No skills were installed from a repository, so there is nothing to update.")
        return 0

    for target in targets:
        try:
            result = install.check_update(target)
        except FetchError as exc:
            print(f"{target}: could not fetch — {exc}", file=sys.stderr)
            continue
        except SkillError as exc:
            print(f"{target}: {exc}", file=sys.stderr)
            continue

        if not result.changed:
            print(f"{target}: {result.message}")
            continue

        print(f"\n{target}: {result.message}")
        print(result.diff)
        if not assume_yes and not _confirm(f"Apply this update to '{target}'?"):
            print("Left as it is. The installed copy is unchanged.")
            continue
        try:
            applied = install.apply_update(target)
        except SkillError as exc:
            print(f"{target}: {exc}", file=sys.stderr)
            continue
        print(applied.message)
    return 0


def skills_remove(name: str) -> int:
    try:
        removed = install.uninstall(name)
    except SkillError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    if not removed:
        print(f"No skill called '{name}'.", file=sys.stderr)
        return 1
    print(f"Removed '{name}'.")
    return 0


def skills_token(token: str | None) -> int:
    if token is None:
        print("A GitHub token is saved." if token_saved() else "No GitHub token is saved.")
        print("Without one, GitHub allows 60 requests an hour and no private repositories.")
        return 0
    save_token(token)
    print("Saved." if token.strip() else "Removed the stored token.")
    return 0


# ---------------------------------------------------------------------- #
#: Dispatched on before argparse sees anything. An optional positional
#: (``dataset``) and a subparser cannot coexist in one parser: argparse binds
#: ``skills`` to the positional and then fails on ``list`` as an unknown command.
#: Two parsers, chosen by the first word, keeps `python main.py data.csv` -- the
#: invocation the docs have always given -- working exactly as before.
SUBCOMMANDS = frozenset({"skills"})


def _build_repl_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wizard data analysis agent (CLI).")
    parser.add_argument("dataset", nargs="?", help="Path to a CSV/Excel/JSON/Parquet file.")
    parser.add_argument(
        "--mode",
        choices=["planning", "fast"],
        default="fast",
        help="'planning' asks for confirmation before executing (default: fast).",
    )
    parser.epilog = "Subcommands: skills (add | list | update | remove | token). Try `skills --help`."
    return parser


def _build_skills_parser() -> argparse.ArgumentParser:
    skills = argparse.ArgumentParser(prog="main.py skills", description="Install and manage reusable know-how.")
    actions = skills.add_subparsers(dest="action", required=True)

    add = actions.add_parser("add", help="Install skills from a GitHub repository or gist.")
    add.add_argument("url", help="e.g. https://github.com/owner/repo, owner/repo@tag, or a gist URL.")
    add.add_argument("--yes", action="store_true", help="Install without stopping to confirm each skill.")

    actions.add_parser("list", help="Every installed skill, and where it came from.")

    update = actions.add_parser("update", help="Re-resolve the pinned ref and show what changed.")
    update.add_argument("name", nargs="?", help="One skill; omit for every installed skill.")
    update.add_argument("--yes", action="store_true", help="Apply without confirming the diff.")

    remove = actions.add_parser("remove", help="Uninstall a skill.")
    remove.add_argument("name")

    token = actions.add_parser("token", help="Save, clear or report the GitHub token.")
    token.add_argument("value", nargs="?", help="The token; pass an empty string to clear it. Omit to report.")
    return skills


def _run_skills(argv: list[str]) -> int:
    parser = _build_skills_parser()
    args = parser.parse_args(argv)
    if args.action == "add":
        return skills_add(args.url, args.yes)
    if args.action == "list":
        return skills_list()
    if args.action == "update":
        return skills_update(args.name, args.yes)
    if args.action == "remove":
        return skills_remove(args.name)
    if args.action == "token":
        return skills_token(args.value)
    parser.error(f"Unknown skills action: {args.action}")
    return 2  # pragma: no cover - parser.error exits


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in SUBCOMMANDS:
        return _run_skills(arguments[1:])

    parser = _build_repl_parser()
    args = parser.parse_args(arguments)
    dataset_path = args.dataset or input("Dataset path: ").strip()
    if not dataset_path:
        parser.error("A dataset path is required.")
    return run_repl(dataset_path, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
