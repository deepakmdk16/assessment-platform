"""Request correlation, structured logs, error reporting and metrics (X08).

Four concerns that all answer one operational question — "what is this server
doing, and what just broke?" — and all four need the same request id, so they
live together rather than in four modules.

* **Request ids.** `adopt_request_id` puts the inbound `X-Request-Id` (or a fresh
  one) in a contextvar; `RequestIdFilter` copies it onto every log record, the
  middleware echoes it on the response, and `agent_client` forwards it on the
  outbound trigger. One id therefore spans submit -> trigger -> grade -> callback
  across both services, which is the hop X08 exists to make debuggable.

* **Log format.** `logging_config` builds a dictConfig rather than a
  `basicConfig`, for two reasons: uvicorn installs its own handlers with
  `propagate = False`, so a root-only format leaves the access lines in uvicorn's
  format and the output half-converted; and `basicConfig` is a no-op once any
  handler exists. `LOG_FORMAT=json` switches the same handler to one JSON object
  per line.

* **Sentry.** Inert unless `SENTRY_DSN` is set, and forced off under test. The
  scrubbing is not optional: this server handles candidate code, candidate email
  addresses and invite tokens, and an unscrubbed error report is the one place
  they would all leave the box at once — days after X03/X04 gave candidates an
  erasure guarantee that a third-party crash log would quietly break.

* **Metrics.** The render helpers turn numbers into Prometheus text exposition.
  Note what is *not* here: process-local counters. The platform's numbers are
  derived by SQL from rows it already stores (see `api.metrics`), because a
  counter in memory counts per worker — the same mistake `config` documents at
  length for `RATE_LIMIT_BACKEND`. The agent, which has no database, necessarily
  does the opposite.

Nothing here imports FastAPI: the maths and formatting are DB- and
framework-free so they unit-test without a server, matching `analytics.py`.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from . import config

if TYPE_CHECKING:  # the SDK is imported lazily; its types are needed at check time
    from sentry_sdk.types import Event

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"

# The id is accepted from outside and echoed into logs, a response header and an
# outbound request, so it has to be too dull to be a log-injection or a
# header-smuggling vector. Same shape as the agent's `job_id` for consistency.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# "-" rather than None so a plain-format record always has something to print and
# a JSON one always has the key. Outside a request (the reaper, the retention
# sweep, a CLI import) there genuinely is no id, and that is worth seeing.
NO_REQUEST_ID = "-"

_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def new_request_id() -> str:
    """A fresh correlation id. Short: it is read off a log line by a human."""
    return uuid.uuid4().hex[:16]


def adopt_request_id(inbound: str | None) -> str:
    """Make `inbound` the current request id when it is well formed, else mint one.

    A malformed id is replaced rather than rejected — a correlation id is a
    debugging aid, and failing a candidate's submission over a header a proxy
    mangled would be a spectacularly bad trade.
    """
    request_id = inbound if inbound and _ID_PATTERN.match(inbound) else new_request_id()
    _REQUEST_ID.set(request_id)
    return request_id


def current_request_id() -> str:
    """The id of the request being served, or `NO_REQUEST_ID` outside one."""
    return _REQUEST_ID.get()


# --------------------------------------------------------------------------- #
# Logging                                                                       #
# --------------------------------------------------------------------------- #


class RequestIdFilter(logging.Filter):
    """Stamp every record with the current request id.

    A filter, not a `LoggerAdapter` or an `extra=` at each call site, because the
    records most worth correlating are the ones no call site of ours can reach:
    uvicorn's access lines, SQLAlchemy's warnings, a third-party traceback.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


# The invite token is a PATH parameter on every candidate route
# (/invite/{token}/...), and README calls it bearer-equivalent. A query string is
# not the only place a secret travels in a URL, so both the access log and the
# Sentry scrub go through one redactor rather than each solving half of it.
_TOKEN_IN_PATH = re.compile(r"(/invite/)[^/?]+")


def redact_url(url: str) -> str:
    """Strip the query string and mask the invite token in a URL or path.

    Correlation is what the request id is for now; a URL in a log line or a crash
    report does not need to carry a live credential to be useful.
    """
    path, separator, _query = url.partition("?")
    return _TOKEN_IN_PATH.sub(r"\1<redacted>", path) + ("?<redacted>" if separator else "")


