# REPO-v0.1 Shortcut Audit

> Status: **Established to current tests** — the enumerated probes below are
> implemented and verified in `tests/test_repo.py`. Each shortcut is either
> rejected as a solver outcome or explicitly documented as within sandbox scope.

## 1. Enumerated probes

The verifier and Agent runner are tested against the following obvious cheats
(§29 / §47). Each must not be misjudged as success:

| probe | handling | classified as |
|-------|----------|---------------|
| delete tests / rename `tests/` | structural: protected path | `STRUCTURAL_VIOLATION` |
| pytest-config bypass (skip discovery, `pytest.ini`, `pyproject` pytest-off, `conftest` global skip, `sitecustomize` monkeypatch, `sys.exit(0)`) | verifier calls `solution.solve` directly in the sandbox, not pytest — no discovery to bypass | test executes against the real function |
| hard-code challenge id / examples | does not change `solve` on hidden inputs | `HIDDEN_TEST_FAILURE` |
| read verifier env var | env is a minimal allowlist; `VICA_VERIFIER_SECRET` / `VICA_PRIVATE_*` never forwarded | `SANDBOX_ERROR` / no secret available |
| modify Evaluation Bundle / private path | workspace is materialized fresh; private path not present | `PATCH_APPLY_FAILURE` / `STRUCTURAL_VIOLATION` |
| symlink escape / path traversal in patch | `patch.py` + `workspace.py` reject | `STRUCTURAL_VIOLATION` / `WorkspaceError` |
| oversized patch | `MAX_PATCH_BYTES` / `MAX_CHANGED_FILES` | `STRUCTURAL_VIOLATION` |
| malformed / non-applicable patch | `git apply` failure | `PATCH_APPLY_FAILURE` |
| binary patch | text-only patch enforcement | `STRUCTURAL_VIOLATION` |
| environment probe | no host secrets in the sandbox env | no secret discovered |

## 2. Why shortcut resistance holds

- The verifier never runs pytest on the patched workspace; it loads
  `solution.solve` and calls it on the (public + secret-derived hidden) cases.
  This removes the entire class of pytest-discovery / skip / monkeypatch
  shortcuts.
- Protected paths (`tests/`, `private/`) are structural constraints checked
  before any execution.
- Hidden tests are regenerated from the verifier secret at verification time;
  they cannot be deleted or renamed away by the patch.
- Patch artifacts are bounded and re-applied via `git apply` in a fresh temp
  workspace; a patch that cannot apply is a solver outcome, not an evaluator
  failure (§25).

## 3. Sandbox scope

The sandbox enforces resource limits, a minimal environment, a clean cwd, and
bounded output. It provides **experimental local process isolation, not
hardened hostile-code isolation**. Filesystem / network isolation is incomplete
(§32). Shortcut resistance is established against the enumerated probes, not
against a hostile arbitrary-code attacker escaping the OS sandbox.