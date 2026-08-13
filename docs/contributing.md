# Contributing

`groundskeeping` follows the shared [cava-devops](https://github.com/AustralianCancerDataNetwork/cava-devops) CI/CD process. The canonical checklist lives in `CONTRIBUTING.md` at the repository root; this page summarises it for readers of the documentation site.

## Development setup

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

CI runs these checks, so run all of them before opening a pull request. Documentation changes should also pass:

```bash
uv run --extra dev mkdocs build --strict
```

## Open a pull request

Apply exactly one release label before merging. The label gate fails when no bump label or more than one bump label is present.

| Label | Use it for | Version effect |
|---|---|---|
| `breaking` | A backward-incompatible public API change | MAJOR |
| `feature` | Backward-compatible new functionality | MINOR |
| `fix` | A bug fix | PATCH |
| `dependencies` | A dependency version update | PATCH |
| `chore` | CI, refactoring, tests, or documentation with no public package effect | No release; excluded from the changelog |

When squash-merging, write a clear extended description in the merge dialog. That text, rather than the PR's opening description, becomes the changelog entry. Leave it blank for `chore` pull requests.

## Understand versions and releases

Versions are derived from git tags through `hatch-vcs`; there is no version string in source. `groundskeeping.__version__` reads installed distribution metadata.

Merging a labelled pull request updates a standing draft release. When a maintainer publishes that release, the new `vX.Y.Z` tag triggers:

- `publish.yml`, which builds the wheel and source distribution and uploads them to PyPI through a trusted publisher; and
- `docs.yml`, which deploys this site to GitHub Pages.

There is no automated commit back to `main`.
