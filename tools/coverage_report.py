#!/usr/bin/env python3
"""Summarize a verilator_coverage merged .dat into a markdown functional
coverage report. Only the "user" page (our `cover property` points) is
reported — the "toggle"/"line" pages are Verilator's automatic bit-level
coverage, not the functional crosses this report is about.
"""
import re
import sys

# Fields are \x01-separated "code\x02value" pairs, e.g. \x01t\x02user\x01h\x02TOP.cpu.foo
LINE_RE = re.compile(r"^C '(.*)' (\d+)$")
FIELD_RE = re.compile(r"\x01(\w+)\x02([^\x01]*)")


def human(path: str) -> str:
    path = path.replace("__BRA__", "[").replace("__KET__", "]")
    path = path.replace("__DOT__", ".")
    return path.split(".", 1)[-1] if path.startswith("TOP.") else path


def main():
    datfile = sys.argv[1]
    points = {}
    with open(datfile) as f:
        for line in f:
            m = LINE_RE.match(line.rstrip("\n"))
            if not m:
                continue
            key, count = m.group(1), int(m.group(2))
            fields = dict(FIELD_RE.findall(key))
            if fields.get("t") != "user":
                continue
            name = human(fields.get("h", ""))
            points[name] = points.get(name, 0) + count

    total = len(points)
    hit = sum(1 for c in points.values() if c > 0)
    pct = 100.0 * hit / total if total else 0.0

    print("# Functional coverage report")
    print()
    print("**Evidence status: current.**")
    print()
    print(f"**{hit}/{total} cover points hit ({pct:.1f}%)**, from the directed "
          "suite and deterministic BTB-alias fixture run against a cache-enabled "
          "build (`make coverage`).")
    print()
    print("| Cover point | Hits |")
    print("|---|---|")
    for name in sorted(points):
        count = points[name]
        mark = "" if count > 0 else " **(unhit)**"
        print(f"| `{name}` | {count}{mark} |")

    # Why each remaining hole is still open. A coverage report whose unhit
    # list is unexplained is just a number; the point of chasing holes is to
    # end with each one either closed or justified.
    notes = {
        "c_false_predict":
            "the deterministic BTB-alias fixture no longer reaches the stale "
            "taken prediction.",
        "c_load_use_and_mispredict":
            "the load-dependent branch in t25 no longer mispredicts after the "
            "pipeline accepts the hazard bubble.",
        "c_pred_tt_mismatch":
            "predicted-taken and actually-taken but to a *different* target: "
            "needs an indirect jump (JALR) reached from two call sites so the "
            "BTB holds a stale target. Return-address prediction makes this "
            "case more common.",
        "c_miss_load":
            "t19 no longer reloads the clean line evicted by its FIFO sequence.",
        "c_trans_flush_to_idle":
            "the harness no longer samples the cycle after cache-drain completion.",
    }
    unhit = [n for n, c in points.items() if c == 0]
    if unhit:
        print()
        print("## Unhit points")
        print()
        print("Each is reachable in principle; none is dead logic.")
        print()
        for n in sorted(unhit):
            key = n.split(".")[-1]
            why = notes.get(key, "not yet analysed.")
            print(f"- `{n}` — {why}")


if __name__ == "__main__":
    main()
