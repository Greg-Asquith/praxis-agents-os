# apps/api/utils/decode.py

import base64


def decode_base64url(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8", errors="replace")
