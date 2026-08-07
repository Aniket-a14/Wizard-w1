// Package appdir resolves Wizard's user-level configuration directory.
//
// This is a Go port of backend/src/utils/appdirs.py's config_dir(), kept in
// lockstep by hand rather than shared code -- a Go process cannot import the
// Python module, so this is the one other place the same answer has to be
// computed. Both agree on: WIZARD_CONFIG_DIR overrides everything, and
// otherwise the platform's conventional location is used (APPDATA on
// Windows, Library/Application Support on macOS, XDG_CONFIG_HOME or
// ~/.config elsewhere), so the CLI's daemon state and the backend's
// credentials.json/connections.json/skills live under one directory neither
// side has to be told about.
package appdir

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// AppName matches backend/src/utils/appdirs.py's APP_NAME exactly. Windows
// and macOS use it verbatim; the XDG branch lowercases it, same as Python.
const AppName = "Wizard"

// ConfigDir returns Wizard's user-level configuration directory. It is not
// created here -- callers that need it to exist call EnsureConfigDir.
func ConfigDir() (string, error) {
	return configDirFor(runtime.GOOS, os.Getenv, os.UserHomeDir)
}

// configDirFor is the testable core: goos, environment lookup and home
// directory resolution are all injected so the per-platform branches can be
// exercised on any single machine without touching the real environment.
func configDirFor(goos string, getenv func(string) string, homeDir func() (string, error)) (string, error) {
	if override := strings.TrimSpace(getenv("WIZARD_CONFIG_DIR")); override != "" {
		return expandHome(override, homeDir)
	}

	switch goos {
	case "windows":
		if base := strings.TrimSpace(getenv("APPDATA")); base != "" {
			return filepath.Join(base, AppName), nil
		}
		home, err := homeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, "AppData", "Roaming", AppName), nil

	case "darwin":
		home, err := homeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, "Library", "Application Support", AppName), nil

	default:
		if xdg := strings.TrimSpace(getenv("XDG_CONFIG_HOME")); xdg != "" {
			return filepath.Join(xdg, strings.ToLower(AppName)), nil
		}
		home, err := homeDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(home, ".config", strings.ToLower(AppName)), nil
	}
}

// expandHome mirrors Python's Path(override).expanduser(): a leading "~" (or
// "~/...") in an explicit WIZARD_CONFIG_DIR override resolves against the
// home directory instead of being treated as a literal directory name. Any
// override is also run through filepath.FromSlash, matching pathlib's own
// normalisation -- a forward-slash path typed on Windows (or copied from a
// POSIX .env example) resolves to the same directory a native path would.
func expandHome(path string, homeDir func() (string, error)) (string, error) {
	path = filepath.FromSlash(path)
	sep := string(filepath.Separator)
	if path != "~" && !strings.HasPrefix(path, "~"+sep) {
		return path, nil
	}
	home, err := homeDir()
	if err != nil {
		return "", err
	}
	if path == "~" {
		return home, nil
	}
	return filepath.Join(home, path[2:]), nil
}

// EnsureConfigDir returns ConfigDir, creating it (and any missing parents)
// if it does not exist.
func EnsureConfigDir() (string, error) {
	dir, err := ConfigDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return dir, nil
}

// RunDir, LogsDir and VenvDir are the subdirectories Milestone 8 adds under
// the existing config directory -- pid files and the stop sentinel, rotated
// logs, and the venv `wizard init` manages. They sit beside
// credentials.json/connections.json/skills/ without touching any of them.
func RunDir() (string, error)  { return ensureSubdir("run") }
func LogsDir() (string, error) { return ensureSubdir("logs") }
func VenvDir() (string, error) { return ensureSubdir("venv") }

func ensureSubdir(name string) (string, error) {
	base, err := EnsureConfigDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(base, name)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	return dir, nil
}

// ErrNoHome is returned when neither an override nor the platform's own
// lookup can produce a home directory -- surfaced so callers can print a
// clear message instead of a bare os.UserHomeDir error.
var ErrNoHome = errors.New("could not determine the user's home directory")
