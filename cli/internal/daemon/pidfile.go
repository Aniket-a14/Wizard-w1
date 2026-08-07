package daemon

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// WritePID records pid, plus a best-effort process-identity token (see
// processStartTime, implemented per-platform in process_unix.go/
// process_windows.go), in the file at path, overwriting anything already
// there. The token lets LiveAt notice when an OS has recycled a recorded pid
// onto an unrelated process, rather than trusting bare pid liveness forever.
func WritePID(path string, pid int) error {
	started, _ := processStartTime(pid) // best-effort; "" if unavailable, checked as "unverifiable" below
	return os.WriteFile(path, []byte(strconv.Itoa(pid)+"\n"+started), 0o600)
}

// ReadPID reads back the pid WritePID wrote, ignoring the identity token --
// for callers that only ever want the number (log messages, "wizard status"
// display). A missing file is reported as a plain os.ErrNotExist so callers
// can treat "never started" the same way as "cleanly stopped" (the file is
// removed on clean shutdown).
func ReadPID(path string) (int, error) {
	rec, err := readPIDRecord(path)
	if err != nil {
		return 0, err
	}
	return rec.pid, nil
}

type pidRecord struct {
	pid     int
	started string // opaque identity token from processStartTime; "" if it was unavailable when written
}

func readPIDRecord(path string) (pidRecord, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return pidRecord{}, err
	}
	lines := strings.SplitN(strings.TrimSpace(string(raw)), "\n", 2)
	pid, err := strconv.Atoi(strings.TrimSpace(lines[0]))
	if err != nil {
		return pidRecord{}, fmt.Errorf("pid file %s does not contain a valid pid: %w", path, err)
	}
	rec := pidRecord{pid: pid}
	if len(lines) > 1 {
		rec.started = strings.TrimSpace(lines[1])
	}
	return rec, nil
}

// RemovePID deletes the pid file, ignoring "already gone".
func RemovePID(path string) error {
	err := os.Remove(path)
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

// LiveAt reports whether path names a pid file whose process is still
// running -- and, when the identity token WritePID recorded can be
// cross-checked, whether it is still the *same* process. A pid the OS has
// recycled onto an unrelated process is reported as not alive: a stale pid
// file must never make an unrelated process look like a running Wizard
// daemon, since callers escalate a "still alive" report to a forced kill
// (see cli/internal/commands/stop.go's forceKill).
//
// When the token cannot be checked -- it was unavailable at write time, or
// processStartTime fails now (the current process's identity cannot be
// read, `ps`/GetProcessTimes unavailable) -- ownership is unverifiable, and
// this falls back to bare pid liveness rather than refusing to report
// anything: a pidfile-based tool that could never say "yes it's running"
// without a process-identity API present on every machine would not be able
// to do its one job on a stripped-down system.
func LiveAt(path string) (pid int, alive bool) {
	rec, err := readPIDRecord(path)
	if err != nil {
		return 0, false
	}
	if !IsAlive(rec.pid) {
		return 0, false
	}
	if rec.started != "" {
		if current, err := processStartTime(rec.pid); err == nil && current != "" && current != rec.started {
			return 0, false // the pid is alive, but as a different process than the one recorded
		}
	}
	return rec.pid, true
}
