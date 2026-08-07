package commands

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestReadEnvValueFindsKey(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	content := "# comment\nAPP_NAME=\"Wizard\"\nEXECUTION_BACKEND=docker\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	value, found, err := readEnvValue(path, "EXECUTION_BACKEND")
	if err != nil || !found || value != "docker" {
		t.Fatalf("got (%q, %v, %v), want (\"docker\", true, nil)", value, found, err)
	}
}

func TestReadEnvValueStripsQuotes(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	if err := os.WriteFile(path, []byte(`APP_NAME="Wizard"`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	value, found, err := readEnvValue(path, "APP_NAME")
	if err != nil || !found || value != "Wizard" {
		t.Fatalf("got (%q, %v, %v), want (\"Wizard\", true, nil)", value, found, err)
	}
}

func TestReadEnvValueLastAssignmentWins(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	content := "EXECUTION_BACKEND=host\nEXECUTION_BACKEND=docker\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	value, found, err := readEnvValue(path, "EXECUTION_BACKEND")
	if err != nil || !found || value != "docker" {
		t.Fatalf("got (%q, %v, %v), want (\"docker\", true, nil)", value, found, err)
	}
}

func TestReadEnvValueMissingFile(t *testing.T) {
	_, found, err := readEnvValue(filepath.Join(t.TempDir(), "nope.env"), "ANY")
	if err != nil {
		t.Fatalf("expected no error for a missing file, got %v", err)
	}
	if found {
		t.Fatal("expected found=false for a missing file")
	}
}

func TestReadEnvValueMissingKey(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	if err := os.WriteFile(path, []byte("OTHER=1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, found, err := readEnvValue(path, "EXECUTION_BACKEND")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if found {
		t.Fatal("expected found=false for a key that is not present")
	}
}

func TestReadEnvValueOversizedLineReturnsError(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	// bufio.Scanner's default max token size is 64KiB; one line past that
	// must surface as an error, not as a silent found=false.
	huge := "EXECUTION_BACKEND=" + strings.Repeat("x", 100*1024) + "\n"
	if err := os.WriteFile(path, []byte(huge), 0o644); err != nil {
		t.Fatal(err)
	}
	_, found, err := readEnvValue(path, "EXECUTION_BACKEND")
	if err == nil {
		t.Fatal("expected an error for a line exceeding the scanner's token limit")
	}
	if found {
		t.Fatal("expected found=false alongside the error")
	}
}

func TestReadAPIVersionFromSource(t *testing.T) {
	dir := t.TempDir()
	metaDir := filepath.Join(dir, "backend", "src", "api", "routes")
	if err := os.MkdirAll(metaDir, 0o755); err != nil {
		t.Fatal(err)
	}
	content := "API_VERSION = \"3.1.0\"\n"
	if err := os.WriteFile(filepath.Join(metaDir, "meta.py"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	env := &Env{RepoRoot: dir, BackendDir: filepath.Join(dir, "backend")}
	version, err := readAPIVersionFromSource(env)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version != "3.1.0" {
		t.Fatalf("got %q, want %q", version, "3.1.0")
	}
}
