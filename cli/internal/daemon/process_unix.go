//go:build !windows

package daemon

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// applyPlatformAttrs puts the child in its own process group (setsid) so a
// signal sent to -pid reaches it and anything it spawns, without also
// reaching this supervisor.
func applyPlatformAttrs(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

// terminateChild sends SIGTERM to the whole process group, waits up to
// grace, and escalates to SIGKILL if the process is still alive.
func terminateChild(c *Child, grace time.Duration) error {
	pgid := c.cmd.Process.Pid // setsid makes the leader's pid the pgid
	_ = syscall.Kill(-pgid, syscall.SIGTERM)

	select {
	case <-c.Done():
		return nil
	case <-time.After(grace):
	}

	_ = syscall.Kill(-pgid, syscall.SIGKILL)
	<-c.Done()
	return nil
}

// IsAlive reports whether pid names a running process. Sending signal 0
// performs no action but still fails with ESRCH if the process is gone, or
// succeeds (or fails with EPERM, meaning it exists but is owned by someone
// else) if it is still there.
func IsAlive(pid int) bool {
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	err = process.Signal(syscall.Signal(0))
	if err == nil {
		return true
	}
	if errors.Is(err, os.ErrProcessDone) {
		return false
	}
	return errors.Is(err, syscall.EPERM)
}

// detachAttrs is applied to the re-exec'd `__supervise` process so it
// survives the `wizard start` command that launched it returning and its
// terminal closing.
func detachAttrs(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

// KillPID forces a process (and, since it was spawned with Setsid, its
// process group) to stop, given only a bare pid recorded in a pid file --
// `wizard stop`'s fallback for when the supervisor did not clean up in time
// and there is no live *Child, just a number on disk.
//
// pid <= 1 is refused outright: kill(-1, ...) is a broadcast to every
// process the caller may signal, and kill(-0/-1 as a group, ...) is never a
// pid this package could have legitimately recorded (see WritePID/LiveAt),
// so treating one as an ordinary target is always a bug upstream, not a
// process actually worth signaling.
func KillPID(pid int) error {
	if pid <= 1 {
		return fmt.Errorf("refusing to signal pid %d (would broadcast rather than target one process)", pid)
	}
	_ = syscall.Kill(-pid, syscall.SIGKILL)
	return syscall.Kill(pid, syscall.SIGKILL)
}

// processStartTime returns an opaque, comparable token identifying when pid
// started, used to detect pid reuse (see LiveAt in pidfile.go). There is no
// portable syscall for this in the stdlib across Linux and macOS -- /proc is
// Linux-only -- so this shells out to `ps`, which both platforms ship. A
// failure here (ps missing, pid gone) is reported as an error, and callers
// treat that as "ownership unverifiable" rather than as proof of anything.
func processStartTime(pid int) (string, error) {
	out, err := exec.Command("ps", "-o", "lstart=", "-p", strconv.Itoa(pid)).Output()
	if err != nil {
		return "", err
	}
	started := strings.TrimSpace(string(out))
	if started == "" {
		return "", fmt.Errorf("ps reported no start time for pid %d", pid)
	}
	return started, nil
}
