"""Bundle version dispatcher — §14 (docs/SPEC.md "Evaluation Bundle Versioning").

A v1 artifact is interpreted strictly by the v1 reader and a v2 artifact
strictly by the v2 reader; we never silently reinterpret a v1 bundle with v2
semantics. Only the *advertised* version string differs between the two
layouts for ordinary families; the v2 Evaluation layout additionally carries a
solver-visible ``workspaces/`` directory (real REPO challenge workspaces).

This module centralizes version detection / routing so callers never scatter
``if version == ... elif version == ...`` across the codebase.
"""

from __future__ import annotations

from vica.eval.models import (
    BUNDLE_FORMAT_VERSION,
    BUNDLE_FORMAT_VERSION_V2,
    RESULT_BUNDLE_VERSION,
    RESULT_BUNDLE_VERSION_V2,
    SUBMISSION_BUNDLE_VERSION,
    SUBMISSION_BUNDLE_VERSION_V2,
    EvaluationFailure,
)

# Evaluation / Submission / Result bundle versions this build can *read*.
# v1 is the v0.2 layout; v2 is the v0.3 Workspace layout. Both remain
# 1.0-compatibility targets.
SUPPORTED_EVALUATION_VERSIONS = (BUNDLE_FORMAT_VERSION, BUNDLE_FORMAT_VERSION_V2)
SUPPORTED_SUBMISSION_VERSIONS = (SUBMISSION_BUNDLE_VERSION, SUBMISSION_BUNDLE_VERSION_V2)
SUPPORTED_RESULT_VERSIONS = (RESULT_BUNDLE_VERSION, RESULT_BUNDLE_VERSION_V2)


def check_evaluation_version(advertised: object, label: str) -> str:
    """Return a normalized supported Evaluation version or raise."""
    return _check(advertised, SUPPORTED_EVALUATION_VERSIONS, label, "Evaluation")


def check_submission_version(advertised: object, label: str) -> str:
    """Return a normalized supported Submission version or raise."""
    return _check(advertised, SUPPORTED_SUBMISSION_VERSIONS, label, "Submission")


def check_result_version(advertised: object, label: str) -> str:
    """Return a normalized supported Result version or raise."""
    return _check(advertised, SUPPORTED_RESULT_VERSIONS, label, "Result")


def _check(advertised: object, supported: tuple[str, ...], label: str, kind: str) -> str:
    if not isinstance(advertised, str) or advertised not in supported:
        raise EvaluationFailure(
            f"unsupported {kind} bundle version {advertised!r} in {label}; "
            f"supported: {sorted(supported)}"
        )
    return advertised


def is_v2(version: str) -> bool:
    """True when the advertised version is the v2 Workspace layout."""
    return version == BUNDLE_FORMAT_VERSION_V2


# Evaluation / Submission / Result bundle versions are strictly paired:
# Evaluation v1 ↔ Submission v1 ↔ Result v1 and Evaluation v2 ↔ Submission v2
# ↔ Result v2. A bundle is never matched to a different version than the
# evaluation it was produced from (§32-34).
def expected_bundle_versions(evaluation_version: object) -> tuple[str, str]:
    """The Submission and Result bundle versions required for an Evaluation.

    Raises ``EvaluationFailure`` for an unknown evaluation version.
    """
    if evaluation_version == BUNDLE_FORMAT_VERSION:
        return SUBMISSION_BUNDLE_VERSION, RESULT_BUNDLE_VERSION
    if evaluation_version == BUNDLE_FORMAT_VERSION_V2:
        return SUBMISSION_BUNDLE_VERSION_V2, RESULT_BUNDLE_VERSION_V2
    raise EvaluationFailure(
        f"unsupported evaluation bundle version {evaluation_version!r}; "
        f"supported: {sorted(SUPPORTED_EVALUATION_VERSIONS)}"
    )


__all__ = [
    "SUPPORTED_EVALUATION_VERSIONS",
    "SUPPORTED_RESULT_VERSIONS",
    "SUPPORTED_SUBMISSION_VERSIONS",
    "check_evaluation_version",
    "check_result_version",
    "check_submission_version",
    "is_v2",
]