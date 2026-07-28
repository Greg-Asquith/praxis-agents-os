# apps/api/services/artifacts/domain.py

"""Artifact types and serving security policy."""

from urllib.parse import urlsplit

from core.settings import settings

ARTIFACT_TYPES = frozenset({"html", "markdown", "mermaid", "csv", "image-ref"})
CREATABLE_ARTIFACT_TYPES = frozenset({"html", "markdown", "mermaid", "csv"})
ARTIFACT_EXTENSIONS = {
    "html": ".html",
    "markdown": ".md",
    "mermaid": ".mmd",
    "csv": ".csv",
}
ARTIFACT_CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "markdown": "text/plain; charset=utf-8",
    "mermaid": "text/plain; charset=utf-8",
    "csv": "text/plain; charset=utf-8",
}
ARTIFACT_STORAGE_CONTENT_TYPES = {
    "html": "text/html",
    "markdown": "text/markdown",
    "mermaid": "text/plain",
    "csv": "text/csv",
}
# External hosts are forbidden. Future vendor assets must be checked in and
# served from a path-scoped source on the artifact origin.
ARTIFACT_CSP_CDN_HOSTS: tuple[str, ...] = ()


def artifact_frame_ancestors() -> str:
    ancestors = ["'self'"]
    for candidate in (settings.FRONTEND_URL, *settings.cors_origins_list):
        parsed = urlsplit(candidate)
        if parsed.scheme and parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in ancestors:
                ancestors.append(origin)
    return " ".join(ancestors)


def build_html_csp(*, connect_src: str, frame_ancestors: str) -> str:
    return (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src data: blob:; font-src data:; "
        f"connect-src {connect_src}; frame-ancestors {frame_ancestors}; "
        "base-uri 'none'; form-action 'none'; object-src 'none'; sandbox allow-scripts"
    )


def build_plain_csp(*, frame_ancestors: str) -> str:
    return (
        f"default-src 'none'; frame-ancestors {frame_ancestors}; "
        "base-uri 'none'; form-action 'none'; sandbox"
    )


def serving_headers(*, artifact_type: str, content_type: str) -> dict[str, str]:
    csp = (
        build_html_csp(connect_src="'none'", frame_ancestors=artifact_frame_ancestors())
        if artifact_type == "html"
        else build_plain_csp(frame_ancestors=artifact_frame_ancestors())
    )
    return {
        "Content-Type": content_type,
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }
