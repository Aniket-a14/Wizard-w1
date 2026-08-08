package daemon

import (
	"fmt"
	"os"
	"sync"
)

// DefaultMaxBytes and DefaultBackups bound how large the supervisor's own
// logs (backend.log, frontend.log, daemon.log) can grow across a
// long-running daemon, per the milestone's "logs ... don't grow unbounded"
// requirement.
const (
	DefaultMaxBytes = 10 * 1024 * 1024 // 10 MB
	DefaultBackups  = 5
)

// RotatingWriter is an io.Writer over a path that renames the current file
// to a numbered backup once it exceeds MaxBytes, keeping at most Backups old
// files (path.1 is the newest backup, path.N the oldest; anything beyond N
// is deleted). Size is checked before each write rather than continuously,
// which is enough for line-buffered subprocess output and needs no
// background goroutine.
type RotatingWriter struct {
	Path     string
	MaxBytes int64
	Backups  int

	mu   sync.Mutex
	file *os.File
	size int64
}

func NewRotatingWriter(path string, maxBytes int64, backups int) (*RotatingWriter, error) {
	w := &RotatingWriter{Path: path, MaxBytes: maxBytes, Backups: backups}
	if err := w.open(); err != nil {
		return nil, err
	}
	return w, nil
}

func (w *RotatingWriter) open() error {
	f, err := os.OpenFile(w.Path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	info, err := f.Stat()
	if err != nil {
		_ = f.Close() // already returning the stat error; a close error here adds nothing
		return err
	}
	w.file = f
	w.size = info.Size()
	return nil
}

func (w *RotatingWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.size > 0 && w.size+int64(len(p)) > w.MaxBytes {
		if err := w.rotate(); err != nil {
			return 0, err
		}
	}
	n, err := w.file.Write(p)
	w.size += int64(n)
	return n, err
}

func (w *RotatingWriter) rotate() error {
	if err := w.file.Close(); err != nil {
		return err
	}

	// Errors are collected rather than returned immediately: w.file was just
	// closed above, so this call must still reach w.open() to leave the
	// writer usable, even when a rename/remove step failed -- returning
	// early here would brick every later Write with "file already closed"
	// over one transient rotation failure, trading a bounded-growth problem
	// for a total-log-loss one.
	var rotateErr error
	recordErr := func(err error) {
		if err != nil && !os.IsNotExist(err) && rotateErr == nil {
			rotateErr = err
		}
	}

	oldest := fmt.Sprintf("%s.%d", w.Path, w.Backups)
	recordErr(os.Remove(oldest))
	for i := w.Backups - 1; i >= 1; i-- {
		src := fmt.Sprintf("%s.%d", w.Path, i)
		dst := fmt.Sprintf("%s.%d", w.Path, i+1)
		recordErr(os.Rename(src, dst))
	}
	if w.Backups >= 1 {
		recordErr(os.Rename(w.Path, fmt.Sprintf("%s.1", w.Path)))
	}

	if err := w.open(); err != nil {
		return err
	}
	return rotateErr
}

func (w *RotatingWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.file.Close()
}
