# API error code reference

| Code | Meaning | Operator action |
| --- | --- | --- |
| 4010 | Session expired | Sign in again and retry the request. |
| 4032 | Workspace permission denied | Ask a workspace owner to grant the required role. |
| 4091 | Conflicting update | Refresh the resource and reapply the change. |
| 4290 | Request rate limited | Wait for the retry interval before trying again. |

Error 4032 means the authenticated user lacks the workspace permission required by the operation.
