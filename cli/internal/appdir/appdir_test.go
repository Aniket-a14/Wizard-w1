package appdir

import (
	"errors"
	"path/filepath"
	"testing"
)

func fakeHome() (string, error) {
	return filepath.FromSlash("/home/tester"), nil
}

func brokenHome() (string, error) {
	return "", errors.New("no home")
}

func getenvFrom(values map[string]string) func(string) string {
	return func(key string) string { return values[key] }
}

func TestConfigDirOverrideWins(t *testing.T) {
	got, err := configDirFor("linux", getenvFrom(map[string]string{
		"WIZARD_CONFIG_DIR": "/custom/wizard",
		"XDG_CONFIG_HOME":   "/should/not/be/used",
	}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.FromSlash("/custom/wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirOverrideExpandsHome(t *testing.T) {
	got, err := configDirFor("linux", getenvFrom(map[string]string{
		"WIZARD_CONFIG_DIR": "~/wizard-override",
	}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(filepath.FromSlash("/home/tester"), "wizard-override")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirWindowsUsesAppData(t *testing.T) {
	got, err := configDirFor("windows", getenvFrom(map[string]string{
		"APPDATA": `C:\Users\tester\AppData\Roaming`,
	}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(`C:\Users\tester\AppData\Roaming`, "Wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirWindowsFallsBackToHome(t *testing.T) {
	got, err := configDirFor("windows", getenvFrom(map[string]string{}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(filepath.FromSlash("/home/tester"), "AppData", "Roaming", "Wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirDarwin(t *testing.T) {
	got, err := configDirFor("darwin", getenvFrom(map[string]string{}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(filepath.FromSlash("/home/tester"), "Library", "Application Support", "Wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirLinuxXDG(t *testing.T) {
	got, err := configDirFor("linux", getenvFrom(map[string]string{
		"XDG_CONFIG_HOME": "/xdg/config",
	}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join("/xdg/config", "wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirLinuxFallsBackToDotConfig(t *testing.T) {
	got, err := configDirFor("linux", getenvFrom(map[string]string{}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join(filepath.FromSlash("/home/tester"), ".config", "wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestConfigDirPropagatesHomeError(t *testing.T) {
	_, err := configDirFor("linux", getenvFrom(map[string]string{}), brokenHome)
	if err == nil {
		t.Fatal("expected an error when the home directory cannot be resolved")
	}
}

func TestConfigDirBlankOverrideIsIgnored(t *testing.T) {
	// A blank environment variable is still "present" the way an empty
	// ${VAR:-} substitution is in docker-compose.yml -- config.py treats that
	// as unset, and this must too, or an empty WIZARD_CONFIG_DIR silently
	// resolves to the process's current directory instead of falling through
	// to the platform default.
	got, err := configDirFor("linux", getenvFrom(map[string]string{
		"WIZARD_CONFIG_DIR": "   ",
		"XDG_CONFIG_HOME":   "/xdg/config",
	}), fakeHome)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := filepath.Join("/xdg/config", "wizard")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}
