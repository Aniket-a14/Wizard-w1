package hostinfo

import "golang.org/x/sys/unix"

// TotalRAMBytes reads the hw.memsize sysctl, the same value macOS's own
// `sysctl hw.memsize` reports and the natural analog of the Linux/Windows
// syscalls this package's other two files use.
func TotalRAMBytes() (uint64, error) {
	return unix.SysctlUint64("hw.memsize")
}
