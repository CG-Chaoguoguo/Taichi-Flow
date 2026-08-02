# GitHub Branch Workflow

Last updated: 2026-04-12

This workflow is intended for publishing EDDA-Taichi to GitHub while preserving
scientific traceability.

## Recommended Initial Publication Flow

```powershell
git status --short
git switch -c docs/github-readiness
git add README.md docs PROJECT_REPORTS requirements.txt environment.yml .gitignore setup.py
git commit -m "docs: prepare repository for GitHub publication"
git remote add origin <your-github-repo-url>
git push -u origin docs/github-readiness
```

Open a pull request into `main` after reviewing the diff.

## Branch Naming

Use narrow branches with one purpose:

- `docs/...` for documentation only.
- `test/...` for tests, comparison scripts, fixtures, or CI.
- `feature/...` for solver or output features.
- `fix/...` for targeted bug fixes.
- `research/...` for exploratory diagnostics that may not enter production.

## Commit Hygiene

Before each commit:

```powershell
git status --short
git diff --stat
git diff -- README.md docs PROJECT_REPORTS requirements.txt environment.yml .gitignore
```

For solver branches, also run targeted checks and include the output in the pull
request description.

## What Not To Commit

Do not commit:

- `.venv/`, `.pytest_cache/`, `__pycache__/`, or `.taichi/`;
- `tests/output/` or `tests/comparison/output/`;
- full `EntireBanzigou1005` reference data or original EDDA binaries;
- generated logs, checkpoints, `*.npz`, or bulk raster outputs;
- private machine paths unless they are clearly documented as local examples.

## Pull Request Template

Use this structure manually until a formal GitHub template is added:

```text
Summary
- What changed and why.

Scientific impact
- State whether formulas, direction order, time stepping, dry/wet gates, or
  output semantics changed.
- If none changed, say so explicitly.

Validation
- Commands run.
- Reference case or fixture used.
- Key metrics.

Known limitations
- Remaining mismatch or untested path.
```

## Solver Change Rule

Any branch that touches `edda/solver/`, `edda/core/fields.py`, or real-case I/O
must identify the corresponding original EDDA Fortran source lines. Do not merge
solver changes justified only by speed, visual smoothness, or numerical
convenience.
