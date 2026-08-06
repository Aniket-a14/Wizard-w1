package commands

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadEnvValueFindsKey(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	content := "# comment\nAPP_NAME=\"Wizard\"\nEXECUTION_BACKEND=docker\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}

	value, found := readEnvValue(path, "EXECUTION_BACKEND")
	if !found || value != "docker" {
		t.Fatalf("got (%q, %v), want (\"docker\", true)", value, found)
	}
}

func TestReadEnvValueStripsQuotes(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	if err := os.WriteFile(path, []byte(`APP_NAME="Wizard"`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	value, found := readEnvValue(path, "APP_NAME")
	if !found || value != "Wizard" {
		t.Fatalf("got (%q, %v), want (\"Wizard\", true)", value, found)
	}
}

func TestReadEnvValueLastAssignmentWins(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	content := "EXECUTION_BACKEND=host\nEXECUTION_BACKEND=docker\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	value, found := readEnvValue(path, "EXECUTION_BACKEND")
	if !found || value != "docker" {
		t.Fatalf("got (%q, %v), want (\"docker\", true)", value, found)
	}
}

func TestReadEnvValueMissingFile(t *testing.T) {
	_, found := readEnvValue(filepath.Join(t.TempDir(), "nope.env"), "ANY")
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
	_, found := readEnvValue(path, "EXECUTION_BACKEND")
	if found {
		t.Fatal("expected found=false for a key that is not present")
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
