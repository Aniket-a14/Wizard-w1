package commands

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"
)

// RunAttach implements `wizard attach`: prints current status, then tails
// backend.log and frontend.log together, source-prefixed, until Ctrl+C.
// Read-only -- it does not touch the daemon, only watches its logs.
func RunAttach(env *Env, args []string) int {
	RunStatus(env, nil)
	fmt.Fprintln(env.Out, "\n--- following backend.log and frontend.log (Ctrl+C to stop) ---")

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	lines := make(chan string, 256)
	go followFile(ctx, "backend", env.BackendLogPath(), lines)
	go followFile(ctx, "frontend", env.FrontendLogPath(), lines)

	for {
		select {
		case <-ctx.Done():
			fmt.Fprintln(env.Out, "\nDetached.")
			return 0
		case line := <-lines:
			fmt.Fprintln(env.Out, line)
		}
	}
}

// followFile polls path for growth and emits any newly-appended, complete
// lines, prefixed with label. Polling rather than a filesystem watcher: the
// three target platforms have three different notification APIs, and a log
// file appended to a few times a second needs nothing fancier than this.
func followFile(ctx context.Context, label, path string, out chan<- string) {
	var offset int64
	ticker := time.NewTicker(300 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		f, err := os.Open(path)
		if err != nil {
			continue // not created yet, or rotated away mid-read; try again next tick
		}
		info, err := f.Stat()
		if err != nil {
			f.Close()
			continue
		}
		if info.Size() < offset {
			offset = 0 // the file was rotated/truncated out from under us; start over
		}
		if info.Size() == offset {
			f.Close()
			continue
		}

		if _, err := f.Seek(offset, 0); err != nil {
			f.Close()
			continue
		}
		scanner := bufio.NewScanner(f)
		scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for scanner.Scan() {
			select {
			case out <- fmt.Sprintf("[%s] %s", label, scanner.Text()):
			case <-ctx.Done():
				f.Close()
				return
			}
		}
		offset = info.Size()
		f.Close()
	}
}
