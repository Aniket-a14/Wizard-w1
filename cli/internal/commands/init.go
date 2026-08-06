package commands

import (
	"flag"
	"fmt"
	"io"
	"os"
)

const (
	minPythonMajor = 3
	minPythonMinor = 11
	minNodeMajor   = 20
)

// RunInit implements `wizard init`: environment check, .env setup, dependency
// install, optional model pulls. Detect-and-instruct only -- it never
// invokes a package manager on the user's behalf for Python/Node/Ollama
// themselves, only for this project's own dependencies once the
// prerequisites are confirmed present.
func RunInit(env *Env, args []string) int {
	fs := flag.NewFlagSet("init", flag.ContinueOnError)
	pullModels := fs.Bool("pull-models", false, "Also `ollama pull` a small default manager/worker pair if Ollama is present and no model is pinned.")
	managerModel := fs.String("manager-model", "qwen3:8b", "Model to pull for the manager role with --pull-models.")
	workerModel := fs.String("worker-model", "qwen2.5-coder:7b", "Model to pull for the worker role with --pull-models.")
	if err := fs.Parse(args); err != nil {
		return 2
	}

	fmt.Fprintln(env.Out, "Checking prerequisites...")
	python := CheckPython(minPythonMajor, minPythonMinor)
	node := CheckNode(minNodeMajor)
	ollama := CheckOllama()

	printCheck(env.Out, python)
	printCheck(env.Out, node)
	printCheck(env.Out, ollama)

	if !python.OK || !node.OK {
		fmt.Fprintln(env.Err, "\nOne or more required prerequisites are missing or too old. Install them and re-run `wizard init`.")
		return 1
	}

	if err := ensureEnvFile(env); err != nil {
		fmt.Fprintf(env.Err, "Could not set up backend/.env: %v\n", err)
		return 1
	}

	if err := installDependencies(env, python); err != nil {
		fmt.Fprintf(env.Err, "%v\n", err)
		return 1
	}

	if *pullModels {
		if !ollama.Found {
			fmt.Fprintln(env.Out, "\n--pull-models given but Ollama was not found on PATH; skipping.")
		} else {
			fmt.Fprintln(env.Out, "\nPulling default models via Ollama...")
			for _, model := range []string{*managerModel, *workerModel} {
				if err := runStreamed(env, env.RepoRoot, "ollama", []string{"pull", model}); err != nil {
					fmt.Fprintf(env.Err, "ollama pull %s failed: %v\n", model, err)
				}
			}
		}
	} else if ollama.Found {
		fmt.Fprintln(env.Out, "\nOllama detected. Run `wizard init --pull-models` to also fetch a default manager/worker model pair.")
	}

	fmt.Fprintln(env.Out, "\nDone. Run `wizard start` to launch the backend and frontend.")
	return 0
}

func printCheck(out io.Writer, c ToolCheck) {
	switch {
	case !c.Found:
		fmt.Fprintf(out, "  [MISSING] %-10s not found on PATH.", c.Name)
		if c.InstallHint != "" {
			fmt.Fprintf(out, " Install: %s", c.InstallHint)
		}
		fmt.Fprintln(out)
	case !c.OK:
		fmt.Fprintf(out, "  [TOO OLD] %-10s %s at %s (need >= %d.%d). Install: %s\n", c.Name, c.Version, c.Path, c.MinMajor, c.MinMinor, c.InstallHint)
	case c.Version != "":
		fmt.Fprintf(out, "  [OK]      %-10s %s at %s\n", c.Name, c.Version, c.Path)
	default:
		fmt.Fprintf(out, "  [OK]      %-10s at %s\n", c.Name, c.Path)
	}
}

// ensureEnvFile copies backend/.env.example to backend/.env if the latter
// does not exist yet. The app already runs with none of those values set
// (see backend/.env.example's own header), so this is a convenience starting
// point to edit, not a required step.
func ensureEnvFile(env *Env) error {
	if _, err := os.Stat(env.BackendEnvPath()); err == nil {
		fmt.Fprintln(env.Out, "\nbackend/.env already exists, leaving it as is.")
		return nil
	}
	src, err := os.Open(env.BackendEnvExamplePath())
	if err != nil {
		return err
	}
	defer src.Close()

	dst, err := os.OpenFile(env.BackendEnvPath(), os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	defer dst.Close()

	if _, err := io.Copy(dst, src); err != nil {
		return err
	}
	fmt.Fprintln(env.Out, "\nCreated backend/.env from backend/.env.example. Edit it to pin a provider/model if you want one.")
	return nil
}

// ensureVenv creates the wizard-managed Python venv if it does not already
// have a usable interpreter in it. Kept under the platform config directory
// (see internal/appdir) rather than inside the checkout, so it survives a
// `git clean` and does not collide with a developer's own venv there.
func ensureVenv(env *Env, python ToolCheck) error {
	if env.VenvExists() {
		fmt.Fprintln(env.Out, "\nUsing existing venv at", env.VenvDir)
		return nil
	}
	fmt.Fprintln(env.Out, "\nCreating a Python environment at", env.VenvDir)
	return runStreamed(env, env.RepoRoot, python.Path, []string{"-m", "venv", env.VenvDir})
}
