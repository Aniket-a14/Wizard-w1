package daemon

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

// TestLiveAtDetectsPidReuse guards the fix for a stale pid file naming an
// unrelated process: if the identity token recorded at WritePID time no
// longer matches what processStartTime reports for that pid now, LiveAt must
// report not-alive even though the pid itself is still running -- otherwise
// `wizard stop` could force-kill whatever process the OS happened to reuse
// the pid for.
func TestLiveAtDetectsPidReuse(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "reused.pid")

	if err := WritePID(path, os.Getpid()); err != nil {
		t.Fatalf("WritePID: %v", err)
	}
	current, err := processStartTime(os.Getpid())
	if err != nil || current == "" {
		t.Skip("processStartTime is unavailable on this host; pid-reuse detection cannot be exercised")
	}

	// Simulate a pid file written for a different, earlier process that
	// happened to get this same pid: same pid, a start-time token that
	// cannot possibly match the current process's real one.
	stale := strconv.Itoa(os.Getpid()) + "\n" + current + "-stale"
	if err := os.WriteFile(path, []byte(stale), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, alive := LiveAt(path); alive {
		t.Fatal("expected LiveAt to report not-alive for a pid file whose identity token does not match the running process")
	}
}

// TestLiveAtFallsBackWhenIdentityUnrecorded covers the pre-Milestone-8.x
// on-disk format (bare pid, no second line) and the case where
// processStartTime was unavailable when WritePID ran: with no token to
// compare against, LiveAt cannot disprove ownership, so it must fall back to
// plain pid liveness rather than refusing to report anything.
func TestLiveAtFallsBackWhenIdentityUnrecorded(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "no-token.pid")
	if err := os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0o600); err != nil {
		t.Fatal(err)
	}

	pid, alive := LiveAt(path)
	if !alive || pid != os.Getpid() {
		t.Fatalf("LiveAt = (%d, %v), want (%d, true)", pid, alive, os.Getpid())
	}
}
