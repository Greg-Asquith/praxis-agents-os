# apps/api/services/integrations/microsoft_graph/preauthenticated.py

"""Keep connection credentials away from pre-authenticated file URLs."""

from collections.abc import Generator

import httpx2


class PreauthenticatedFileAuth(httpx2.Auth):
    """Removes inherited credentials after the client builds its request."""

    def auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        for header in ("Authorization", "Proxy-Authorization", "Cookie"):
            request.headers.pop(header, None)
        yield request
