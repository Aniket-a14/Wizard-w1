// Supervisor is the body of the hidden `__supervise` subcommand `wizard
// start` re-execs itself into. It owns the backend and frontend child
// processes for the lifetime of the daemon: starting them, rotating their
// logs, polling backend health, restarting either one with backoff if it
// dies or stops answering, and giving up cleanly (a `crashed` marker, not a
// process that silently vanishes) once restart attempts are exhausted.
package daemon

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"time"

	"wizard/internal/healthcheck"
)

const (
	DefaultStartupGrace      = 15 * time.Second
	DefaultPollInterval      = 2 * time.Second
	DefaultHealthEvery       = 5 * time.Second
	DefaultFailuresToRestart = 3
	DefaultTerminateGrace    = 8 * time.Second
	DefaultMaxRestarts       = 5
	DefaultBackoffBase       = 1 * time.Second
	DefaultBackoffCap        = 30 * time.Second
)

// ProcessSpec is everything needed to launch one child.
type ProcessSpec struct {
	Label string // "backend" or "frontend" -- used in log/status messages only
	Name  string
	Args  []string
	Dir   string
	Env   []string
}

// Config is the supervisor's full policy: what to run and how forgiving to
// be about it dying or going quiet.
type Config struct {
	RunDir  string
	LogsDir string

	Backend  ProcessSpec
	Frontend ProcessSpec

	// BackendHealthURL is polled at GET /health. FrontendAddr, if set, is
	// checked with a bare TCP dial -- the frontend has no equivalent health
	// route, so "the port accepts a connection" is the honest degraded
	// signal rather than inventing one.
	BackendHealthURL string
	FrontendAddr     string

	StartupGrace      time.Duration
	PollInterval      time.Duration
	HealthEvery       time.Duration
	FailuresToRestart int
	TerminateGrace    time.Duration
	MaxRestarts       int
	BackoffBase       time.Duration
	BackoffCap        time.Duration
}

// managed pairs one ProcessSpec with its running Child and restart/failure
// bookkeeping.
type managed struct {
	spec       ProcessSpec
	log        *RotatingWriter
	pidPath    string
	child      *Child
	restarts   int
	failStreak int
}

// start is transactional: m.child is only assigned once the process is both
// running and recorded. A child that started but whose pid file could not be
// written is terminated immediately rather than left running and untracked
// -- otherwise a WritePID failure leaks a process `wizard stop` can never
// find, since it has no pid file to read.
func (m *managed) start() error {
	child := NewChild(m.spec.Label, m.spec.Name, m.spec.Args, m.spec.Dir, m.spec.Env, m.log)
	if err := child.Start(); err != nil {
		return err
	}
	if err := WritePID(m.pidPath, child.Pid()); err != nil {
		_ = child.Terminate(DefaultTerminateGrace)
		_ = RemovePID(m.pidPath)
		return fmt.Errorf("recording pid for %s: %w", m.spec.Label, err)
	}
	m.child = child
	return nil
}

