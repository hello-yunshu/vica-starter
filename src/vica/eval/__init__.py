"""VICA v0.2 — Benchmark Research & External Evaluation protocol.

Portable artifacts and authoritative verification for the closed loop:

    Prepare Evaluation -> Public Bundle -> External Solver -> Submission Bundle
        -> Authoritative Verify -> Result Bundle -> Independent Reverify
        -> Benchmark Research Report

See docs/BENCHMARK_METHODOLOGY.md and docs/protocol/BUNDLE.md.
"""

from vica.eval.bundle import (
    inspect_evaluation,
    load_private_manifest,
    load_public_challenges,
    load_public_manifest,
    load_verifier_material,
    prepare_evaluation,
)
from vica.eval.models import (
    BUNDLE_FORMAT_VERSION,
    RESULT_BUNDLE_VERSION,
    SUBMISSION_BUNDLE_VERSION,
    EvaluationFailure,
    ReportStatus,
    ResultRecord,
    to_result_record,
)
from vica.eval.reverify import reverify_bundle
from vica.eval.stats import (
    cost_coverage,
    failure_taxonomy,
    latency_distribution,
    paired_comparison,
    success_rate_with_ci,
    wilson_interval,
)
from vica.eval.submission import build_submission_bundle, load_submission_bundle
from vica.eval.verify import load_result_bundle, verify_evaluation

__all__ = [
    "BUNDLE_FORMAT_VERSION",
    "EvaluationFailure",
    "RESULT_BUNDLE_VERSION",
    "ReportStatus",
    "ResultRecord",
    "SUBMISSION_BUNDLE_VERSION",
    "build_submission_bundle",
    "cost_coverage",
    "failure_taxonomy",
    "inspect_evaluation",
    "latency_distribution",
    "load_private_manifest",
    "load_public_challenges",
    "load_public_manifest",
    "load_result_bundle",
    "load_submission_bundle",
    "load_verifier_material",
    "paired_comparison",
    "prepare_evaluation",
    "reverify_bundle",
    "success_rate_with_ci",
    "to_result_record",
    "verify_evaluation",
    "wilson_interval",
]