#!/usr/bin/env python3
"""elf2hex.py - split a compiled compliance-test ELF into two $readmemh hex
files, one for instr_mem (code) and one for data_mem (data/signature).

Usage: elf2hex.py <elf> <instr_hex_out> <data_hex_out>
"""
import subprocess
import sys
import struct
import tempfile
from pathlib import Path

def objcopy_binary(elf, sections, out_bin):
    output = Path(out_bin)
    try:
        output.unlink()
    except FileNotFoundError:
        pass
    cmd = ["riscv64-unknown-elf-objcopy", "-O", "binary"]
    for s in sections:
        cmd += [f"--only-section={s}"]
    cmd += [elf, out_bin]
    subprocess.run(cmd, check=True)
    if not output.is_file():
        raise SystemExit(f"ERROR: objcopy produced no output: {out_bin}")

def bin_to_hex_words(bin_path, hex_path, max_words):
    with open(bin_path, "rb") as f:
        data = f.read()
    if len(data) % 4:
        data += b"\x00" * (4 - len(data) % 4)
    words = [struct.unpack("<I", data[i:i+4])[0] for i in range(0, len(data), 4)]
    if len(words) > max_words:
        raise SystemExit(f"ERROR: {bin_path} needs {len(words)} words, "
                          f"exceeds memory size {max_words}")
    with open(hex_path, "w") as f:
        for w in words:
            f.write(f"{w:08x}\n")
    return len(words)

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    elf, instr_hex, data_hex = sys.argv[1:4]

    with tempfile.TemporaryDirectory(prefix="rv32i-elf2hex-") as work:
        text_bin = Path(work) / "text.bin"
        data_bin = Path(work) / "data.bin"
        objcopy_binary(elf, [".text.init", ".text", ".rodata"], text_bin)
        objcopy_binary(elf, [".data"], data_bin)

        n_instr = bin_to_hex_words(text_bin, instr_hex, 524288)
        n_data = bin_to_hex_words(data_bin, data_hex, 16384)

    print(f"instr_mem: {n_instr} words -> {instr_hex}")
    print(f"data_mem:  {n_data} words -> {data_hex}")

if __name__ == "__main__":
    main()
