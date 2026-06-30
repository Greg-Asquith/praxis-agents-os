# apps/api/utils/request.py

from ipaddress import ip_address

from fastapi import Request

from core.rate_limiting import get_client_ip


def request_ip(request: Request) -> str:
    candidate = get_client_ip(request)
    try:
        ip_address(candidate)
        return candidate
    except ValueError:
        return "127.0.0.1"
