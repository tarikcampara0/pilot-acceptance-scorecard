# Pilot Acceptance Scorecard

A sales engineering tool for the decision meeting at the end of a proof of value. The fictional buyer, Northline Supply, needs evidence that automating order intake preserves fulfillment accuracy and keeps latency within an agreed limit.

## Run the decision meeting

Use Python 3.10 or newer. No packages or accounts are required.

```sh
python scorecard.py pilot-plan.json evidence-initial.csv
python scorecard.py pilot-plan.json evidence-partial.csv
python scorecard.py pilot-plan.json evidence-retest.csv --out decision.md
python -m unittest -v
```

| Capture | Decision | What to show the buyer |
| --- | --- | --- |
| Initial run | **NO-GO** | Two of 20 orders failed, one order wrote twice, and p95 latency exceeded 900 ms. Use the order IDs to assign follow-up. |
| Partial capture | **HOLD** | Three planned orders are missing. The brief names the missing IDs and keeps approval open. |
| Retest | **GO** | All 20 completed, p95 was 882 ms, and there were zero extra writes. One 912 ms order is slower than the p95 target. |

The files are independent synthetic runs. They model what a buyer might export after a pilot. The lab and scorecard run independently.

## Set the agreement before the pilot

The plan lists the agreed order IDs, owners, minimum completion percentage, and maximum p95 latency. Any repeated fulfillment write fails the integrity criterion. Edit the plan with the buyer before gathering evidence. The example has 20 orders, so one order affects completion by five percentage points.

Supply one CSV row per observed order. Use `completed` with a nonnegative integer latency in milliseconds and at least one fulfillment write. Use `failed` with a blank latency and the observed write count. Count actual writes from the destination order system. Leave missing observations absent so the report can identify them. Duplicate rows and unknown order IDs are rejected.

## Explain the decision

- The completion denominator is the full planned cohort. Missing evidence keeps completion and latency open. An observed duplicate write blocks rollout even during a partial capture.
- p95 uses the nearest-rank method over completed orders. With no completions the latency gate remains open.
- A failing gate yields **NO-GO**. Open gates with no failures yield **HOLD**. Passing every gate yields **GO** for the evaluated cohort.
- Add `--gate` to return exit code 1 for HOLD or NO-GO. Invalid input returns 2. With no output path the tool prints the brief.

A passing synthetic pilot illustrates the decision process. For a real rollout, agree on a representative cohort, measurement window, and who must sign off.
