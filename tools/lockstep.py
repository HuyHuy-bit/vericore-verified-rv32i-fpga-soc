#!/usr/bin/env python3
"""Run one ELF on Spike and RTL and compare complete retirement streams."""

import argparse
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


RESET_PC = 0x80000000
TERMINAL_INSN = 0x0000006F
SPIKE = os.path.expanduser(
    os.environ.get("SPIKE", "~/projects/riscv-isa-sim/build/spike"))

COMMIT = re.compile(
    r"^core\s+\d+:\s+\d+\s+0x([0-9a-f]+)\s+\(0x([0-9a-f]+)\)(.*)$",
    re.IGNORECASE,
)
REGWR = re.compile(r"\bx\s*(\d+)\s+0x([0-9a-f]+)", re.IGNORECASE)
RTL_RECORD = re.compile(
    r"^([0-9a-f]{8}) ([0-9a-f]{8}) (0|[1-9]|[12][0-9]|3[01]) ([0-9a-f]{8})$"
)


class LockstepError(Exception):
    """A comparison cannot establish complete lockstep equality."""


def fmt(entry):
    pc, insn, rd, wdata = entry
    wr = f"x{rd}=0x{wdata:08x}" if rd else "-"
    return f"pc=0x{pc:08x} insn=0x{insn:08x} {wr}"


def terminate_and_reap(proc):
    """Terminate a child, escalating if necessary, and always wait for it."""
    if proc is None:
        return False
    termination_requested = False
    if proc.poll() is None:
        proc.terminate()
        termination_requested = True
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    else:
        proc.wait()
    return termination_requested


def read_diagnostic(path):
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def print_diagnostics(label, stdout_path, stderr_path):
    stdout = read_diagnostic(stdout_path)
    stderr = read_diagnostic(stderr_path)
    if stdout:
        print(f"--- {label} stdout ---", file=sys.stderr)
        print(stdout, end="" if stdout.endswith("\n") else "\n", file=sys.stderr)
    if stderr:
        print(f"--- {label} stderr ---", file=sys.stderr)
        print(stderr, end="" if stderr.endswith("\n") else "\n", file=sys.stderr)


def parse_rtl_trace(trace_path):
    if not trace_path.exists():
        raise LockstepError(f"RTL trace is missing: {trace_path}")
    try:
        lines = trace_path.read_text().splitlines()
    except OSError as exc:
        raise LockstepError(f"cannot read RTL trace: {exc}") from exc
    if not lines:
        raise LockstepError("RTL trace is empty")

    trace = []
    for lineno, line in enumerate(lines, 1):
        match = RTL_RECORD.fullmatch(line)
        if match is None:
            raise LockstepError(f"malformed RTL trace record at line {lineno}: {line!r}")
        pc = int(match.group(1), 16)
        insn = int(match.group(2), 16)
        rd = int(match.group(3), 10)
        wdata = int(match.group(4), 16)
        trace.append((pc, insn, rd, wdata if rd else 0))

    if trace[-1][1] != TERMINAL_INSN:
        raise LockstepError("RTL trace does not end with terminal self-loop 0x0000006f")
    if any(record[1] == TERMINAL_INSN for record in trace[:-1]):
        raise LockstepError("RTL trace contains retirement after terminal self-loop")
    return trace


class SpikeTrace:
    """Incrementally parse Spike's commit log through its first sentinel."""

    def __init__(self, stderr_path):
        self.stderr_path = stderr_path
        self.offset = 0
        self.partial = ""
        self.started = False
        self.complete = False
        self.records = []

    def update(self):
        if self.complete:
            return
        try:
            with self.stderr_path.open(errors="replace") as stream:
                stream.seek(self.offset)
                chunk = stream.read()
                self.offset = stream.tell()
        except FileNotFoundError:
            return
        text = self.partial + chunk
        lines = text.splitlines(keepends=True)
        self.partial = ""
        if lines and not lines[-1].endswith(("\n", "\r")):
            self.partial = lines.pop()
        for line in lines:
            match = COMMIT.match(line.rstrip("\r\n"))
            if not match:
                continue
            pc = int(match.group(1), 16)
            insn = int(match.group(2), 16)
            if not self.started:
                if pc != RESET_PC:
                    continue
                self.started = True
            rd, wdata = 0, 0
            write = REGWR.search(match.group(3))
            if write:
                rd, wdata = int(write.group(1)), int(write.group(2), 16)
                if not 0 <= rd <= 31 or wdata > 0xFFFFFFFF:
                    raise LockstepError(f"malformed Spike commit record: {line.rstrip()!r}")
                if rd == 0:
                    wdata = 0
            self.records.append((pc, insn, rd, wdata))
            if insn == TERMINAL_INSN:
                self.complete = True
                return


