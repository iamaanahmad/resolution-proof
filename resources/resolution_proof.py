#!/usr/bin/env python3
"""Evaluate a public JSON source against one explicit market resolution rule."""

from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timezone


MAX_RESPONSE_BYTES = 1_048_576
USER_AGENT = "ResolutionProof/0.1 (+https://getrote.dev/playoffs)"


class SourceBlocked(Exception):
    """The named source could not be used safely or reliably."""


def normalized_scalar(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)) and not isinstance(value, complex):
        return str(value).strip().casefold()
    return None


def validate_public_https(url: str) -> urllib.parse.SplitResult:
    parsed = validate_https_shape(url)

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise SourceBlocked(f"The source host did not resolve: {error}.") from error

    if not addresses:
        raise SourceBlocked("The source host did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise SourceBlocked("The source host resolved to a non-public address.")
    return parsed


def validate_https_shape(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise SourceBlocked("The source URL must use HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise SourceBlocked("The source URL has an invalid host or embedded credentials.")
    if parsed.port not in (None, 443):
        raise SourceBlocked("The source URL must use the standard HTTPS port.")

    return parsed


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        validate_public_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_json(source_url: str, fixture_path: str) -> Any:
    if source_url == "fixture://ready":
        with open(fixture_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    validate_public_https(source_url)
    request = urllib.request.Request(
        source_url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    opener = urllib.request.build_opener(SafeRedirectHandler())
    try:
        with opener.open(request, timeout=10) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"application/json", "application/geo+json", "text/json"}:
                raise SourceBlocked(f"The source returned {content_type}, not JSON.")
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise SourceBlocked("The source response exceeded the 1 MiB safety limit.")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        raise SourceBlocked(f"The source request failed: {error}.") from error

    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceBlocked(f"The source returned malformed JSON: {error}.") from error


def resolve_pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    if pointer == "":
        return True, document
    if not pointer.startswith("/"):
        raise ValueError("json_pointer must be empty or start with '/'.")

    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit():
                return False, None
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def safe_receipt_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value.strip() in {"", "."}:
        raise ValueError("receipt_path must be a safe workspace-relative file path.")
    return path


def write_receipt(path_value: str, payload: dict[str, Any]) -> str:
    path = safe_receipt_path(path_value)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return str(path)


def validate_inputs(
    market_question: str,
    resolution_rule: str,
    source_url: str,
    json_pointer: str,
    expected_value: str,
    pending_values: str,
) -> dict[str, Any]:
    if not market_question.strip():
        raise ValueError("market_question must not be empty.")
    if not resolution_rule.strip():
        raise ValueError("resolution_rule must not be empty.")
    if not expected_value.strip():
        raise ValueError("expected_value must not be empty.")
    if json_pointer and not json_pointer.startswith("/"):
        raise ValueError("json_pointer must be empty or start with '/'.")
    if source_url != "fixture://ready":
        validate_https_shape(source_url)
    if not {item.strip() for item in pending_values.split(",") if item.strip()}:
        raise ValueError("pending_values must name at least one pending marker.")
    return {
        "valid": True,
        "market_question": market_question,
        "source_url": source_url,
        "json_pointer": json_pointer,
    }


def fetch_evidence(source_url: str, fixture_path: str) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    try:
        document = fetch_json(source_url, fixture_path)
    except SourceBlocked as error:
        return {
            "source_url": source_url,
            "observed_at": observed_at,
            "canonical_json_sha256": None,
            "fetch_error": str(error),
        }
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "source_url": source_url,
        "observed_at": observed_at,
        "canonical_json_sha256": hashlib.sha256(canonical).hexdigest(),
        "document": document,
    }


def evaluate(
    market_question: str,
    resolution_rule: str,
    source_url: str,
    json_pointer: str,
    expected_value: str,
    pending_values: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "market_question": market_question,
        "resolution_rule": resolution_rule,
        "source_url": source_url,
        "json_pointer": json_pointer,
        "expected_value": expected_value,
        "observed_at": evidence.get("observed_at"),
        "canonical_json_sha256": evidence.get("canonical_json_sha256"),
    }

    if evidence.get("fetch_error"):
        return {
            **base,
            "status": "BLOCKED",
            "reason": str(evidence["fetch_error"]),
        }

    try:
        document = evidence["document"]
        found, actual = resolve_pointer(document, json_pointer)
    except (KeyError, ValueError) as error:
        return {**base, "status": "BLOCKED", "reason": str(error)}

    base["actual_value"] = actual
    if not found or actual is None:
        return {
            **base,
            "status": "WAIT",
            "reason": "The supplied source does not publish a decisive value yet.",
        }
    if isinstance(actual, (dict, list)):
        return {
            **base,
            "status": "AMBIGUOUS",
            "reason": "The JSON Pointer selected a collection, not one decisive scalar value.",
        }

    actual_normalized = normalized_scalar(actual)
    expected_normalized = expected_value.strip().casefold()
    pending = {item.strip().casefold() for item in pending_values.split(",") if item.strip()}
    if actual_normalized in pending or actual_normalized == "":
        return {
            **base,
            "status": "WAIT",
            "reason": "The supplied source still reports a pending value.",
        }
    if actual_normalized == expected_normalized:
        return {
            **base,
            "status": "READY",
            "condition_met": True,
            "reason": "The supplied source publishes a decisive scalar that matches the expected value.",
        }
    return {
        **base,
        "status": "READY",
        "condition_met": False,
        "reason": "The supplied source publishes a decisive scalar that does not match the expected value.",
    }


def verify_result(result: dict[str, Any]) -> dict[str, Any]:
    required = {
        "market_question",
        "resolution_rule",
        "source_url",
        "json_pointer",
        "expected_value",
        "observed_at",
        "canonical_json_sha256",
        "status",
        "reason",
    }
    missing = sorted(required - result.keys())
    if missing:
        raise ValueError(f"result is missing fields: {', '.join(missing)}")
    if result["status"] not in {"READY", "WAIT", "AMBIGUOUS", "BLOCKED"}:
        raise ValueError("result has an invalid status.")
    digest = result["canonical_json_sha256"]
    if result["status"] != "BLOCKED" and (
        not isinstance(digest, str) or len(digest) != 64
    ):
        raise ValueError("result has an invalid source digest.")
    if result["status"] == "READY" and not isinstance(result.get("condition_met"), bool):
        raise ValueError("READY results must include a boolean condition_met value.")
    return {**result, "verified": True}


def parse_object(value: str, label: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return parsed


def main(argv: list[str]) -> int:
    try:
        command = argv[1]
        if command == "validate" and len(argv) == 8:
            result = validate_inputs(*argv[2:])
        elif command == "fetch" and len(argv) == 4:
            result = fetch_evidence(argv[2], argv[3])
        elif command == "evaluate" and len(argv) == 9:
            result = evaluate(*argv[2:8], parse_object(argv[8], "evidence"))
        elif command == "verify" and len(argv) == 3:
            result = verify_result(parse_object(argv[2], "result"))
        elif command == "write" and len(argv) == 5:
            result = parse_object(argv[2], "result")
            if argv[3] != "write":
                raise ValueError("receipt must be 'write' when the receipt step runs")
            result["receipt_path"] = write_receipt(argv[4], result)
        else:
            raise ValueError("unknown command or invalid argument count")
    except (IndexError, OSError, SourceBlocked, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
