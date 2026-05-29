# django-migraid

**Detect, diagnose, and auto-fix Django migration problems in Git workflows.**

## Quick Start

```bash
pip install django-migraid
```

Add `"migraid"` to `INSTALLED_APPS`, then:

```bash
python manage.py migraid doctor
```

## Why django-migraid?

When developers work in parallel on Django projects, migration conflicts are inevitable. `django-migraid` gives you a single toolkit that:

- **Diagnoses** every known migration issue class
- **Previews** exactly what it will change before touching a file
- **Auto-fixes** the safe cases (renumbering, conflict linearization)
- **Branch-aware** database management (provision and switch databases automatically as you switch git branches)
- **Protects** you from common footguns (rewriting applied migrations, operating on non-local DBs)

See [Known Issues](known-issues.md) for the full catalog.
