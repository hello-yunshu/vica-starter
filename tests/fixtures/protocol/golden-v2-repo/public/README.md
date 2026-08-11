# Evaluation Bundle

evaluation_id: eval-48376e5606cb
challenge_type: repo-v0.1
generator_version: 0.1.0
challenge_count: 1

This is the PUBLIC part of an evaluation bundle. It contains only the
solver-visible challenges. It must be the ONLY material handed to an
external solver / coding agent.

This evaluation is verifier-material-bound: challenges carry a public
SHA-256 commitment of the verifier material. The reference target and
hidden tests are NOT in this bundle and are only derivable by the
evaluator who holds the material.

Submit answers as a Submission Bundle (see docs/protocol/BUNDLE.md):
a manifest.json plus a submissions.jsonl with one line per challenge:

    {"challenge_id": "...", "candidate": {...}, "metadata": {...}}
