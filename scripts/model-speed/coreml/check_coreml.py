"""Runs a converted Core ML model on the requests of the speed test, on a Mac.

Usage: python check_coreml.py MODEL.mlpackage TOKENS REFERENCE OUT --units cpu|gpu|all
  TOKENS     the tokens of the requests (speed_cli tokens)
  REFERENCE  llama.cpp's answers on the same model (speed_cli cpu on the Q8_0 file)
  OUT        OUT.summary, OUT.times and OUT.answers in the format of speed_cli, and OUT.check.json
  --units    the compute units of Core ML: cpu (CPU_ONLY), gpu (CPU_AND_GPU), all (ALL)

OUT.check.json holds the form of the model, Core ML's compute plan on this machine, the share of
requests with the same top candidate as the reference, the widest and the median difference of
the numbers, and the time to load the model.
"""

import argparse
import json
import pathlib
import statistics
import sys
import time

import coremltools as ct
import numpy as np
from coremltools.models.compute_plan import MLComputePlan

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from request_driver import Driver, read_tokens  # noqa: E402

UNITS = {"cpu": ct.ComputeUnit.CPU_ONLY, "gpu": ct.ComputeUnit.CPU_AND_GPU, "all": ct.ComputeUnit.ALL}


def compute_plan(model, units) -> dict:
    """Core ML's plan for the operations of the model on this machine: per device, the count of
    operations it prefers that device for, and their share of the estimated cost."""
    plan = MLComputePlan.load_from_path(path=model.get_compiled_model_path(), compute_units=units)
    counts, costs = {}, {}

    def walk(block):
        for operation in block.operations:
            usage = plan.get_compute_device_usage_for_mlprogram_operation(operation)
            if usage is not None:
                device = type(usage.preferred_compute_device).__name__
                counts[device] = counts.get(device, 0) + 1
                cost = plan.get_estimated_cost_for_mlprogram_operation(operation)
                costs[device] = costs.get(device, 0.0) + (cost.weight if cost is not None else 0.0)
            for inner in operation.blocks:
                walk(inner)

    for function in plan.model_structure.program.functions.values():
        walk(function.block)
    total = sum(costs.values())
    return {device: {"operations": counts[device], "cost_share": round(costs[device] / total, 4) if total else None}
            for device in sorted(counts)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("tokens")
    parser.add_argument("reference")
    parser.add_argument("out")
    parser.add_argument("--units", choices=sorted(UNITS), required=True)
    arguments = parser.parse_args()
    started = time.perf_counter()
    model = ct.models.MLModel(arguments.model, compute_units=UNITS[arguments.units])
    load_ms = (time.perf_counter() - started) * 1000
    times = []
    # The fixed form of convert.py has the input write_cells and lists the (Q, R) pairs of its
    # calls as the shapes of input_ids and score_rows, matched by their place in the lists.
    inputs = {entry.name: entry for entry in model.get_spec().description.input}
    shapes = None
    if "write_cells" in inputs:
        tokens = inputs["input_ids"].type.multiArrayType.enumeratedShapes.shapes
        scored = inputs["score_rows"].type.multiArrayType.enumeratedShapes.shapes
        shapes = sorted({(int(q.shape[1]), int(r.shape[1])) for q, r in zip(tokens, scored)})
    print(f"form {'fixed with shapes ' + str(shapes) if shapes else 'flexible'}")

    def call(state, values):
        began = time.perf_counter()
        outputs = model.predict(values, state=state)
        times.append((time.perf_counter() - began) * 1000)
        return tuple(np.asarray(outputs[name]).reshape(-1)
                     for name in ("target_logit", "log_norm", "space_log_mass", "first_logit"))

    driver = Driver(call, model.make_state, shapes=shapes)
    reference = []
    for line in pathlib.Path(arguments.reference).read_text().splitlines():
        reference.append([tuple(float(number) for number in field.split(" ")) for field in line.split("\t")])
    requests = read_tokens(pathlib.Path(arguments.tokens))
    out = pathlib.Path(arguments.out)
    time_lines, answer_lines, differences, same = [], [], [], 0
    first_request_ms = None
    for index, request in enumerate(requests):
        window_before, reused_before = driver.window_tokens, driver.window_tokens_reused
        calls_before = len(times)
        began = time.perf_counter()
        scores = driver.score(request)
        total = (time.perf_counter() - began) * 1000
        if first_request_ms is None:
            first_request_ms = total
        parts = [part for part, _, _ in driver.calls]
        made = times[calls_before:]
        window_ms = sum(ms for ms, part in zip(made, parts) if part == "window")
        candidate_ms = sum(ms for ms, part in zip(made, parts) if part == "candidates")
        time_lines.append(f"{driver.window_tokens - window_before} {driver.window_tokens_reused - reused_before} "
                          f"{window_ms:.4f} {candidate_ms:.4f} {total:.4f}")
        answer_lines.append("\t".join(f"{lp:.17g} {sa:.17g}" for lp, sa in scores))
        for (lp, sa), (rlp, rsa) in zip(scores, reference[index]):
            differences += [abs(lp - rlp), abs(sa - rsa)]
        top = max(range(len(scores)), key=lambda c: scores[c][0] + scores[c][1])
        top_reference = max(range(len(scores)), key=lambda c: reference[index][c][0] + reference[index][c][1])
        same += top == top_reference
    pathlib.Path(str(out) + ".times").write_text("\n".join(time_lines) + "\n")
    pathlib.Path(str(out) + ".answers").write_text("\n".join(answer_lines) + "\n")
    pathlib.Path(str(out) + ".summary").write_text("\n".join([
        f"model {arguments.model}", f"device coreml-{arguments.units}", "threads 0", f"load_ms {load_ms:.3f}",
        "memory_kind none", f"first_request_ms {first_request_ms:.3f}", f"requests {len(requests)}",
        f"tokens_read {driver.tokens_read}", f"window_tokens {driver.window_tokens}",
        f"window_tokens_reused {driver.window_tokens_reused}"]) + "\n")
    check = {
        "form": "fixed" if shapes else "flexible",
        "compute_plan": compute_plan(model, UNITS[arguments.units]),
        "requests": len(requests),
        "agreement": round(same / len(requests), 4),
        "widest_difference": round(max(differences), 4),
        "median_difference": round(statistics.median(differences), 5),
        "load_ms": round(load_ms, 1),
    }
    pathlib.Path(str(out) + ".check.json").write_text(json.dumps(check, indent=2) + "\n")
    print(json.dumps(check))


if __name__ == "__main__":
    main()
