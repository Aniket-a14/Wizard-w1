package commands

import "testing"

func TestParseVersionExtractsMajorMinor(t *testing.T) {
	version, parsed := parseVersion("Python 3.11.9")
	if version != "3.11" {
		t.Fatalf("got version %q, want %q", version, "3.11")
	}
	if parsed != [2]int{3, 11} {
		t.Fatalf("got %v, want {3 11}", parsed)
	}
}

func TestParseVersionNodeStyle(t *testing.T) {
	version, parsed := parseVersion("v20.11.1\n")
	if version != "20.11" {
		t.Fatalf("got version %q, want %q", version, "20.11")
	}
	if parsed != [2]int{20, 11} {
		t.Fatalf("got %v, want {20 11}", parsed)
	}
}

func TestParseVersionUnparsable(t *testing.T) {
	version, parsed := parseVersion("")
	if version != "unknown" {
		t.Fatalf("got version %q, want %q", version, "unknown")
	}
	if parsed != [2]int{0, 0} {
		t.Fatalf("got %v, want zero value", parsed)
	}
}

func TestFinishCheckOKOnExactMinimum(t *testing.T) {
	c := finishCheck(ToolCheck{Name: "Python"}, [2]int{3, 11}, "3.11", 3, 11)
	if !c.OK {
		t.Fatal("expected exactly-the-minimum version to be OK")
	}
}

func TestFinishCheckOKOnNewerMinor(t *testing.T) {
	c := finishCheck(ToolCheck{Name: "Python"}, [2]int{3, 12}, "3.12", 3, 11)
	if !c.OK {
		t.Fatal("expected a newer minor version to be OK")
	}
}

func TestFinishCheckNotOKOnOlderMinor(t *testing.T) {
	c := finishCheck(ToolCheck{Name: "Python"}, [2]int{3, 10}, "3.10", 3, 11)
	if c.OK {
		t.Fatal("expected an older minor version to fail the minimum")
	}
}

func TestFinishCheckOKOnNewerMajor(t *testing.T) {
	c := finishCheck(ToolCheck{Name: "Node.js"}, [2]int{22, 0}, "22.0", 20, 0)
	if !c.OK {
		t.Fatal("expected a newer major version to be OK")
	}
}

func TestCheckPythonPrefersAnOKCandidateOverAnEarlierUnparsableOne(t *testing.T) {
	// Regresses a real bug found on Windows: `python3` commonly resolves to
	// the Microsoft Store's App Execution Alias stub, a real executable on
	// PATH whose --version output is an install-redirect message, not a
	// version. Stopping at the first *found* name reported Python as broken
	// on a machine where `python` was a perfectly good 3.13.
	_, stubParsed := parseVersion("Python was not found; run without arguments to install from the Microsoft Store")
	unparsable := finishCheck(ToolCheck{Name: "Python", Found: true}, stubParsed, "unknown", 3, 11)
	if unparsable.OK {
		t.Fatal("an unparsable version must never be reported OK")
	}
	good := finishCheck(ToolCheck{Name: "Python", Found: true}, [2]int{3, 13}, "3.13", 3, 11)
	if !good.OK {
		t.Fatal("expected 3.13 to satisfy a 3.11 minimum")
	}
	// CheckPython's actual candidate loop (python3 stub found-but-broken,
	// then python found-and-good) is exercised for real in
	// TestCheckPythonOnThisMachine below, which only runs where relevant.
}

func TestCheckPythonOnThisMachine(t *testing.T) {
	c := CheckPython(minPythonMajor, minPythonMinor)
	if !c.Found {
		t.Skip("no python/python3 on PATH in this environment")
	}
	if c.Version == "unknown" {
		t.Fatalf("CheckPython returned an unparsable version (%+v) even though a usable interpreter should be on PATH; "+
			"this is exactly the App-Execution-Alias-stub bug if it recurs on Windows", c)
	}
}
