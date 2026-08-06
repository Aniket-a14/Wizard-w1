//go:build windows

package daemon

import (
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

// terminateChild first asks nicely (CTRL_BREAK_EVENT to the child's process
// group), then -- because generated Python/Node code has no obligation to
// handle that the way a well-behaved CLI does -- falls back to `taskkill
// /T /F`, which recurses the whole process tree through the OS itself rather
// than this binary trying to enumerate it.
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
func KillPID(pid int) error {
	return exec.Command("taskkill", "/PID", strconv.Itoa(pid), "/T", "/F").Run()
}
