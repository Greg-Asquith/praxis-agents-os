<!-- apps/api/tests/routes/README.md -->

# Route tests

Route tests cover the HTTP boundary only: request parsing, dependency wiring,
status codes, response models, headers, and cookies.

Keep business-rule assertions in `tests/services/` unless the route itself is
responsible for the behavior.
