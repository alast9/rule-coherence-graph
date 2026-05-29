# Releasing

The package is published to PyPI as **`rule-coherence-graph`** (import name and
CLI command remain `rcg`).

1. Make sure CI is green on `main` (ruff + mypy + pytest).
2. Bump `version` in `pyproject.toml` (semver).
3. Build the distributions:
   ```bash
   uv build            # -> dist/rule_coherence_graph-<v>-py3-none-any.whl + .tar.gz
   uvx twine check dist/*
   ```
4. Publish (needs a PyPI API token; the first upload reserves the name):
   ```bash
   uvx twine upload dist/*
   # or: uv publish --token "$PYPI_TOKEN"
   ```
5. Tag the release:
   ```bash
   git tag v<version> && git push --tags
   ```

`dist/` and `build/` are git-ignored; never commit build artifacts.