// Run blocks until told to stop (the sentinel file appears) or a child
// exhausts its restart budget. Both are normal, reportable outcomes, not
// panics -- callers distinguish them by whether Run returns a non-nil error.
func Run(cfg Config) error {
	if err := os.MkdirAll(cfg.RunDir, 0o755); err != nil {
		return err
	}
	if err := os.MkdirAll(cfg.LogsDir, 0o755); err != nil {
		return err
	}

	backendLog, err := NewRotatingWriter(filepath.Join(cfg.LogsDir, "backend.log"), DefaultMaxBytes, DefaultBackups)
	if err != nil {
		return fmt.Errorf("opening backend log: %w", err)
	}
	defer backendLog.Close()

	frontendLog, err := NewRotatingWriter(filepath.Join(cfg.LogsDir, "frontend.log"), DefaultMaxBytes, DefaultBackups)
	if err != nil {
		return fmt.Errorf("opening frontend log: %w", err)
	}
	defer frontendLog.Close()

	backend := &managed{spec: cfg.Backend, log: backendLog, pidPath: filepath.Join(cfg.RunDir, "backend.pid")}
	frontend := &managed{spec: cfg.Frontend, log: frontendLog, pidPath: filepath.Join(cfg.RunDir, "frontend.pid")}
	crashedPath := filepath.Join(cfg.RunDir, "crashed")
	stopPath := filepath.Join(cfg.RunDir, "stop-requested")
	_ = os.Remove(crashedPath) // a fresh run should not carry a stale crash report

	if err := backend.start(); err != nil {
		return fmt.Errorf("starting backend: %w", err)
	}
	if err := frontend.start(); err != nil {
		_ = backend.child.Terminate(cfg.TerminateGrace)
		return fmt.Errorf("starting frontend: %w", err)
	}

	giveUp := func(which string, cause error, survivor *managed) error {
		writeCrashed(crashedPath, which, cause)
		if survivor != nil && survivor.child != nil {
			_ = survivor.child.Terminate(cfg.TerminateGrace)
		}
		cleanupAll(cfg, backend, frontend, stopPath)
		return fmt.Errorf("%s stopped and exhausted restart attempts: %w", which, cause)
	}

	healthClient := healthcheck.NewClient(cfg.BackendHealthURL)
	startedAt := time.Now()
	var lastHealthCheck time.Time

	ticker := time.NewTicker(cfg.PollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-backend.child.Done():
			cause := backend.child.ExitErr()
			if cause == nil {
				cause = errors.New("exited")
			}
			if !restart(backend, cfg) {
				return giveUp("backend", cause, frontend)
			}

		case <-frontend.child.Done():
			cause := frontend.child.ExitErr()
			if cause == nil {
				cause = errors.New("exited")
			}
			if !restart(frontend, cfg) {
				return giveUp("frontend", cause, backend)
			}

		case <-ticker.C:
			if _, err := os.Stat(stopPath); err == nil {
				_ = backend.child.Terminate(cfg.TerminateGrace)
				_ = frontend.child.Terminate(cfg.TerminateGrace)
				cleanupAll(cfg, backend, frontend, stopPath)
				return nil
			}

			if time.Since(startedAt) < cfg.StartupGrace {
				continue
			}
			if time.Since(lastHealthCheck) < cfg.HealthEvery {
				continue
			}
			lastHealthCheck = time.Now()

			if err := checkBackendHealth(healthClient); err != nil {
				backend.failStreak++
				if backend.failStreak >= cfg.FailuresToRestart {
					backend.failStreak = 0
					_ = backend.child.Terminate(cfg.TerminateGrace)
					if !restart(backend, cfg) {
						return giveUp("backend", err, frontend)
					}
				}
			} else {
				backend.failStreak = 0
			}

			if cfg.FrontendAddr != "" {
				if !tcpReachable(cfg.FrontendAddr, 3*time.Second) {
					frontend.failStreak++
					if frontend.failStreak >= cfg.FailuresToRestart {
						frontend.failStreak = 0
						_ = frontend.child.Terminate(cfg.TerminateGrace)
						if !restart(frontend, cfg) {
							return giveUp("frontend", errors.New("port not reachable"), backend)
						}
					}
				} else {
					frontend.failStreak = 0
				}
			}
		}
	}
}

func checkBackendHealth(client *healthcheck.Client) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	h, err := client.Health(ctx)
	if err != nil {
		return err
	}
	if h.Status != "ok" {
		return fmt.Errorf("backend reported status %q", h.Status)
	}
	return nil
}

// restart applies exponential backoff, bounded by MaxRestarts, and reports
// whether the process is running again.
func restart(m *managed, cfg Config) bool {
	if m.restarts >= cfg.MaxRestarts {
		return false
	}
	delay := cfg.BackoffBase * time.Duration(int64(1)<<uint(m.restarts))
	if delay > cfg.BackoffCap {
		delay = cfg.BackoffCap
	}
	m.restarts++
	time.Sleep(delay)
	return m.start() == nil
}

func cleanupAll(cfg Config, backend, frontend *managed, stopPath string) {
	_ = RemovePID(backend.pidPath)
	_ = RemovePID(frontend.pidPath)
	_ = os.Remove(stopPath)
	_ = RemovePID(filepath.Join(cfg.RunDir, "daemon.pid"))
}

func writeCrashed(path, which string, cause error) {
	msg := fmt.Sprintf("%s stopped unexpectedly at %s", which, time.Now().Format(time.RFC3339))
	if cause != nil {
		msg += ": " + cause.Error()
	}
	_ = os.WriteFile(path, []byte(msg+"\n"), 0o644)
}

func tcpReachable(addr string, timeout time.Duration) bool {
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}
