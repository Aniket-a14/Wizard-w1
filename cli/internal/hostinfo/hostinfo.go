// Package hostinfo reads this machine's total physical RAM.
//
// This is a Go port of the RAM figure backend/src/utils/hostinfo.py reads
// (host_info().ram_bytes), kept in lockstep by hand rather than shared code --
// a Go process cannot import the Python module, the same reason
// internal/appdir gives for reimplementing config_dir(). Only RAM is ported:
// hostinfo.py's core-count detection feeds LLM_NUM_THREAD sizing, an axis
// `wizard init` never touches, so porting it here would be a second copy of
// logic kept in sync for no behavior this command has.
package hostinfo

// TotalRAMBytes is implemented per-OS in hostinfo_windows.go /
// hostinfo_linux.go / hostinfo_darwin.go, split by build-tag filename the
// same way internal/daemon splits process control. See each file's doc
// comment for the underlying API. An error means detection failed (an
// unsupported OS, a syscall failure) -- callers must treat that as
// "unknown," not as zero bytes of RAM.
