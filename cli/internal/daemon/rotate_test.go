package daemon

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRotatingWriterRotatesOnceOverLimit(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.log")

	w, err := NewRotatingWriter(path, 10, 2)
	if err != nil {
		t.Fatalf("NewRotatingWriter: %v", err)
	}
	defer w.Close()

	if _, err := w.Write([]byte("12345")); err != nil { // 5 bytes, under limit
		t.Fatalf("write 1: %v", err)
	}
	if _, err := w.Write([]byte("67890")); err != nil { // 10 bytes total, still under
		t.Fatalf("write 2: %v", err)
	}
	if _, err := w.Write([]byte("rotateme")); err != nil { // pushes over limit -> rotates first
		t.Fatalf("write 3: %v", err)
	}

	backup := path + ".1"
	if _, err := os.Stat(backup); err != nil {
		t.Fatalf("expected a rotated backup at %s: %v", backup, err)
	}

	backupContents, err := os.ReadFile(backup)
	if err != nil {
		t.Fatalf("reading backup: %v", err)
	}
	if !strings.Contains(string(backupContents), "1234567890") {
		t.Fatalf("backup missing the pre-rotation content: %q", backupContents)
	}

	current, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading current: %v", err)
	}
	if string(current) != "rotateme" {
		t.Fatalf("got current content %q, want %q", current, "rotateme")
	}
}

func TestRotatingWriterKeepsBoundedBackups(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bounded.log")

	w, err := NewRotatingWriter(path, 4, 2)
	if err != nil {
		t.Fatalf("NewRotatingWriter: %v", err)
	}
	defer w.Close()

	// Each write is large enough to force a rotation on the next write.
	for i := 0; i < 5; i++ {
		if _, err := w.Write([]byte("xxxxx")); err != nil {
			t.Fatalf("write %d: %v", i, err)
		}
	}

	if _, err := os.Stat(path + ".3"); !os.IsNotExist(err) {
		t.Fatalf("expected no third backup with Backups=2, got err=%v", err)
	}
	if _, err := os.Stat(path + ".2"); err != nil {
		t.Fatalf("expected a second backup to exist: %v", err)
	}
}
