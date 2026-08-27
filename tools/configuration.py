#!/usr/bin/env python3
"""Validate simulator predictor parameters."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
from typing import Sequence


class ConfigurationError(ValueError):
    pass


def canonical_integer(name: str, value: str) -> int:
    if re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        raise ConfigurationError(f"{name} must be a canonical integer")
    return int(value)


@dataclass(frozen=True)
class PredictorConfiguration:
    btb_idx_bits: int
    btb_tag_bits: int
    gshare: int
    ras_depth: int

    @classmethod
    def parse(cls, idx: str, tag: str, gshare: str, ras: str) -> "PredictorConfiguration":
        config = cls(
            canonical_integer("BTB_IDX_BITS", idx),
            canonical_integer("BTB_TAG_BITS", tag),
            canonical_integer("GSHARE", gshare),
            canonical_integer("RAS_DEPTH", ras),
        )
        errors = config.errors()
        if errors:
            raise ConfigurationError(errors[0])
        return config

    def errors(self) -> list[str]:
        errors: list[str] = []
        if not 1 <= self.btb_idx_bits <= 12:
            errors.append("BTB_IDX_BITS must be between 1 and 12")
        if not 1 <= self.btb_tag_bits <= 24:
            errors.append("BTB_TAG_BITS must be between 1 and 24")
        if self.btb_idx_bits + self.btb_tag_bits > 30:
            errors.append("BTB index and tag bits exceed the PC width")
        if self.gshare not in (0, 1):
            errors.append("GSHARE must be 0 or 1")
        if self.gshare and self.btb_idx_bits < 6:
            errors.append("GSHARE requires BTB_IDX_BITS >= 6")
        if self.ras_depth > 64 or (
            self.ras_depth != 0 and self.ras_depth & (self.ras_depth - 1)
        ):
            errors.append("RAS_DEPTH must be zero or a power of two up to 64")
        return errors

    def identity(self) -> str:
        return f"bp{self.btb_idx_bits}_{self.btb_tag_bits}_{self.gshare}_{self.ras_depth}"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btb-idx-bits", required=True)
    parser.add_argument("--btb-tag-bits", required=True)
    parser.add_argument("--gshare", required=True)
    parser.add_argument("--ras-depth", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        PredictorConfiguration.parse(
            args.btb_idx_bits,
            args.btb_tag_bits,
            args.gshare,
            args.ras_depth,
        )
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
