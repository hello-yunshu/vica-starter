# Repository Setup

## Local Git

```bash
git init
git branch -M main
git add .
git commit -m "chore: bootstrap VICA repository"
```

## Recommended GitHub repository settings

Suggested repository name:

```text
vica
```

Alternative names:

```text
vica-arena
verifiable-intelligence-arena
vica-benchmark
```

Suggested description:

```text
An open benchmark and research platform for verifiable problem-solving efficiency across AI models, agents, traditional solvers, and hybrid systems.
```

Recommended visibility for early research:

```text
Private initially
```

Switch to public after:

- protocol schema is stable enough to explain;
- no secrets or proprietary benchmark data are present;
- README clearly states the research scope;
- first reproducible benchmark is available.

## GitHub topics

```text
ai
benchmark
agents
verifiable-computing
optimization
program-synthesis
llm
solver
research
```

## Suggested branch protection later

For `main`:

- require pull request
- require CI
- require branch up to date
- block force pushes
- block deletion

## First labels

```text
protocol
challenge
verifier
benchmark
baseline
model-adapter
security
research
documentation
good-first-issue
```

## First milestone

```text
MVP: CSP-v0.1 Local Arena
```

## First issues

Use the issue list in `docs/TASKS.md`.
