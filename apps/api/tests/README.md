<!-- apps/api/tests/README.md -->
# API Test Structure

Keep tests grouped by what they are proving. Do not add a flat collection of
unrelated `test_*.py` files at the root of this directory.

## Layout

- `contract/` contains cheap API-shape tests: route registration, HTTP methods,
  OpenAPI metadata, and public boundary rules.
- `routes/` contains thin route tests. These should verify request parsing,
  dependency wiring, status codes, response models, and cookies. Business rules
  belong in service tests.
- `services/` contains behavioral tests for service operations. This is the main
  place for auth decisions, user mutations, provider calls, audit logging, and
  security logging.
- `integration/` contains end-to-end API/database flows for key journeys only.
  Prefer a few meaningful flows over broad duplication of route and service
  tests.
- `middleware/` contains focused tests for middleware behavior such as CSRF, rate
  limiting, security headers, request IDs, and request transaction handling.
- `factories/` contains test data builders. Factories should build explicit,
  unsurprising model objects and avoid hiding assertions.
- `support/` contains shared pytest helpers and fixtures. Keep it small; move
  helpers closer to tests when they are only used by one area.

## Database Tests

Database-backed tests should use PostgreSQL through `TEST_DATABASE_URL`; do not
use SQLite as a behavioral substitute for this API. Tests that require a database
should call the `test_database_url` fixture so they skip cleanly until a test
database is configured.

## What To Test

Do not write a test for every route file or every service file by default. Add
tests for the routes, services, and flows where the behavior is high-risk,
security-sensitive, externally observable, or easy to regress.
