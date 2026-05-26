# Contributing to django-migraid

Thank you for contributing!

## Development Setup

```bash
git clone https://github.com/yourusername/django-migraid
cd django-migraid
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Running Tests

```bash
pytest                          # run all tests
pytest --cov=migraid            # with coverage
pytest tests/test_analysis/     # specific module
tox                             # full matrix (Python 3.10-3.12 × Django 4.2/5.0/5.1)
```

## Adding a New Issue Detector

1. Add an issue code and description to the table in `docs/known-issues.md`
2. Add the code to `src/migraid/analysis/issues.py` — write a detector function following the `Callable[[MigrationAnalyzer], list[Issue]]` signature
3. Register it in `ALL_DETECTORS` at the bottom of `issues.py`
4. Write a test in `tests/test_analysis/test_issues.py` with a fixture from `tests/fixtures/`

## Code Style

- `ruff check src tests` — zero issues
- `ruff format src tests` — consistent formatting
- `mypy src/migraid` — strict, clean
- Type hints on every public function

## Pull Request Checklist

- [ ] Tests added / updated
- [ ] `pytest --cov=migraid` ≥ 85%
- [ ] `ruff check src tests` passes
- [ ] `mypy src/migraid` passes
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
