# storage

task_kind: repair

Fix the KV store: ``commit`` must persist open-transaction writes into the store; ``rollback`` must discard them. Hidden tests check commit persistence.

Modify `solution.py` and keep the `solve` interface. Public tests are in `tests/test_public.py`. Do not modify anything under `tests/`.
