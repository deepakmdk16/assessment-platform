"""The security headers have to survive nginx's add_header inheritance rule.

`add_header` is inherited from the enclosing level **only if the current level
declares none of its own**. `location /assets/` and `location = /index.html`
both set Cache-Control, and every response the SPA is actually made of comes out
of one of those two blocks — so a CSP declared once in `server` would be present
on nothing but the API proxy. That failure is silent: the app works, the headers
are simply absent where they matter. These tests pin the include into every
block that sets a header of its own.

The nginx config is not exercised by the rest of the suite (it lives in the web
image, not in the app), so these are file invariants plus a real run of the
start-up script that renders security.txt.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "web" / "nginx.conf.template"
SNIPPET = REPO / "web" / "nginx-security-headers.conf"
SCRIPT = REPO / "web" / "docker-entrypoint.d" / "30-security-txt.sh"
INCLUDE = "include /etc/nginx/snippets/security-headers.conf;"


def _uncommented(path: Path) -> str:
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")
    )


def _blocks(text: str, keyword: str) -> list[tuple[str, str]]:
    """(header, body) for every `<keyword> ... { ... }` block, braces balanced."""
    found: list[tuple[str, str]] = []
    for match in re.finditer(rf"^\s*({keyword}[^{{]*)\{{", text, re.M):
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        found.append((match.group(1).strip(), text[match.end() : i - 1]))
    return found


def test_every_block_with_its_own_add_header_reincludes_the_security_headers() -> None:
    text = _uncommented(TEMPLATE)
    offenders = [
        head
        for head, body in _blocks(text, "location")
        if "add_header" in body and INCLUDE not in body
    ]
    assert not offenders, (
        f"these blocks set add_header of their own, which cancels inheritance, and "
        f"do not re-include the security headers: {offenders}"
    )


def test_the_server_level_carries_the_headers_for_every_other_response() -> None:
    text = _uncommented(TEMPLATE)
    (_, server) = _blocks(text, "server")[0]
    outside_locations = re.sub(r"location[^{]*\{", "{", server)
    for _, body in _blocks(server, "location"):
        outside_locations = outside_locations.replace(body, "")
    assert INCLUDE in outside_locations, (
        "the server block itself must include the headers, or the API proxy and "
        "every try_files response ships without them"
    )


def test_the_headers_are_complete_and_set_on_error_responses_too() -> None:
    snippet = SNIPPET.read_text()
    for directive in (
        "default-src 'self'",
        "img-src 'self' data: blob:",
        "style-src 'self' 'unsafe-inline'",
        "worker-src 'self' blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ):
        assert directive in snippet, f"CSP is missing {directive!r}"

    for header in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Strict-Transport-Security",
    ):
        line = next(
            line
            for line in snippet.splitlines()
            if line.lstrip().startswith(f"add_header {header}")
        )
        # Without `always` nginx drops the header on 4xx/5xx — the responses an
        # injected page is most likely to be served as.
        assert line.rstrip().endswith("always;"), f"{header} is not `always`"


def test_hsts_stays_off_until_a_deployment_sets_it() -> None:
    # Meaningless over plain HTTP and sticky for as long as its max-age says, so
    # it is a deployment setting. nginx omits an add_header whose value is empty.
    assert 'set $hsts_header "${HSTS_HEADER}";' in TEMPLATE.read_text()
    assert "add_header Strict-Transport-Security $hsts_header always;" in SNIPPET.read_text()


def test_security_txt_is_not_answered_by_the_spa_fallback() -> None:
    # `location /` ends at index.html, so without an exact match a missing
    # security.txt would be served as the app with a 200.
    body = dict(_blocks(_uncommented(TEMPLATE), "location"))["location = /.well-known/security.txt"]
    assert "try_files $uri =404;" in body


def test_security_txt_is_served_as_utf_8() -> None:
    # RFC 9116 §3 makes the charset part of the media type, and nginx's
    # mime.types maps .txt to a bare text/plain.
    body = dict(_blocks(_uncommented(TEMPLATE), "location"))["location = /.well-known/security.txt"]
    assert "charset utf-8;" in body


def test_the_startup_script_is_executable() -> None:
    # The stock nginx entrypoint runs the executable files in /docker-entrypoint.d
    # and skips the rest with a log line nobody reads.
    mode = subprocess.run(
        ["git", "ls-files", "-s", str(SCRIPT.relative_to(REPO))],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()[0]
    assert mode == "100755", f"{SCRIPT.name} is tracked as {mode}, so nginx will ignore it"


def _render(tmp_path: Path, **env: str) -> Path:
    subprocess.run(
        ["sh", str(SCRIPT)],
        check=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"], "SECURITY_TXT_ROOT": str(tmp_path), **env},
    )
    return tmp_path / ".well-known" / "security.txt"


def test_the_contact_falls_back_to_the_support_address(tmp_path: Path) -> None:
    out = _render(tmp_path, SUPPORT_EMAIL="support@assess.dev")
    assert "Contact: mailto:support@assess.dev" in out.read_text()


def test_an_explicit_security_contact_wins(tmp_path: Path) -> None:
    out = _render(tmp_path, SECURITY_CONTACT="security@acme.com", SUPPORT_EMAIL="support@acme.com")
    assert "Contact: mailto:security@acme.com" in out.read_text()


def test_a_contact_that_is_already_a_uri_is_left_alone(tmp_path: Path) -> None:
    # RFC 9116 §2.5.3 allows any URI, so a bug-bounty page is a valid contact —
    # and `mailto:https://…` would be a valid-looking way to publish nothing.
    out = _render(tmp_path, SECURITY_CONTACT="https://hackerone.com/acme")
    assert "Contact: https://hackerone.com/acme" in out.read_text()


def test_expires_is_a_year_out_and_machine_readable(tmp_path: Path) -> None:
    # RFC 9116 makes Expires a MUST, and a file baked at build time would go
    # stale on the shelf — hence rendering it at container start.
    out = _render(tmp_path, SECURITY_CONTACT="security@acme.com")
    value = next(
        line.split(": ", 1)[1] for line in out.read_text().splitlines() if line.startswith("Expires:")
    )
    delta = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - datetime.now(
        timezone.utc
    )
    assert timedelta(days=360) < delta <= timedelta(days=366), value


def test_the_canonical_url_is_published_when_the_public_host_is_known(tmp_path: Path) -> None:
    out = _render(
        tmp_path, SECURITY_CONTACT="security@acme.com", PUBLIC_BASE_URL="https://acme.example.com/"
    )
    assert "Canonical: https://acme.example.com/.well-known/security.txt" in out.read_text()


def test_no_address_publishes_nothing(tmp_path: Path) -> None:
    # An empty Contact makes the file invalid; a 404 says "not published" honestly.
    stale = tmp_path / ".well-known" / "security.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("Contact: mailto:gone@acme.com\n")
    assert not _render(tmp_path).exists()
