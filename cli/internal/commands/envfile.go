package commands

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// readEnvValue does a best-effort scan of a .env-style file for KEY=value,
// the last assignment winning (matching how a real .env is actually
// applied). It exists only for `wizard status`/`doctor` to report a setting
// like EXECUTION_BACKEND without a Python dependency -- it is not a general
// .env parser and does not need to handle everything python-dotenv does.
func readEnvValue(path, key string) (string, bool) {
	f, err := os.Open(path)
	if err != nil {
		return "", false
	}
	defer f.Close()

	value, found := "", false
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 || strings.TrimSpace(parts[0]) != key {
			continue
		}
		value = strings.Trim(strings.TrimSpace(parts[1]), `"'`)
		found = true
	}
	return value, found
}

var apiVersionPattern = regexp.MustCompile(`API_VERSION\s*=\s*"([^"]+)"`)

// readAPIVersionFromSource reads API_VERSION straight out of
// backend/src/api/routes/meta.py by pattern, without running Python. Used
// only by `wizard update`, right after a git pull and before anything is
// restarted, when there is no live backend to ask via /health yet.
func readAPIVersionFromSource(env *Env) (string, error) {
	path := filepath.Join(env.BackendDir, "src", "api", "routes", "meta.py")
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	m := apiVersionPattern.FindSubmatch(data)
	if m == nil {
		return "", fmt.Errorf("API_VERSION not found in %s", path)
	}
	return string(m[1]), nil
}
