package daemon

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// WritePID records pid in the file at path, overwriting anything already
// there.
func WritePID(path string, pid int) error {
	return os.WriteFile(path, []byte(strconv.Itoa(pid)), 0o644)
}

// ReadPID reads back what WritePID wrote. A missing file is reported as a
// plain os.ErrNotExist so callers can treat "never started" the same way as
// "cleanly stopped" (the file is removed on clean shutdown).
func ReadPID(path string) (int, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil {
		return 0, fmt.Errorf("pid file %s does not contain a valid pid: %w", path, err)
	}
	return pid, nil
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
// running. False for a missing file or a dead pid -- both mean "not
// running" to every caller in this package.
func LiveAt(path string) (pid int, alive bool) {
	pid, err := ReadPID(path)
	if err != nil {
		return 0, false
	}
	return pid, IsAlive(pid)
}
