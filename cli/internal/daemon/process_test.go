package daemon

import (
	"os"
	"path/filepath"
	"testing"
)

func TestIsAliveTrueForCurrentProcess(t *testing.T) {
	if !IsAlive(os.Getpid()) {
		t.Fatal("expected the current process to be reported alive")
	}
}

func TestIsAliveFalseForImplausiblePid(t *testing.T) {
	// Not a guaranteed-unused pid on every system, but a pid this large is
	// never valid on any of the three target platforms.
	if IsAlive(999999999) {
		t.Fatal("expected an implausible pid to be reported not alive")
	}
}

func TestPidFileRoundTrip(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "daemon.pid")

	if err := WritePID(path, os.Getpid()); err != nil {
		t.Fatalf("WritePID: %v", err)
	}
	pid, err := ReadPID(path)
	if err != nil {
		t.Fatalf("ReadPID: %v", err)
	}
	if pid != os.Getpid() {
		t.Fatalf("got pid %d, want %d", pid, os.Getpid())
	}

	gotPid, alive := LiveAt(path)
	if !alive || gotPid != os.Getpid() {
		t.Fatalf("LiveAt = (%d, %v), want (%d, true)", gotPid, alive, os.Getpid())
	}

	if err := RemovePID(path); err != nil {
		t.Fatalf("RemovePID: %v", err)
	}
	if _, alive := LiveAt(path); alive {
		t.Fatal("expected LiveAt to be false after RemovePID")
	}
	// Removing again must not error -- "already gone" is not a failure.
	if err := RemovePID(path); err != nil {
		t.Fatalf("RemovePID on missing file: %v", err)
	}
}

func TestLiveAtFalseForDeadPid(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "dead.pid")
	if err := WritePID(path, 999999999); err != nil {
		t.Fatalf("WritePID: %v", err)
	}
	if _, alive := LiveAt(path); alive {
		t.Fatal("expected a pid file naming a dead process to report not alive")
	}
}
