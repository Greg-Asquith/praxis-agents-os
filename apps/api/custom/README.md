# Custom code

This directory holds the code that belongs to one deployment. Core ships it
empty. A deployment fills it in and can change anything inside it without
touching core code, so upstream merges stay clean.

Read [custom code](../../../docs/architecture/custom-code.md) for the design
and the import laws before you add code here.

## Seams

Core imports exactly four modules from this package. Keep their names and
exports:

| Module | Export | Core caller |
| --- | --- | --- |
| `custom.routes` | `router` | `routes/__init__.py` mounts it under `/custom` |
| `custom.models` | Model imports | `models/__init__.py` |
| `custom.runtime` | `register_custom_runtime()` | Runtime catalogue assembly |
| `custom.hooks` | `after_sign_in()`, `after_workspace_created()`, `before_membership_change()` | Sign-in, workspace creation, and membership changes |

Import hook implementations inside each hook function. Core auth and workspace
services import the `custom.hooks` module while they load.

## Layout

Group code by tool or feature below the seams:

```
custom/
  routes/REPORTS/        # one route operation per file
  models/reports.py      # imported from models/__init__.py
  runtime.py             # imports tool modules, registers job handlers
  settings.py            # deployment-owned BaseSettings
  reports/               # services for one feature, one operation per file
  tools/                 # agent tool definitions
```

- Put migrations on the Alembic `app` branch in `alembic/versions/app/`.
- Put tests in `tests/custom/`.
- Keep settings in a `BaseSettings` class inside this package, the way a
  provider package does. Don't add a mixin to `core/settings`.
- Serve routes that open from a link, without sign-in, under
  `/custom/public/{token}/...`. Core keeps that token out of logs and stops
  caches and search engines from keeping the response.
- Custom tables that hold workspace data need forced row-level security and a
  blindness test, the same as core tables.
