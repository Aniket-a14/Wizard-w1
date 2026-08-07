//go:build windows

package daemon

import (
	"fmt"
	"os/exec"
	"strconv"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
)

// applyPlatformAttrs puts the child in its own process group. Windows has no
// SIGTERM, so a process group is what lets a graceful stop request
// (CTRL_BREAK_EVENT, below) reach the child and anything it spawned without
// also reaching this supervisor -- the same technique
// backend/src/core/tools/host_runtime.py already uses to interrupt a single
// generated-code execution, applied here to a whole child process instead.
func applyPlatformAttrs(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: windows.CREATE_NEW_PROCESS_GROUP}
}

// terminateChild attempts CTRL_BREAK_EVENT to the child's process group
// first, then -- because generated Python/Node code has no obligation to
// handle that the way a well-behaved CLI does -- falls back to `taskkill
// /T /F`, which recurses the whole process tree through the OS itself rather
// than this binary trying to enumerate it.
//
// In practice the fallback is the only path that actually stops anything
// here: GenerateConsoleCtrlEvent only reaches a process sharing a console
// with the caller, and `__supervise` (this package's one caller in
// production, via detachAttrs below) runs with CREATE_NEW_PROCESS_GROUP |
// DETACHED_PROCESS -- no console at all -- so it has no console to share.
// The call is kept anyway: it is a single harmless API call, and it becomes
// real if this package is ever driven from a process that does have a
// console (a foreground, non-detached use). Do not read the grace-period
// wait below as "usually graceful, occasionally forced" on the shipped
// binary; on Windows it is forced termination on a timer, every time.
func terminateChild(c *Child, grace time.Duration) error {
	pid := uint32(c.Pid())
	_ = windows.GenerateConsoleCtrlEvent(windows.CTRL_BREAK_EVENT, pid)

	select {
	case <-c.Done():
		return nil
	case <-time.After(grace):
	}

	kill := exec.Command("taskkill", "/PID", strconv.Itoa(int(pid)), "/T", "/F")
	_ = kill.Run()
	<-c.Done()
	return nil
}

// IsAlive reports whether pid names a running process, via a limited-access
// handle so this never needs to run elevated just to check.
func IsAlive(pid int) bool {
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return false
	}
	defer windows.CloseHandle(handle)

	var exitCode uint32
	if err := windows.GetExitCodeProcess(handle, &exitCode); err != nil {
		return false
	}
	return exitCode == 259 // STILL_ACTIVE
}

// detachAttrs is applied to the re-exec'd `__supervise` process. Its own
// process group (no console attached) keeps it running after `wizard start`
// exits and its terminal closes.
func detachAttrs(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: windows.CREATE_NEW_PROCESS_GROUP | windows.DETACHED_PROCESS}
}

// KillPID forces a process tree to stop, given only a bare pid recorded in a
// pid file -- `wizard stop`'s fallback for when the supervisor did not clean
// up in time and there is no live *Child, just a number on disk.
//
// pid <= 1 is refused outright, matching process_unix.go's KillPID: it is
// never a pid this package could have legitimately recorded (see
// WritePID/LiveAt in pidfile.go), so treating one as an ordinary target is
// always a bug upstream.
func KillPID(pid int) error {
	if pid <= 1 {
		return fmt.Errorf("refusing to signal pid %d", pid)
	}
	return exec.Command("taskkill", "/PID", strconv.Itoa(pid), "/T", "/F").Run()
}

// processStartTime returns an opaque, comparable token identifying when pid
// started, used to detect pid reuse (see LiveAt in pidfile.go): a stale pid
// file naming a live but unrelated process (the recorded pid got recycled by
// the OS) must not be mistaken for the process this file was written for.
func processStartTime(pid int) (string, error) {
	handle, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return "", err
	}
	defer windows.CloseHandle(handle)

	var creation, exit, kernel, user windows.Filetime
	if err := windows.GetProcessTimes(handle, &creation, &exit, &kernel, &user); err != nil {
		return "", err
	}
	return strconv.FormatUint(uint64(creation.HighDateTime)<<32|uint64(creation.LowDateTime), 10), nil
}
