package commands

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// defaultMemoryFraction mirrors resources.py's DEFAULT_MEMORY_FRACTION: the
// share of total RAM the backend budgets for resident models, leaving the
// rest for the OS, the sandbox and everything else running.
const defaultMemoryFraction = 0.60

// fallbackSingleModel is the pair's replacement when it won't fit together.
// Not an arbitrary "small" pick -- it is the exact model resources.py's own
// estimate_footprint calibration is measured against (1.93 GB on disk,
// 2.91 GB resident at 8192 ctx, per that file's docstring), so this
// package's own estimate for it is the closest to reality of any model it
// could choose blind.
const fallbackSingleModel = "qwen2.5:3b"

const bytesPerGB = 1024 * 1024 * 1024

// weightsPerBillionParams mirrors estimate_footprint's fallback branch (used
// there when no real size_bytes is known yet, which is always true here --
// wizard init runs before any model is pulled or any registry is reachable).
const weightsPerBillionParams = 0.55 * bytesPerGB

var paramSizePattern = regexp.MustCompile(`(?i)(\d+(?:\.\d+)?)b`)

// estimateWeightBytes reads a parameter count off an Ollama tag's own
// "...:<N>b" convention (qwen3:8b -> 8, qwen2.5-coder:1.5b -> 1.5) and scales
// it the same way estimate_footprint's fallback branch does. ok is false
// when the tag carries no parameter size (no colon, or nothing matching) --
// callers must treat that as "unknown," not as a 0-byte model.
func estimateWeightBytes(model string) (weightBytes uint64, ok bool) {
	idx := strings.LastIndex(model, ":")
	if idx < 0 || idx == len(model)-1 {
		return 0, false
	}
	tag := model[idx+1:]
	m := paramSizePattern.FindStringSubmatch(tag)
	if m == nil {
		return 0, false
	}
	paramsB, err := strconv.ParseFloat(m[1], 64)
	if err != nil {
		return 0, false
	}
	return uint64(paramsB * weightsPerBillionParams), true
}

// recommendModels decides whether the requested manager/worker pair should
// be replaced by fallbackSingleModel for both roles, given this host's RAM.
//
// ramKnown=false means detection failed -- the requested pair is always
// returned unchanged in that case (see hostinfo.TotalRAMBytes), matching the
// codebase's "report inconclusive, don't guess" rule elsewhere (the
// OS-sandbox selftest uses the same shape for the same reason). The same
// applies when either model's tag carries no parseable parameter size: there
// is nothing to compare against the budget, so nothing is overridden.
func recommendModels(ramBytes uint64, ramKnown bool, manager, worker string) (mgr, wrk string, overridden bool, reason string) {
	if !ramKnown {
		return manager, worker, false, "could not detect host memory; using the requested models as-is"
	}

	budget := uint64(float64(ramBytes) * defaultMemoryFraction)
	mgrBytes, mgrOK := estimateWeightBytes(manager)
	wrkBytes, wrkOK := estimateWeightBytes(worker)
	if !mgrOK || !wrkOK {
		return manager, worker, false, fmt.Sprintf(
			"could not estimate %s's or %s's size from its tag; using the requested models as-is", manager, worker,
		)
	}

	combined := mgrBytes + wrkBytes
	if combined <= budget {
		return manager, worker, false, fmt.Sprintf(
			"%s + %s need ~%.1f GB combined, which fits this machine's ~%.1f GB model budget (%.0f%% of RAM)",
			manager, worker, gb(combined), gb(budget), defaultMemoryFraction*100,
		)
	}
	return fallbackSingleModel, fallbackSingleModel, true, fmt.Sprintf(
		"%s + %s need ~%.1f GB combined, which exceeds this machine's ~%.1f GB model budget (%.0f%% of RAM) enough to "+
			"cause swapping between them; using %s for both roles instead. Pass --manager-model/--worker-model to force the defaults.",
		manager, worker, gb(combined), gb(budget), defaultMemoryFraction*100, fallbackSingleModel,
	)
}

func gb(bytes uint64) float64 {
	return float64(bytes) / bytesPerGB
}