def compare_traces(name, rtl, spike, context, quiet):
    overlap = min(len(rtl), len(spike))
    if len(rtl) != len(spike):
        print(f"FAIL {name}: trace length mismatch: rtl={len(rtl)} spike={len(spike)}")
        matching = 0
        while matching < overlap and rtl[matching] == spike[matching]:
            matching += 1
        print(f"  matching prefix length: {matching}")
        if matching < overlap:
            print(f"  first unequal RTL record:   {fmt(rtl[matching])}")
            print(f"  first unequal Spike record: {fmt(spike[matching])}")
        elif len(rtl) > overlap:
            print(f"  first RTL-only record: {fmt(rtl[overlap])}")
        else:
            print(f"  first Spike-only record: {fmt(spike[overlap])}")
        return 1

    for index in range(overlap):
        if rtl[index] == spike[index]:
            continue
        print(f"FAIL {name}: diverged at retirement {index}")
        first = max(0, index - context)
        if first != index:
            print(f"  --- last {index - first} matching ---")
            for previous in range(first, index):
                print(f"    {previous:5d}  {fmt(rtl[previous])}")
        print("  --- divergence ---")
        print(f"    {index:5d}  RTL   {fmt(rtl[index])}")
        print(f"    {index:5d}  SPIKE {fmt(spike[index])}")
        return 1

    if not rtl or rtl[-1][1] != TERMINAL_INSN or spike[-1][1] != TERMINAL_INSN:
        print(f"FAIL {name}: shared final retirement is not terminal self-loop")
        return 1
    if not quiet:
        print(f"PASS {name}: {len(rtl)} retirements match through terminal self-loop")
    return 0


def run_children(args, work):
    trace_path = work / "rtl.rvfi"
    sim_stdout = work / "sim.stdout"
    sim_stderr = work / "sim.stderr"
    spike_stdout = work / "spike.stdout"
    spike_stderr = work / "spike.stderr"
    sim = spike = None

    if not os.path.isfile(SPIKE) or not os.access(SPIKE, os.X_OK):
        raise LockstepError(f"Spike is not executable: {SPIKE!r} (set $SPIKE)")
    if not os.path.isfile(args.sim) or not os.access(args.sim, os.X_OK):
        raise LockstepError(f"simulator is not executable: {args.sim}")

    sim_command = [
        args.sim, f"+MEMFILE={args.instr_hex}", f"+DATAFILE={args.data_hex}",
        f"+CYCLES={args.cycles}", "+STOP=selfloop", "+VCD=",
        f"+RVFI_TRACE={trace_path}",
    ]
    spike_command = [SPIKE, "--isa=rv32i", "-l", "--log-commits", args.elf]
    try:
        with spike_stdout.open("w") as spike_out, spike_stderr.open("w") as spike_err:
            spike = subprocess.Popen(spike_command, stdout=spike_out, stderr=spike_err,
                                     text=True)
        with sim_stdout.open("w") as sim_out, sim_stderr.open("w") as sim_err:
            sim = subprocess.Popen(sim_command, stdout=sim_out, stderr=sim_err,
                                   text=True)
    except OSError as exc:
        terminate_and_reap(sim)
        terminate_and_reap(spike)
        raise LockstepError(f"cannot start lockstep child: {exc}") from exc

    parser = SpikeTrace(spike_stderr)
    deadline = time.monotonic() + args.timeout
    rtl = None
    failure = None
    spike_terminated_by_us = False
    try:
        while True:
            parser.update()
            spike_status = spike.poll()
            sim_status = sim.poll()

            if parser.complete and spike_status is None:
                try:
                    spike_status = spike.wait(timeout=0.02)
                except subprocess.TimeoutExpired:
                    spike_terminated_by_us = terminate_and_reap(spike)
                spike_status = spike.returncode

            intentional_spike_status = (
                spike_terminated_by_us
                and spike_status in (-signal.SIGTERM, -signal.SIGKILL)
            )
            if spike_status not in (None, 0) and not intentional_spike_status:
                position = "after" if parser.complete else "before"
                failure = LockstepError(
                    f"Spike exited with status {spike_status} {position} terminal self-loop")
                break
            if sim_status is not None and sim_status != 0:
                failure = LockstepError(f"simulator exited with status {sim_status}")
                break
            if sim_status == 0 and rtl is None:
                try:
                    rtl = parse_rtl_trace(trace_path)
                except LockstepError as exc:
                    failure = exc
                    break
            if rtl is not None and parser.complete:
                break

            if time.monotonic() >= deadline:
                if sim_status == 0 and not parser.complete:
                    failure = LockstepError(
                        "deadline expired waiting for Spike terminal self-loop")
                elif parser.complete and sim_status is None:
                    failure = LockstepError("deadline expired waiting for simulator")
                else:
                    failure = LockstepError("lockstep deadline expired")
                break
            time.sleep(0.01)
    except LockstepError as exc:
        failure = exc
    finally:
        terminate_and_reap(sim)
        terminate_and_reap(spike)

    if failure is not None:
        print_diagnostics("simulator", sim_stdout, sim_stderr)
        print_diagnostics("Spike", spike_stdout, spike_stderr)
        raise failure
    return rtl, parser.records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("elf")
    parser.add_argument("instr_hex")
    parser.add_argument("data_hex")
    parser.add_argument("--sim", default="obj_dir_lockstep/Vcpu")
    parser.add_argument("--cycles", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--context", type=int, default=8)
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()
    if args.cycles <= 0:
        parser.error("--cycles must be positive")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")

    name = os.path.basename(args.elf)
    work = Path(tempfile.mkdtemp(prefix="rv32i-lockstep-"))
    try:
        rtl, spike = run_children(args, work)
    except LockstepError as exc:
        print(f"FAIL {name}: {exc}", file=sys.stderr)
        shutil.rmtree(work)
        return 1
    result = compare_traces(name, rtl, spike, args.context, args.quiet)
    if result:
        print(f"diagnostics retained in {work}", file=sys.stderr)
    else:
        shutil.rmtree(work)
    return result


if __name__ == "__main__":
    sys.exit(main())
