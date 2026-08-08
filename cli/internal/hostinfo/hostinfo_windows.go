package hostinfo

import (
	"fmt"
	"unsafe"

	"golang.org/x/sys/windows"
)

// memoryStatusEx mirrors the Win32 MEMORYSTATUSEX struct field-for-field --
// GlobalMemoryStatusEx has no x/sys/windows wrapper, so the struct and the
// DLL call are declared by hand, the same technique the daemon package
// already uses for CTRL_BREAK_EVENT delivery on this OS.
type memoryStatusEx struct {
	dwLength                uint32
	dwMemoryLoad            uint32
	ullTotalPhys            uint64
	ullAvailPhys            uint64
	ullTotalPageFile        uint64
	ullAvailPageFile        uint64
	ullTotalVirtual         uint64
	ullAvailVirtual         uint64
	ullAvailExtendedVirtual uint64
}

var (
	kernel32                 = windows.NewLazySystemDLL("kernel32.dll")
	procGlobalMemoryStatusEx = kernel32.NewProc("GlobalMemoryStatusEx")
)

// TotalRAMBytes calls GlobalMemoryStatusEx, the same Win32 API
// backend/src/utils/hostinfo.py's ctypes call goes through.
func TotalRAMBytes() (uint64, error) {
	var status memoryStatusEx
	status.dwLength = uint32(unsafe.Sizeof(status))
	r, _, err := procGlobalMemoryStatusEx.Call(uintptr(unsafe.Pointer(&status)))
	if r == 0 {
		return 0, fmt.Errorf("GlobalMemoryStatusEx: %w", err)
	}
	return status.ullTotalPhys, nil
}
