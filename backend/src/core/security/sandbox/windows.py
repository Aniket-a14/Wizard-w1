"""Windows containment: a job object and a low integrity level.

This is where the ``RLIMIT_AS``-on-POSIX-only gap closes. Windows has no
``setrlimit``, and the previous answer was to document the ceiling rather than
apply it -- a job object applies it, needs no ``pywin32``, and adds a process
cap and kill-on-close at the same time.

The integrity level is the filesystem half. A Low-IL process can still *read*
almost everything, because the default mandatory policy is no-write-up, so the
interpreter and its libraries keep working while writes outside the workspace
are refused by the kernel. The workspace is labelled Low so the child can still
write where it is supposed to.

Deliberately **not** AppContainer, which is the mechanism that would also block
outbound network: it would require granting the container identity access to the
user's Python installation, and a virtualenv under a user profile is exactly
where that goes wrong. Windows therefore reports network as unenforced, which
:mod:`capability` states with the reason rather than leaving blank.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from src.utils.logging import logger


# Job object
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_ulong),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_ulong),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_ulong),
        ("SchedulingClass", ctypes.c_ulong),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_job(mem_bytes: int, max_processes: int):
    """A job object carrying the memory and process ceilings, or ``None``.

    The handle is returned so the caller can hold it: ``KILL_ON_JOB_CLOSE``
    means the child dies when the last handle goes, which is the behaviour that
    stops an orphaned runtime outliving the backend.
    """
    if sys.platform != "win32":
        return None

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.warning("Could not create a job object", error=ctypes.get_last_error())
        return None

    info = _ExtendedLimitInformation()
    flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if mem_bytes > 0:
        info.ProcessMemoryLimit = mem_bytes
        flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
    if max_processes > 0:
        info.BasicLimitInformation.ActiveProcessLimit = max_processes
        flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    info.BasicLimitInformation.LimitFlags = flags

    if not kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    ):
        logger.warning("Could not set job object limits", error=ctypes.get_last_error())
        kernel32.CloseHandle(job)
        return None
    return job


def assign_to_job(job, process: subprocess.Popen) -> bool:
    """Puts a running child into the job.

    Assignment happens just after spawn rather than through ``CREATE_SUSPENDED``,
    because ``subprocess`` closes the child's thread handle and there is nothing
    left to resume. The gap is the few microseconds of interpreter startup
    before any generated code exists, and the limits bound analysis code that
    runs seconds later -- so this is a real but narrow difference from assigning
    pre-resume, and it is written down rather than glossed over.
    """
    if job is None or sys.platform != "win32":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handle = getattr(process, "_handle", None)
    if handle is None:
        return False
    if not kernel32.AssignProcessToJobObject(job, int(handle)):
        logger.warning("Could not assign the runtime to its job object", error=ctypes.get_last_error())
        return False
    return True


def close_job(job) -> None:
    if job is None or sys.platform != "win32":
        return
    try:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)  # type: ignore[attr-defined]
    except OSError:
        pass


def label_workspace_low(workspace: Path) -> bool:
    """Labels the workspace Low so a Low-IL child can still write to it.

    ``icacls`` rather than ``SetNamedSecurityInfo``: the mandatory label is one
    ACE in the SACL, building it through ctypes is a great deal of surface for a
    one-line effect, and `core/credentials.py` already established `icacls` as
    how this codebase adjusts Windows ACLs.
    """
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv; the path is ours, not user input
            ["icacls", str(workspace), "/setintegritylevel", "(OI)(CI)Low"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not label the workspace Low", error=str(exc))
        return False
    if result.returncode != 0:
        logger.warning(
            "icacls refused the integrity label",
            detail=(result.stdout or b"").decode("utf-8", "replace").strip(),
        )
        return False
    return True


__all__ = ["assign_to_job", "close_job", "create_job", "label_workspace_low"]
