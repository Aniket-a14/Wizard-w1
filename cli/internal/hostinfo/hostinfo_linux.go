package hostinfo

import "golang.org/x/sys/unix"

// TotalRAMBytes calls sysinfo(2) via x/sys/unix.Sysinfo, the same syscall
// backend/src/utils/hostinfo.py falls back to when no cgroup memory limit is
// set. wizard init has no session/container concept of its own, so unlike
// hostinfo.py it does not additionally check a cgroup limit -- the whole-host
// figure is the right question for "will these two models fit on this
// machine," which is what this package answers.
func TotalRAMBytes() (uint64, error) {
	var info unix.Sysinfo_t
	if err := unix.Sysinfo(&info); err != nil {
		return 0, err
	}
	return info.Totalram * uint64(info.Unit), nil
}
