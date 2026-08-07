package commands

import "fmt"

// installDependencies runs the same steps `wizard init` and `wizard update`
// both need: a Python venv with the backend's requirements, and a built
// frontend. Shared so update cannot drift from what init actually does.
func installDependencies(env *Env, python ToolCheck) error {
	if err := ensureVenv(env, python); err != nil {
		return fmt.Errorf("setting up the Python environment: %w", err)
	}

	fmt.Fprintln(env.Out, "\nInstalling backend dependencies (this can take a while the first time)...")
	if err := runStreamed(env, env.RepoRoot, env.VenvPip(), []string{"install", "-r", "requirements.txt", "-r", "requirements-local.txt"}); err != nil {
		return fmt.Errorf("pip install failed: %w", err)
	}

	fmt.Fprintln(env.Out, "\nInstalling frontend dependencies...")
	if err := runStreamed(env, env.FrontendDir, "npm", []string{"ci"}); err != nil {
		return fmt.Errorf("npm ci failed: %w", err)
	}

	fmt.Fprintln(env.Out, "\nBuilding the frontend (production standalone bundle)...")
	if err := runStreamed(env, env.FrontendDir, "npm", []string{"run", "build"}); err != nil {
		return fmt.Errorf("npm run build failed: %w", err)
	}
	return nil
}
