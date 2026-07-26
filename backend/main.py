"""Command-line interface.

A thin REPL over the same session + orchestrator stack the API uses, so CLI
behaviour cannot drift from the web behaviour.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Wizard w1 data analysis agent (CLI).")
    parser.add_argument("dataset", nargs="?", help="Path to a CSV/Excel/JSON/Parquet file.")
    parser.add_argument(
        "--mode",
        choices=["planning", "fast"],
        default="fast",
        help="'planning' asks for confirmation before executing (default: fast).",
    )
    args = parser.parse_args()

    dataset_path = args.dataset or input("Dataset path: ").strip()
    if not dataset_path:
        parser.error("A dataset path is required.")
    return run_repl(dataset_path, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
