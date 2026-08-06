package commands

import (
	"os"
	"path/filepath"
	"testing"
)

func TestActivePortsRoundTrip(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "run"), 0o755); err != nil {
		t.Fatal(err)
	}
	env := &Env{RunDir: filepath.Join(dir, "run")}

	if err := saveActivePorts(env, "9000", "4000"); err != nil {
		t.Fatalf("saveActivePorts: %v", err)
	}
	backend, frontend := loadActivePorts(env)
	if backend != "9000" || frontend != "4000" {
		t.Fatalf("got (%q, %q), want (\"9000\", \"4000\")", backend, frontend)
	}
}

func TestActivePortsFallBackToDefaults(t *testing.T) {
	dir := t.TempDir()
	env := &Env{RunDir: filepath.Join(dir, "run")} // nothing saved, dir does not even exist
	backend, frontend := loadActivePorts(env)
	if backend != DefaultBackendPort || frontend != DefaultFrontendPort {
		t.Fatalf("got (%q, %q), want defaults (%q, %q)", backend, frontend, DefaultBackendPort, DefaultFrontendPort)
	}
}
