"""SYNTH-v0.1 d4/d5 difficulty calibration harness.

Reproduces the target-generation loop of family._generate_all with a custom
(Preset) definition, runs the brute-force baseline on each target, and reports
the success rate (through hidden tests) plus the target node-count distribution.
Used to pick preset params that restore monotonic difficulty.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vica.challenges.synth_v01.family import (
    _PARAM_POOL,
    Preset,
    _make_rng,
    _sample_tests,
    eval_program,
    parse_program,
    program_to_source,
    sample_program,
)
from vica.systems.synth.brute_force import BruteForceSynthSystem


@dataclass
class Config:
    seed: int
    difficulty: int
    preset: Preset
    n: int
    reject_constant: bool = False
    min_nodes: int = 0


def _is_constant(
    target: tuple[Any, ...], params: list[str], rng: random.Random, width: int
) -> bool:
    """True if the target evaluates to the same value on several random inputs."""
    outputs: set[int] = set()
    for _ in range(20):
        inp = {p: rng.randint(-width, width) for p in params}
        try:
            outputs.add(eval_program(target, inp))
        except Exception:
            return False
        if len(outputs) > 1:
            return False
    return True


def _node_count(node: tuple[Any, ...]) -> int:
    if node[0] in ("num", "var"):
        return 1
    if node[0] in ("neg", "abs"):
        return 1 + _node_count(node[1])
    return 1 + _node_count(node[1]) + _node_count(node[2])


def run_calib(cfg: Config) -> dict[str, Any]:
    rng = _make_rng(str(cfg.seed), cfg.difficulty)
    params = list(_PARAM_POOL[cfg.difficulty])
    p: Preset = cfg.preset

    brute = BruteForceSynthSystem()
    successes = 0
    solved = 0  # brute found any public-passing candidate
    node_counts: list[int] = []
    total_ms = 0.0
    examples: list[dict[str, Any]] = []
    n_constant = 0

    for _i in range(cfg.n):
        target: tuple[Any, ...] | None = None
        public: list[dict[str, Any]] | None = None
        hidden: list[dict[str, Any]] | None = None
        for _ in range(50):
            c = sample_program(
                rng, params, p.ops, p.unary, p.max_depth, p.input_width
            )
            if c[0] in ("num", "var"):
                continue
            if _is_constant(c, params, rng, p.input_width):
                n_constant += 1
                if cfg.reject_constant:
                    continue
            if cfg.min_nodes and _node_count(c) < cfg.min_nodes:
                continue
            pub = _sample_tests(rng, params, p, c, p.public_tests)
            if pub is None:
                continue
            hid = _sample_tests(rng, params, p, c, p.hidden_tests)
            if hid is None:
                continue
            target, public, hidden = c, pub, hid
            break
        if target is None:
            raise RuntimeError("no target")
        assert public is not None and hidden is not None

        node_counts.append(_node_count(target))
        payload = {
            "function": {"name": "f", "params": params},
            "public_tests": public,
            "input_width": p.input_width,
            "budget": {"code_size": p.code_size, "max_eval_ms": 10},
        }
        out = brute.solve({"payload": payload})
        total_ms += out.metadata.get("solve_wall_time_ms", 0.0)
        if out.candidate is None:
            continue
        solved += 1
        # verify through hidden tests
        try:
            node = parse_program(str(out.candidate["program"]))
            ok = True
            for t in hidden:
                if eval_program(node, dict(t["input"])) != t["expected"]:
                    ok = False
                    break
        except Exception:
            ok = False
        if ok:
            successes += 1
        if len(examples) < 3:
            examples.append(
                {
                    "target": program_to_source(target),
                    "nodes": _node_count(target),
                    "brute_cand": out.candidate["program"] if out.candidate else None,
                    "ok": ok,
                }
            )

    return {
        "ops": p.ops,
        "unary": p.unary,
        "max_depth": p.max_depth,
        "input_width": p.input_width,
        "n": cfg.n,
        "reject_constant": cfg.reject_constant,
        "min_nodes": cfg.min_nodes,
        "constant_rate": round(n_constant / cfg.n, 2),
        "success_rate": successes / cfg.n,
        "solved_rate": solved / cfg.n,
        "mean_nodes": round(sum(node_counts) / len(node_counts), 2),
        "max_nodes": max(node_counts),
        "mean_brute_ms": round(total_ms / cfg.n, 1),
        "examples": examples,
    }


def _fmt(cfg: Config, r: dict[str, Any]) -> str:
    tag = ""
    if r["reject_constant"]:
        tag += "+rej-const "
    if r["min_nodes"]:
        tag += f"+minN{r['min_nodes']} "
    return (
        f"d{cfg.difficulty} depth={r['max_depth']} w={r['input_width']} "
        f"unary={','.join(r['unary']) or '-'}  [{tag.strip()}]  "
        f"success={r['success_rate']*100:5.1f}%  solved={r['solved_rate']*100:5.1f}%  "
        f"const={r['constant_rate']*100:3.0f}%  "
        f"nodes mean={r['mean_nodes']} max={r['max_nodes']}  brute_ms={r['mean_brute_ms']}"
    )


def main() -> None:
    seed = 42
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    base = Preset(("+", "-", "*", "%", "//", "min", "max"), (), 4, 20)

    configs: list[tuple[int, Preset, bool, int]] = [
        # current d3 baseline for reference
        (3, base, False, 0),
        # current d4/d5 (no filters) for reference
        (4, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs",), 5, 20), False, 0),
        (5, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs", "neg"), 6, 20), False, 0),
        # reject constant only
        (4, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs",), 5, 20), True, 0),
        (5, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs", "neg"), 6, 20), True, 0),
        # reject constant AND enforce min target complexity
        (4, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs",), 5, 20), True, 5),
        (4, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs",), 5, 20), True, 6),
        (5, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs", "neg"), 6, 20), True, 7),
        (5, Preset(("+", "-", "*", "%", "//", "min", "max"), ("abs", "neg"), 6, 20), True, 8),
    ]

    print(f"seed={seed} n={n}\n")
    seen_keys: set[tuple[int, int, int, bool, int]] = set()
    for difficulty, preset, reject_const, min_nodes in configs:
        key = (difficulty, preset.max_depth, preset.input_width, reject_const, min_nodes)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        cfg = Config(
            seed=seed,
            difficulty=difficulty,
            preset=preset,
            n=n,
            reject_constant=reject_const,
            min_nodes=min_nodes,
        )
        r = run_calib(cfg)
        print(_fmt(cfg, r))
        for ex in r["examples"]:
            print(
                f"    target={ex['target']}({ex['nodes']}n) "
                f"brute={ex['brute_cand']} ok={ex['ok']}"
            )


if __name__ == "__main__":
    main()