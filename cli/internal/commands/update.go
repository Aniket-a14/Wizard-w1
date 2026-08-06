package commands

import (
	"fmt"
	"os/exec"

	"wizard/internal/compat"
	"wizard/internal/daemon"
)

// RunUpdate implements `wizard update`, scoped to the checkout only for this
// milestone: git pull, reinstall dependencies, re-check the compat marker.
// Updating the wizard binary itself needs a release pipeline that does not
// exist yet -- see cli/README.md.
func RunUpdate(env *Env, args []string) int {
	if err := exec.Command("git", "-C", env.RepoRoot, "rev-parse", "--is-inside-work-tree").Run(); err != nil {
		fmt.Fprintln(env.Err, "This checkout is not a git repository, so `wizard update` has nothing to pull. Update it however you obtained it.")
		return 1
	}

	wasRunning := false
	if _, alive := daemon.LiveAt(env.DaemonPIDPath()); alive {
		wasRunning = true
		fmt.Fprintln(env.Out, "Stopping the running daemon before updating...")
		if code := RunStop(env, nil); code != 0 {
			return code
		}
	}

	fmt.Fprintln(env.Out, "Pulling the latest checkout (fast-forward only)...")
	pull := exec.Command("git", "-C", env.RepoRoot, "pull", "--ff-only")
	pull.Stdout = env.Out
	pull.Stderr = env.Err
	if err := pull.Run(); err != nil {
		fmt.Fprintf(env.Err, "git pull --ff-only failed: %v\nResolve it manually (a merge or a diverged branch needs a decision this command won't make for you), then re-run `wizard update`.\n", err)
		return 1
	}

	python := CheckPython(minPythonMajor, minPythonMinor)
	if !python.OK {
		fmt.Fprintln(env.Err, "Python is no longer found/new enough after the pull; run `wizard init` to see what changed.")
		return 1
	}
	if err := installDependencies(env, python); err != nil {
		fmt.Fprintf(env.Err, "%v\n", err)
		return 1
	}

	if newVersion, err := readAPIVersionFromSource(env); err == nil {
		if mismatched, cmpErr := compat.Mismatch(newVersion); cmpErr == nil && mismatched {
			fmt.Fprintf(env.Err,
				"The updated backend now reports API v%s; this wizard binary is built for v%s.\n"+
					"Rebuild/reinstall the wizard CLI before starting it again.\n",
				newVersion, compat.CompatAPIVersion)
			return 1
		}
	}

	if wasRunning {
		fmt.Fprintln(env.Out, "\nRestarting...")
		return RunStart(env, nil)
	}

	fmt.Fprintln(env.Out, "\nUpdated. Run `wizard start` when you're ready.")
	return 0
}
