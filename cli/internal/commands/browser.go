package commands

import (
	"os/exec"
	"runtime"
)

// openBrowser best-effort opens url in the default browser. Failure is not
// fatal to `wizard start` -- the URL is always printed too.
func openBrowser(url string) error {
	switch runtime.GOOS {
	case "windows":
		// The empty string is the window title argument `start` expects
		// before the URL; without it, a URL containing certain characters
		// can be misparsed as the title itself.
		return exec.Command("cmd", "/c", "start", "", url).Start()
	case "darwin":
		return exec.Command("open", url).Start()
	default:
		return exec.Command("xdg-open", url).Start()
	}
}
