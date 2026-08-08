package commands

import "testing"

func TestEstimateWeightBytesParsesTag(t *testing.T) {
	cases := []struct {
		model  string
		wantB  float64
		wantOK bool
	}{
		{"qwen3:8b", 8, true},
		{"qwen2.5-coder:7b", 7, true},
		{"qwen2.5-coder:1.5b", 1.5, true},
		{"qwen2.5:3b", 3, true},
		{"qwen2.5:3b-instruct-q4_0", 3, true},
		{"llama3", 0, false},        // no tag at all
		{"llama3:latest", 0, false}, // tag carries no parameter size
		{"weird:model", 0, false},
	}
	for _, c := range cases {
		got, ok := estimateWeightBytes(c.model)
		if ok != c.wantOK {
			t.Errorf("estimateWeightBytes(%q) ok = %v, want %v", c.model, ok, c.wantOK)
			continue
		}
		if !ok {
			continue
		}
		want := uint64(c.wantB * weightsPerBillionParams)
		if got != want {
			t.Errorf("estimateWeightBytes(%q) = %d bytes, want %d", c.model, got, want)
		}
	}
}

func TestRecommendModelsUnknownRAMLeavesRequestUnchanged(t *testing.T) {
	mgr, wrk, overridden, reason := recommendModels(0, false, "qwen3:8b", "qwen2.5-coder:7b")
	if overridden {
		t.Fatal("expected no override when RAM is unknown")
	}
	if mgr != "qwen3:8b" || wrk != "qwen2.5-coder:7b" {
		t.Fatalf("got (%q, %q), want the requested pair unchanged", mgr, wrk)
	}
	if reason == "" {
		t.Fatal("expected a reason explaining why nothing was evaluated")
	}
}

func TestRecommendModelsFitsOnAmpleRAM(t *testing.T) {
	// 64 GB * 60% = ~38.4 GB budget -- the default pair (~8.25 GB) fits easily.
	ram := uint64(64) * bytesPerGB
	mgr, wrk, overridden, _ := recommendModels(ram, true, "qwen3:8b", "qwen2.5-coder:7b")
	if overridden {
		t.Fatal("expected no override on a machine with ample RAM")
	}
	if mgr != "qwen3:8b" || wrk != "qwen2.5-coder:7b" {
		t.Fatalf("got (%q, %q), want the requested pair unchanged", mgr, wrk)
	}
}

func TestRecommendModelsOverridesOnTightRAM(t *testing.T) {
	// 8 GB * 60% = ~4.8 GB budget -- the default pair (~8.25 GB) does not fit.
	ram := uint64(8) * bytesPerGB
	mgr, wrk, overridden, reason := recommendModels(ram, true, "qwen3:8b", "qwen2.5-coder:7b")
	if !overridden {
		t.Fatal("expected an override on a machine with tight RAM")
	}
	if mgr != fallbackSingleModel || wrk != fallbackSingleModel {
		t.Fatalf("got (%q, %q), want both roles set to %q", mgr, wrk, fallbackSingleModel)
	}
	if reason == "" {
		t.Fatal("expected a reason explaining the override")
	}
}

func TestRecommendModelsUnparseableTagSkipsOverride(t *testing.T) {
	ram := uint64(8) * bytesPerGB
	mgr, wrk, overridden, reason := recommendModels(ram, true, "my-custom-model", "qwen2.5-coder:7b")
	if overridden {
		t.Fatal("expected no override when a model's size can't be estimated")
	}
	if mgr != "my-custom-model" || wrk != "qwen2.5-coder:7b" {
		t.Fatalf("got (%q, %q), want the requested pair unchanged", mgr, wrk)
	}
	if reason == "" {
		t.Fatal("expected a reason explaining why nothing was evaluated")
	}
}
