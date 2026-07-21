# Tests

This directory will contain the LOP test suite.

## Planned Structure

```
tests/
├── conftest.py          # pytest fixtures (app factory, test client, seeded DB)
├── unit/
│   ├── test_models.py   # Model validation and relationships
│   └── test_queries.py  # Query helper unit tests
├── integration/
│   ├── test_dashboard.py   # Dashboard stats accuracy
│   ├── test_inventory.py   # CRUD operations end-to-end
│   ├── test_settings.py    # Location / Environment / Owner CRUD
│   └── test_api.py         # REST API endpoints (Ansible push)
└── fixtures/
    └── sample_data.sql  # SQL fixture for reproducible test data
```

## Running Tests

```bash
# Install test dependencies (once added to requirements.txt)
pip install pytest pytest-flask coverage

# Run all tests
pytest

# Run with coverage report
coverage run -m pytest
coverage report -m

# Run a specific module
pytest tests/integration/test_inventory.py -v
```

## Test Configuration

Tests use the `TestingConfig` (see `app/config.py`):
- SQLite in-memory database (no PostgreSQL required)
- CSRF protection disabled
- Debug mode off

## Writing Tests

Follow the existing `TestingConfig` pattern in `app/config.py`. Use the
application factory (`create_app("testing")`) so tests are isolated.
