package commands

import (
	"fmt"
	"os"
	"path/filepath"

	"wizard/internal/daemon"
)

// RunSupervise is the body of the hidden `wizard __supervise` subcommand.
// `wizard start` re-execs itself into this, detached, so the supervision
// loop in internal/daemon survives the `start` command returning. It is
// never invoked directly by a user -- see cmd/wizard/main.go's dispatch.
func RunSupervise(env *Env) int {
	backendAddr := "127.0.0.1:" + backendPort()
	frontendAddr := "127.0.0.1:" + frontendPort()

	cfg := daemon.Config{
		RunDir:  env.RunDir,
		LogsDir: env.LogsDir,
		Backend: daemon.ProcessSpec{
			Label: "backend",
			Name:  env.VenvUvicorn(),
			Args:  []string{"src.api.api:app", "--host", "127.0.0.1", "--port", backendPort()},
			Dir:   env.BackendDir,
			Env:   os.Environ(),
		},
		Frontend: daemon.ProcessSpec{
			Label: "frontend",
			Name:  "node",
			Args:  []string{filepath.Join(".next", "standalone", "server.js")},
			Dir:   env.FrontendDir,
			Env: append(os.Environ(),
				"PORT="+frontendPort(),
				"HOSTNAME=127.0.0.1", // loopback only -- see the "no remote access" note in cli/README.md
				"NODE_ENV=production",
			),
		},
		BackendHealthURL:  "http://" + backendAddr,
		FrontendAddr:      frontendAddr,
		StartupGrace:      daemon.DefaultStartupGrace,
		PollInterval:      daemon.DefaultPollInterval,
		HealthEvery:       daemon.DefaultHealthEvery,
		FailuresToRestart: daemon.DefaultFailuresToRestart,
		TerminateGrace:    daemon.DefaultTerminateGrace,
		MaxRestarts:       daemon.DefaultMaxRestarts,
		BackoffBase:       daemon.DefaultBackoffBase,
		BackoffCap:        daemon.DefaultBackoffCap,
	}

	if err := daemon.Run(cfg); err != nil {
		fmt.Fprintf(env.Err, "supervisor stopped: %v\n", err)
		return 1
	}
	return 0
}
