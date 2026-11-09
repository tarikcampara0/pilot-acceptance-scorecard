"""Turn an agreed pilot plan and one evidence file into a Markdown decision brief."""
import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sys


def load_plan(path):
    plan = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(plan, dict):
        raise ValueError("The pilot plan must be an object")
    cohort = plan.get("expected_orders")
    if not isinstance(cohort, list) or not cohort or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item) for item in cohort
    ) or len(set(cohort)) != len(cohort):
        raise ValueError("expected_orders must contain unique order IDs")
    for key in ("pilot_name", "operations_owner", "integration_owner"):
        if not isinstance(plan.get(key), str) or not plan[key].strip():
            raise ValueError(f"Missing {key}")
    for key, low, high in (("min_completion_pct", 0, 100), ("max_p95_ms", 1, 86400000)):
        value = plan.get(key)
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
    return plan


@dataclass(frozen=True)
class Observation:
    completed: bool
    latency: int | None
    writes: int


def load_evidence(path, plan):
    evidence = {}
    cohort = set(plan["expected_orders"])
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = ["order_id", "result", "latency_ms", "fulfillment_writes"]
        if sorted(reader.fieldnames or []) != sorted(fields):
            raise ValueError("Evidence columns must be " + ", ".join(fields))
        for row in reader:
            line = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Line {line}: malformed CSV row")
            oid, result, latency, writes = (row[key].strip() for key in fields)
            if oid not in cohort or oid in evidence:
                raise ValueError(f"Line {line}: unexpected or repeated order {oid}")
            if result not in ("completed", "failed") or not re.fullmatch("[0-9]+", writes):
                raise ValueError(f"Line {line}: invalid result or write count")
            completed = result == "completed"
            if completed and (not re.fullmatch("[0-9]+", latency) or int(writes) < 1):
                raise ValueError(f"Line {line}: completed orders require latency and a fulfillment write")
            if not completed and latency:
                raise ValueError(f"Line {line}: leave latency blank for failed orders")
            evidence[oid] = Observation(completed, int(latency) if completed else None, int(writes))
    return evidence


def evaluate(plan, evidence):
    cohort = plan["expected_orders"]
    missing = [oid for oid in cohort if oid not in evidence]
    completed = [r for r in evidence.values() if r.completed]
    percent = 100 * len(completed) / len(cohort)
    latencies = sorted(r.latency for r in completed)
    p95 = latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None
    duplicates = [oid for oid, obs in evidence.items() if obs.writes > 1]
    failures = [oid for oid, obs in evidence.items() if not obs.completed]
    ops, eng = plan["operations_owner"], plan["integration_owner"]
    def gate(passed):
        return "PASS" if passed else "FAIL"
    gates = [
        ("Evidence coverage", f"{len(evidence)} / {len(cohort)} orders", "Every planned order", "OPEN" if missing else "PASS", ops),
        ("Completion", f"{len(completed)} / {len(cohort)} ({percent:.2f}%)", f"At least {plan['min_completion_pct']}%", "OPEN" if missing else gate(percent >= plan["min_completion_pct"]), ops),
        ("p95 completion latency", f"{p95} ms" if p95 is not None else "No completions", f"At most {plan['max_p95_ms']} ms", "OPEN" if missing or p95 is None else gate(p95 <= plan["max_p95_ms"]), eng),
        ("Orders with extra writes", str(len(duplicates)), "Zero", "FAIL" if duplicates else ("OPEN" if missing else "PASS"), eng),
    ]
    statuses = [g[3] for g in gates]
    decision = "NO-GO" if "FAIL" in statuses else ("HOLD" if "OPEN" in statuses else "GO")
    return decision, gates, missing, duplicates, failures


def brief(plan, evidence):
    decision, gates, missing, duplicates, failures = evaluate(plan, evidence)
    lines = [f"# {plan['pilot_name']}", "", f"**Pilot decision: {decision}**", "",
             "| Criterion | Observed | Target | Result | Owner |",
             "| --- | --- | --- | --- | --- |"]
    for row in gates:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    lines += ["", "## Decision meeting", ""]
    if missing:
        lines.append(f"- {plan['operations_owner']}: collect evidence for " + ", ".join(missing) + ".")
    if failures:
        lines.append(f"- {plan['operations_owner']}: reconcile failed orders " + ", ".join(failures) + ".")
    if duplicates:
        lines.append(f"- {plan['integration_owner']}: inspect extra fulfillment writes for " + ", ".join(duplicates) + ".")
    if gates[2][3] == "FAIL":
        slow = [oid for oid, obs in evidence.items() if obs.completed and obs.latency > plan["max_p95_ms"]]
        lines.append(f"- {plan['integration_owner']}: trace slow orders " + ", ".join(slow) + ".")
    if decision == "GO":
        lines.append("- Review the passing evidence with the sponsor and agree on rollout scope and monitoring.")
    elif decision == "NO-GO":
        lines.append("- Fix failed criteria and capture a new run against the same plan.")
    else:
        lines.append("- Leave rollout approval open until every criterion has sufficient evidence.")
    lines += ["", "Completion uses every planned order as its denominator. Latency uses the nearest-rank 95th percentile of completed orders. The score applies to this cohort only."]
    return decision, "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--out", type=Path, help="Save the decision brief as Markdown")
    parser.add_argument("--gate", action="store_true", help="Return exit code 1 for HOLD or NO-GO")
    args = parser.parse_args()
    try:
        plan = load_plan(args.plan)
        decision, report = brief(plan, load_evidence(args.evidence, plan))
        if args.out:
            if args.out.resolve() in (args.plan.resolve(), args.evidence.resolve()):
                raise ValueError("Choose a report path different from the input files")
            args.out.write_text(report, encoding="utf-8")
        else:
            print(report, end="")
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(2, f"Input error: {exc}\n")
    return int(args.gate and decision != "GO")


if __name__ == "__main__":
    sys.exit(main())
