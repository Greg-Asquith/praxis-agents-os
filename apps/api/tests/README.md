<!-- apps/api/tests/README.md -->

# API test structure

Group tests by the behavior they prove. Don't add a flat collection of
unrelated `test_*.py` files at the root of this directory.

## Layout

- `contract/` contains cheap API-shape tests: route registration, HTTP methods,
  OpenAPI metadata, and public boundary rules.
- `routes/` contains thin route tests. These should verify request parsing,
  verify request parsing, dependency wiring, status codes, response models,
  and cookies. Business rules
  belong in service tests.
- `services/` contains behavioral tests for service operations. This is the main
  place for authentication decisions, user mutations, provider calls, audit
  logging, and
  security logging.
- `integration/` contains end-to-end API/database flows for key journeys only.
  Use a few meaningful flows instead of duplicating route and service
  tests.
- `middleware/` contains focused tests for middleware behavior such as CSRF, rate
  limiting, security headers, request IDs, and request transaction handling.
- `factories/` contains test data builders. Factories should build explicit,
  unsurprising model objects and avoid hiding assertions.
- `support/` contains shared pytest helpers and fixtures. Keep it small. Move
  helpers closer to tests when they are only used by one area.

## Database tests

Database-backed tests must use PostgreSQL through `TEST_DATABASE_URL`. Don't
use SQLite as a behavioral substitute for this API. Tests that require a database
must call the `test_database_url` fixture so they skip cleanly until a test
database is configured.

## Choose what to test

Do not write a test for every route file or every service file by default. Add
tests for the routes, services, and flows where the behavior is high-risk,
security-sensitive, externally observable, or easy to regress.