class QueryStringFilter(logging.Filter):
    """Redact secrets from uvicorn's access lines unless LOG_PII is on.

    Two of them: the candidate's email in a query string (open item P08) and the
    invite token in the path of every candidate route. uvicorn logs the request
    line verbatim regardless of LOG_PII, and structured access logs are precisely
    what gets shipped to an aggregator — so X08 must not be the change that turns
    either leak machine-readable. This narrows P08; it does not close it, since
    the token still travels in the URL and so still reaches a proxy's logs and
    the browser's history.

    Coupled to uvicorn's access-log call, whose args are
    `(client_addr, method, full_path, http_version, status_code)`. A test pins
    that shape, because a silent failure here is a silent PII leak.
    """

    _PATH_ARG = 2

    def filter(self, record: logging.LogRecord) -> bool:
        if config.LOG_PII:
            return True
        args = record.args
        if not isinstance(args, tuple) or len(args) <= self._PATH_ARG:
            return True
        path = args[self._PATH_ARG]
        if not isinstance(path, str):
            return True
        redacted = list(args)
        redacted[self._PATH_ARG] = redact_url(path)
        record.args = tuple(redacted)
        return True


# Everything `logging` itself puts on a record. Anything else a call site passed
# via `extra=` is a structured field the caller wants in the JSON line.
_RECORD_BUILTINS = frozenset(
    """args asctime created exc_info exc_text filename funcName levelname levelno
    lineno message module msecs msg name pathname process processName
    relativeCreated stack_info taskName thread threadName""".split()
)

_PLAIN_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s]: %(message)s"


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for a log aggregator to ingest.

    Hand-rolled rather than a dependency: the shape is five fixed keys plus
    whatever `extra=` carried, and a formatter is the one place in a server that
    must never raise — hence `default=str` over anything unexpected.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", NO_REQUEST_ID),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RECORD_BUILTINS and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def logging_config(level: str, *, json_format: bool) -> dict[str, Any]:
    """A `logging.config.dictConfig` dict for the whole server process.

    Hands uvicorn's loggers to the root handler so *all* output shares one
    format — uvicorn sets `propagate = False` on its own, so without the explicit
    entries below the access lines would keep uvicorn's format while the
    package's lines changed. The access logger keeps a handler of its own only
    because it needs the extra query-string redaction.
    """
    formatter = "json" if json_format else "plain"
    return {
        "version": 1,
        # Loggers already created at import time (every module-level getLogger in
        # this package) must keep working.
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": RequestIdFilter},
            "query_string": {"()": QueryStringFilter},
        },
        "formatters": {
            "plain": {"format": _PLAIN_FORMAT},
            "json": {"()": JsonFormatter},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": formatter,
                "filters": ["request_id"],
            },
            "access": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": formatter,
                "filters": ["request_id", "query_string"],
            },
        },
        "root": {"level": level, "handlers": ["console"]},
        "loggers": {
            "uvicorn": {"handlers": [], "propagate": True},
            "uvicorn.error": {"handlers": [], "propagate": True},
            "uvicorn.access": {"handlers": ["access"], "propagate": False, "level": level},
        },
    }


# --------------------------------------------------------------------------- #
# Error reporting                                                               #
# --------------------------------------------------------------------------- #

# Headers safe to attach to an error report. Everything else is dropped, because
# the interesting ones are all credentials: Authorization, Cookie, X-Assess-Token.
_SAFE_HEADERS = frozenset({"host", "user-agent", "content-type", "content-length"})


def _scrub_event(event: Event, _hint: dict[str, Any]) -> Event:
    """Strip candidate data out of an error report before it leaves the box.

    `send_default_pii=False` already stops Sentry volunteering the client IP and
    cookies; this removes what it would still send because *we* put it in the
    request: the submitted source, the candidate's email in a query string, and
    the bearer tokens in the headers.
    """
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                name: value for name, value in headers.items() if name.lower() in _SAFE_HEADERS
            }
        url = request.get("url")
        if isinstance(url, str):
            # The query string AND the invite token in the path. Without this an
            # ordinary 500 on a candidate route hands a third party a live
            # bearer-equivalent credential — one that erasure cannot reach,
            # because erase_candidate amends the invite rather than deleting it.
            request["url"] = redact_url(url)
    event.pop("user", None)
    return event


