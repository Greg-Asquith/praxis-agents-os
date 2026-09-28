"""Shared builders for Google Search Console integration tests."""


async def static_token(_force: bool) -> str:
    return "access-token"
