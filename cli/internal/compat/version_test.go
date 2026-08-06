package compat

import "testing"

func TestMajorParsesLeadingComponent(t *testing.T) {
	got, err := Major("3.1.0")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 3 {
		t.Fatalf("got %d, want 3", got)
	}
}

func TestMajorRejectsUnparsable(t *testing.T) {
	if _, err := Major("not-a-version"); err == nil {
		t.Fatal("expected an error for an unparsable version")
	}
}

func TestMismatchTrueOnDifferentMajor(t *testing.T) {
	original := CompatAPIVersion
	defer func() { CompatAPIVersion = original }()
	CompatAPIVersion = "3.1.0"

	mismatched, err := Mismatch("4.0.0")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !mismatched {
		t.Fatal("expected a mismatch between major versions 3 and 4")
	}
}

func TestMismatchFalseOnSameMajorDifferentMinor(t *testing.T) {
	original := CompatAPIVersion
	defer func() { CompatAPIVersion = original }()
	CompatAPIVersion = "3.1.0"

	mismatched, err := Mismatch("3.9.2")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if mismatched {
		t.Fatal("expected no mismatch for a routine minor/patch bump within the same major version")
	}
}
