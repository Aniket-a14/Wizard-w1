package commands

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func newTestEnv(t *testing.T, backendDir string) *Env {
	t.Helper()
	return &Env{
		RepoRoot:   filepath.Dir(backendDir),
		BackendDir: backendDir,
		Out:        &bytes.Buffer{},
		Err:        &bytes.Buffer{},
	}
}

func writeExampleEnv(t *testing.T, backendDir string) {
	t.Helper()
	content := "APP_NAME=Wizard\n" +
		`MODEL_NAME=""                   # plans and reasons; empty = auto-select` + "\n" +
		`WORKER_MODEL_NAME=""            # writes the Python; empty = auto-select` + "\n"
	if err := os.WriteFile(filepath.Join(backendDir, ".env.example"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestEnsureEnvFileNoOverridePreservesAutoSelect(t *testing.T) {
	backendDir := filepath.Join(t.TempDir(), "backend")
	if err := os.MkdirAll(backendDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExampleEnv(t, backendDir)
	env := newTestEnv(t, backendDir)

	if err := ensureEnvFile(env, false, "qwen3:8b", "qwen2.5-coder:7b"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	value, found, err := readEnvValue(env.BackendEnvPath(), "MODEL_NAME")
	if err != nil || !found {
		t.Fatalf("got (%q, %v, %v)", value, found, err)
	}
	if value != "" {
		t.Fatalf("MODEL_NAME = %q, want empty (auto-select) when the pair was not overridden", value)
	}
}

func TestEnsureEnvFileAppliesOverride(t *testing.T) {
	backendDir := filepath.Join(t.TempDir(), "backend")
	if err := os.MkdirAll(backendDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExampleEnv(t, backendDir)
	env := newTestEnv(t, backendDir)

	if err := ensureEnvFile(env, true, fallbackSingleModel, fallbackSingleModel); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	for _, key := range []string{"MODEL_NAME", "WORKER_MODEL_NAME"} {
		value, found, err := readEnvValue(env.BackendEnvPath(), key)
		if err != nil || !found {
			t.Fatalf("%s: got (%q, %v, %v)", key, value, found, err)
		}
		if value != fallbackSingleModel {
			t.Fatalf("%s = %q, want %q", key, value, fallbackSingleModel)
		}
	}

	// The rest of the file (an unrelated key) must survive untouched.
	value, found, err := readEnvValue(env.BackendEnvPath(), "APP_NAME")
	if err != nil || !found || value != "Wizard" {
		t.Fatalf("APP_NAME got (%q, %v, %v), want (\"Wizard\", true, nil)", value, found, err)
	}
}

func TestEnsureEnvFileLeavesExistingFileAlone(t *testing.T) {
	backendDir := filepath.Join(t.TempDir(), "backend")
	if err := os.MkdirAll(backendDir, 0o755); err != nil {
		t.Fatal(err)
	}
	writeExampleEnv(t, backendDir)
	env := newTestEnv(t, backendDir)
	existing := "MODEL_NAME=\"user-picked-this\"\n"
	if err := os.WriteFile(env.BackendEnvPath(), []byte(existing), 0o644); err != nil {
		t.Fatal(err)
	}

	if err := ensureEnvFile(env, true, fallbackSingleModel, fallbackSingleModel); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	data, err := os.ReadFile(env.BackendEnvPath())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "user-picked-this") {
		t.Fatalf("an existing backend/.env must never be rewritten, got: %s", data)
	}
}