def init_sentry() -> bool:
    """Start Sentry when a DSN is configured. Returns whether it did.

    Off under `PLATFORM_TESTING` for the same reason SMTP and billing are: a
    developer's real `.env` is loaded at import, and a test run must not ship
    events from it.
    """
    if config.TESTING or not config.SENTRY_DSN:
        return False
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - the dependency is declared
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; not reporting errors.")
        return False
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENVIRONMENT,
        release=config.SENTRY_RELEASE,
        # Tracing is off by default: it samples request bodies and spans on every
        # route, which is both the expensive part of Sentry's pricing and the
        # part with the largest PII surface. An operator turns it on knowingly.
        traces_sample_rate=config.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        max_request_body_size="never",
        # Candidate source code sits in a local variable on the submission path.
        include_local_variables=False,
        before_send=_scrub_event,
    )
    global _sentry_started
    _sentry_started = True
    return True


# Set by `init_sentry`, read by `tag_request`. A module flag rather than asking
# the SDK whether it is running: the SDK is only imported when a DSN exists, and
# `tag_request` runs on every single request.
_sentry_started = False


def tag_request(request_id: str) -> None:
    """Attach the request id to any Sentry event raised while serving this request.

    Without it a crash report and the log lines around it share no key, which is
    most of the point of having both. A no-op when Sentry was never started.
    """
    if not _sentry_started:
        return
    import sentry_sdk

    sentry_sdk.set_tag("request_id", request_id)


# --------------------------------------------------------------------------- #
# Prometheus text exposition                                                    #
# --------------------------------------------------------------------------- #

Labels = Mapping[str, str]
Samples = Sequence[tuple[Labels, float]]

# Seconds. Spread for a grade: a fast deterministic run finishes in single
# digits, one waiting on the LLM judge takes tens, and anything past five
# minutes has effectively failed.
LATENCY_BUCKETS: tuple[float, ...] = (1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)


def _escape(value: str) -> str:
    """Escape a label value per the Prometheus text format."""
    return value.replace("\\", r"\\").replace('"', r"\"").replace("\n", r"\n")


def _labels(labels: Labels) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in sorted(labels.items()))
    return "{" + inner + "}"


def _number(value: float) -> str:
    """Render a value the way Prometheus expects: integers without a `.0` tail."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _family(name: str, help_text: str, kind: str, lines: Iterable[str]) -> str:
    header = f"# HELP {name} {help_text}\n# TYPE {name} {kind}\n"
    return header + "".join(lines)


def metric(name: str, help_text: str, kind: str, samples: Samples) -> str:
    """One metric family — a `gauge` or a `counter` — as text exposition."""
    return _family(
        name,
        help_text,
        kind,
        (f"{name}{_labels(labels)} {_number(value)}\n" for labels, value in samples),
    )


def histogram(
    name: str,
    help_text: str,
    values: Sequence[float],
    buckets: Sequence[float] = LATENCY_BUCKETS,
) -> str:
    """A histogram family over already-observed `values`.

    Buckets are cumulative, as the format requires. A histogram rather than a
    mean because grade latency is bimodal — a deterministic run and a run waiting
    on the LLM judge are different populations, and their average describes
    neither.
    """
    lines = []
    for bound in buckets:
        count = sum(1 for value in values if value <= bound)
        lines.append(f'{name}_bucket{{le="{_number(bound)}"}} {count}\n')
    lines.append(f'{name}_bucket{{le="+Inf"}} {len(values)}\n')
    lines.append(f"{name}_sum {_number(sum(values))}\n")
    lines.append(f"{name}_count {len(values)}\n")
    return _family(name, help_text, "histogram", lines)


def render(families: Iterable[str]) -> str:
    """Join metric families into a scrape response."""
    return "".join(families)
