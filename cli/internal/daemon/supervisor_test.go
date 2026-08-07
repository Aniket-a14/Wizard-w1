package daemon

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestHelperProcess is not a real test -- it is spawned as a subprocess by
// the integration tests below to stand in for the backend or frontend
// server, the same pattern Go's own os/exec_test.go uses to get a
// controllable child process without shipping a second binary. Under a
// normal `go test` it is a no-op: the guard below only lets it act as a
// server when the parent process explicitly asked for one.
func TestHelperProcess(t *testing.T) {
	if os.Getenv("WIZARD_CLI_HELPER") != "1" {
		return
	}
	defer os.Exit(0)

	mode := os.Getenv("WIZARD_CLI_HELPER_MODE")
	port := os.Getenv("WIZARD_CLI_HELPER_PORT")

	switch mode {
	case "backend":
		mux := http.NewServeMux()
		mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok", "version": "3.1.0"})
		})
		_ = http.ListenAndServe("127.0.0.1:"+port, mux)

	case "backend-fail":
		// Listens, but /health never reports ok -- simulates a process that
		// is alive but wedged, which only an actual health poll (as opposed
		// to "did the process exit") catches.
		mux := http.NewServeMux()
		mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusServiceUnavailable)
		})
		_ = http.ListenAndServe("127.0.0.1:"+port, mux)

	case "frontend":
		ln, err := net.Listen("tcp", "127.0.0.1:"+port)
		if err != nil {
			os.Exit(1)
		}
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			_ = conn.Close()
		}

	case "crash-immediately":
		os.Exit(1)
	}
}

func skipUnlessSelftest(t *testing.T) {
	t.Helper()
	if os.Getenv("WIZARD_CLI_SELFTEST") != "1" {
		t.Skip("set WIZARD_CLI_SELFTEST=1 to run the supervisor integration test (spawns real child processes)")
	}
}

func helperSpec(dir, label, mode string, port int) ProcessSpec {
	env := append(os.Environ(), "WIZARD_CLI_HELPER=1", "WIZARD_CLI_HELPER_MODE="+mode)
	if port != 0 {
		env = append(env, fmt.Sprintf("WIZARD_CLI_HELPER_PORT=%d", port))
	}
	return ProcessSpec{
		Label: label,
		Name:  os.Args[0],
		Args:  []string{"-test.run=TestHelperProcess"},
		Dir:   dir,
		Env:   env,
	}
}

func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("finding a free port: %v", err)
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port
}

func fastConfig(dir string, backend, frontend ProcessSpec, backendPort, frontendPort int) Config {
	return Config{
		RunDir:            filepath.Join(dir, "run"),
		LogsDir:           filepath.Join(dir, "logs"),
		Backend:           backend,
		Frontend:          frontend,
		BackendHealthURL:  fmt.Sprintf("http://127.0.0.1:%d", backendPort),
		FrontendAddr:      fmt.Sprintf("127.0.0.1:%d", frontendPort),
		StartupGrace:      100 * time.Millisecond,
		PollInterval:      50 * time.Millisecond,
		HealthEvery:       100 * time.Millisecond,
		FailuresToRestart: 2,
		TerminateGrace:    2 * time.Second,
		MaxRestarts:       2,
		BackoffBase:       20 * time.Millisecond,
		BackoffCap:        100 * time.Millisecond,
	}
}

func TestSupervisorStopsCleanlyOnSentinel(t *testing.T) {
	skipUnlessSelftest(t)

	dir := t.TempDir()
	backendPort, frontendPort := freePort(t), freePort(t)
	cfg := fastConfig(dir,
		helperSpec(dir, "backend", "backend", backendPort),
		helperSpec(dir, "frontend", "frontend", frontendPort),
		backendPort, frontendPort,
	)

	done := make(chan error, 1)
	go func() { done <- Run(cfg) }()

	// A fresh child process's first spawn can be slow on a machine where the
	// OS (or AV) has to scan the just-built test binary before it will run,
	// so this polls generously rather than assuming any fixed startup time.
	deadline := time.Now().Add(10 * time.Second)
	var pid int
	var alive bool
	for time.Now().Before(deadline) {
		pid, alive = LiveAt(filepath.Join(cfg.RunDir, "backend.pid"))
		if alive {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !alive {
		logBytes, _ := os.ReadFile(filepath.Join(cfg.LogsDir, "backend.log"))
		select {
		case err := <-done:
			t.Fatalf("expected backend to be alive after start; pid=%d Run already returned: %v; log=%q", pid, err, logBytes)
		default:
			t.Fatalf("expected backend to be alive after start; pid=%d Run has not returned yet; log=%q", pid, logBytes)
		}
	}

	if err := os.WriteFile(filepath.Join(cfg.RunDir, "stop-requested"), []byte("1"), 0o644); err != nil {
		t.Fatalf("writing stop sentinel: %v", err)
	}

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run returned an error on clean stop: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("supervisor did not stop within 10s of the stop sentinel appearing")
	}

	if _, err := os.Stat(filepath.Join(cfg.RunDir, "backend.pid")); !os.IsNotExist(err) {
		t.Fatalf("expected backend.pid removed after clean stop, err=%v", err)
	}
}

func TestSupervisorGivesUpAfterExhaustingRestarts(t *testing.T) {
	skipUnlessSelftest(t)

	dir := t.TempDir()
	frontendPort := freePort(t)
	cfg := fastConfig(dir,
		helperSpec(dir, "backend", "crash-immediately", 0),
		helperSpec(dir, "frontend", "frontend", frontendPort),
		1, frontendPort, // backend health URL is unused: it dies before any poll
	)

	err := Run(cfg)
	if err == nil {
		t.Fatal("expected Run to return an error once the backend exhausts its restart budget")
	}
	if _, statErr := os.Stat(filepath.Join(cfg.RunDir, "crashed")); statErr != nil {
		t.Fatalf("expected a crashed marker: %v", statErr)
	}
}

func TestSupervisorRestartsOnUnhealthyBackend(t *testing.T) {
	skipUnlessSelftest(t)

	dir := t.TempDir()
	backendPort, frontendPort := freePort(t), freePort(t)
	cfg := fastConfig(dir,
		helperSpec(dir, "backend", "backend-fail", backendPort),
		helperSpec(dir, "frontend", "frontend", frontendPort),
		backendPort, frontendPort,
	)

	done := make(chan error, 1)
	go func() { done <- Run(cfg) }()

	select {
	case err := <-done:
		if err == nil {
			t.Fatal("expected Run to give up once the unhealthy-but-alive backend exhausts its restart budget")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("supervisor did not give up on an unhealthy backend within 10s")
	}

	if _, statErr := os.Stat(filepath.Join(cfg.RunDir, "crashed")); statErr != nil {
		t.Fatalf("expected a crashed marker: %v", statErr)
	}
}
