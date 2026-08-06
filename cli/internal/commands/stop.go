package commands

import (
	"fmt"
	"os"
	"time"

	"wizard/internal/daemon"
)

// RunStop implements `wizard stop`. Idempotent: stopping an already-stopped
// daemon is success, not an error, the same way `docker compose down` on an
// already-down stack is.
func RunStop(env *Env, args []string) int {
	daemonPID, alive := daemon.LiveAt(env.DaemonPIDPath())
	if !alive {
		fmt.Fprintln(env.Out, "wizard is not running.")
		return 0
	}

	fmt.Fprintln(env.Out, "Stopping...")
	if err := os.WriteFile(env.StopSentinelPath(), []byte("1"), 0o644); err != nil {
		fmt.Fprintf(env.Err, "Could not request a stop: %v\n", err)
		return 1
	}

	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if _, alive := daemon.LiveAt(env.DaemonPIDPath()); !alive {
			fmt.Fprintln(env.Out, "Stopped.")
			return 0
		}
		time.Sleep(300 * time.Millisecond)
	}

	fmt.Fprintln(env.Out, "The supervisor did not exit on its own in time; forcing a stop.")
	forceKill(env, daemonPID)
	fmt.Fprintln(env.Out, "Stopped.")
	return 0
}

func forceKill(env *Env, daemonPID int) {
	if backendPID, alive := daemon.LiveAt(env.BackendPIDPath()); alive {
		_ = daemon.KillPID(backendPID)
	}
	if frontendPID, alive := daemon.LiveAt(env.FrontendPIDPath()); alive {
		_ = daemon.KillPID(frontendPID)
	}
	if daemon.IsAlive(daemonPID) {
		_ = daemon.KillPID(daemonPID)
	}
	_ = daemon.RemovePID(env.BackendPIDPath())
	_ = daemon.RemovePID(env.FrontendPIDPath())
	_ = daemon.RemovePID(env.DaemonPIDPath())
	_ = os.Remove(env.StopSentinelPath())
}
