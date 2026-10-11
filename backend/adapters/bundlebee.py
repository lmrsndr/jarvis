"""Read-only audit of the real BundleBee public catalogue API.

No affiliate-click endpoint is called and no catalogue record is modified.
Owner configuration: BUNDLEBEE_API_BASE, e.g. https://your-domain/api.
"""

from __future__ import annotations
import ipaddress
import json
import os
import socket
import sys
from urllib.parse import urlparse
import requests


def public_url(url):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
        return bool(addresses) and all(
            ipaddress.ip_address(a[4][0]).is_global for a in addresses
        )
    except (OSError, ValueError):
        return False


def run(request):
    args = request["args"]
    if args.get("task") != "link_validation" or args.get("dry_run") is not True:
        raise ValueError(
            "This adapter only supports read-only link_validation with dry_run=true"
        )
    count = args.get("max_items", 20)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise ValueError("max_items must be an integer from 1 to 100")
    base = os.getenv("BUNDLEBEE_API_BASE", "").rstrip("/")
    parsed = urlparse(base)
    if (
        not base
        or parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Configure BUNDLEBEE_API_BASE in .env")
    if parsed.scheme == "http" and parsed.hostname not in (
        "127.0.0.1",
        "localhost",
        "::1",
    ):
        raise ValueError("Remote catalogue APIs require HTTPS")
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        base + "/products",
        params={"limit": count, "page": 1},
        timeout=15,
        allow_redirects=False,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get("items"), list):
        raise ValueError("Catalogue API response must contain items[]")
    findings = []
    for product in data["items"][:count]:
        url = product.get("productUrl", "")
        entry = {
            "product_id": str(product.get("_id", "")),
            "name": product.get("name", ""),
            "product_url": url,
            "affiliate_url_public": public_url(product.get("affiliateUrl", "")),
            "price_verified": False,
        }
        if not public_url(url):
            entry.update(
                status="needs_review",
                reason="Product URL is missing, malformed or not publicly routable",
            )
        else:
            try:
                result = session.head(url, timeout=8, allow_redirects=False)
                entry.update(
                    http_status=result.status_code,
                    status="reachable"
                    if 200 <= result.status_code < 300
                    else "needs_review",
                    reason="HEAD probe only; redirects, bot protection and content correctness require review",
                )
            except requests.RequestException:
                entry.update(
                    status="needs_review", reason="HEAD probe did not complete"
                )
        findings.append(entry)
    return {
        "ok": True,
        "verified": True,
        "scope": "Published catalogue, first page; URL checks and non-redirecting product HEAD probes. Prices and affiliate attribution are not verified.",
        "count": len(findings),
        "findings": findings,
        "changes_applied": False,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run(json.load(sys.stdin))))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
