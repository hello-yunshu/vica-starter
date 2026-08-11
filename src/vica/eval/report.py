"""Answer-first Result Report rendering (docs/BENCHMARK_METHODOLOGY.md).

``render_report`` produces the ``report.md`` embedded in a Result Bundle. It is
answer-first: the top summarises Evaluation, System, Challenges, Valid rate
with 95% CI, latency, known-cost coverage, main failure modes and OPT regret
(when relevant); only then come the details.

It never emits a fabricated "Overall Winner / Best AI / Best Model": unless a
caller explicitly supplies a paired comparison, the default output is
per-family / per-difficulty / per-metric only.
"""

from __future__ import annotations

from typing import Any

from vica.eval.metrics import summarize
from vica.eval.models import ReportStatus, ResultRecord


def render_report(
    *,
    evaluation: dict[str, Any],
    system_id: str,
    results: list[ResultRecord],
    git_commit: str | None = None,
    paired: dict[str, Any] | None = None,
) -> str:
    """Render a markdown Result Report for one system / evaluation."""
    summary = summarize(results)
    correc = summary["correctness"]
    latency = summary["latency"]
    cost = summary["cost"]
    taxonomy = summary["failure_taxonomy"]
    quality = summary["quality"]

    ci = _fmt_ci(correc.get("ci_lower"), correc.get("ci_upper"))
    lines: list[str] = []
    lines.append("# VICA Result Report")
    lines.append("")
    lines.append(f"- **Evaluation** `{evaluation.get('evaluation_id')}`")
    lines.append(
        f"- **Challenge type** `{evaluation.get('challenge_type')}` "
        f"(`{evaluation.get('generator_version')}`)"
    )
    lines.append(f"- **System** `{system_id}`")
    lines.append(f"- **Challenges** {summary['sample_count']}")
    lines.append(
        f"- **Valid rate** {_pct(correc.get('success_rate'))} 95% CI {ci} "
        f"(n={summary['sample_count']})"
    )
    lines.append(
        f"- **Latency** mean {_num(latency.get('mean'), 'ms')} "
        f"p50 {_num(latency.get('p50'), 'ms')} "
        f"p95 {_num(latency.get('p95'), 'ms')}"
    )
    lines.append(
        f"- **Known cost coverage** {_pct(cost.get('cost_coverage'))} "
        f"({cost.get('known')}/{cost.get('total')})"
    )
    lines.append(f"- **Main failure modes** {_main_failures(taxonomy)}")
    if quality.get("regret_instances"):
        lines.append(
            f"- **OPT regret** mean {_num(quality.get('mean_regret'))} "
            f"(n={quality['regret_instances']})"
        )
    lines.append("")

    # Correctness by difficulty.
    lines.append("## Correctness by difficulty")
    lines.append("")
    lines.append("| difficulty | valid | rate | 95% CI |")
    lines.append("|---|---|---|---|")
    for diff, row in sorted(summary["by_difficulty"].items()):
        lines.append(
            f"| {diff} | {row.get('valid')} | {_pct(row.get('success_rate'))} | "
            f"{_fmt_ci(row.get('ci_lower'), row.get('ci_upper'))} |"
        )
    lines.append("")

    # Failure taxonomy.
    lines.append("## Failure taxonomy")
    lines.append("")
    lines.append("| status | count | rate |")
    lines.append("|---|---|---|")
    for status, count in sorted(taxonomy["counts"].items()):
        lines.append(f"| {status} | {count} | {_pct(taxonomy['rates'].get(status))} |")
    lines.append("")

    # OPT quality.
    if quality.get("regret_instances"):
        lines.append("## Quality (OPT)")
        lines.append("")
        lines.append(
            f"- mean regret = {_num(quality.get('mean_regret'))} over "
            f"{quality['regret_instances']} valid instances"
        )
        lines.append("")

    # Paired comparison (only when explicitly provided).
    if paired:
        lines.append("## Paired comparison")
        lines.append("")
        lines.append(
            f"- **System A** `{paired.get('system_a')}` vs **System B** `{paired.get('system_b')}`"
        )
        lines.append(f"- compared challenges: {paired.get('compared')}")
        lines.append(
            f"- A wins: {paired.get('a_wins')} | B wins: {paired.get('b_wins')} "
            f"| tie: {paired.get('tie')} | both fail: {paired.get('both_fail')}"
        )
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- VICA version: {evaluation.get('vica_version')}")
    lines.append(f"- git commit: {git_commit or 'unknown'}")
    lines.append(
        f"- verifier material commitment: "
        f"{evaluation.get('verifier_material_commitment') or 'none'}"
    )
    lines.append("")
    lines.append("> This report is a research artifact. It compares dimensions "
                 "independently and does not imply an overall winner across "
                 "different challenge families, difficulty distributions, budgets, "
                 "or cost definitions.")
    lines.append("")
    return "\n".join(lines)


def _main_failures(taxonomy: dict[str, Any]) -> str:
    counts = taxonomy.get("counts") or {}
    non_valid = {k: v for k, v in counts.items() if k != ReportStatus.VALID.value and v > 0}
    if not non_valid:
        return "none"
    top = sorted(non_valid.items(), key=lambda kv: -kv[1])[:3]
    return ", ".join(f"{k}={v}" for k, v in top)


def _pct(v: Any) -> str:
    return "N/A" if v is None else f"{v:.3f}"


def _num(v: Any, suffix: str = "") -> str:
    if v is None:
        return "N/A"
    return f"{v:.1f}{suffix}"


def _fmt_ci(lo: Any, hi: Any) -> str:
    if lo is None or hi is None:
        return "N/A"
    return f"[{lo:.3f}, {hi:.3f}]"


__all__ = ["render_report"]