# Contributing

`groundskeeping` follows the shared
[cava-devops](https://github.com/AustralianCancerDataNetwork/cava-devops) CI/CD process. The
canonical checklist lives in `CONTRIBUTING.md` at the repository root; this page summarises it
for readers of the docs site.

## Development setup

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

CI runs exactly these four commands, so a clean local run is a clean pipeline.

## Opening a pull request

Apply **exactly one** label before merging. The label gate fails the build if none or more
than one bump label is present.

| Label | When to use | Version effect |
|---|---|---|
| `breaking` | Public API change, backward-incompatible | MAJOR |
| `feature` | New functionality, backward-compatible | MINOR |
| `fix` | Bug fix | PATCH |
| `dependencies` | Dependency version update | PATCH |
| `chore` | CI changes, refactoring, test additions, docs — anything that does not affect the public-facing package | None; bypasses the gate and is excluded from the changelog |

When merging (squash), write a clear extended description in the merge dialog. That text — not
the PR's opening description — becomes the changelog entry for this change. Leave it blank for
`chore` PRs.

## Versioning and releases

Versions are derived from git tags via `hatch-vcs`; there is no version string in any source
file. `groundskeeping.__version__` reads the installed distribution metadata.

Merging a labelled PR updates a standing draft release. A maintainer publishes that draft when
the change is ready to ship, which creates the `vX.Y.Z` tag and triggers:

- `publish.yml` — builds the wheel and sdist and uploads to PyPI via a trusted publisher; and
- `docs.yml` — deploys this site to GitHub Pages.

There is no automated commit-back to `main`.
