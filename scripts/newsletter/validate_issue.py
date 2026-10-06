"""Validate offline bilingual newsletter JSON; no network or third-party packages."""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _url_key(value):
    """Accept absolute HTTPS URLs; compare host case/default port/fragment neutrally."""
    if not _text(value) or re.search(r"\s|[\x00-\x1f\x7f\\]", value):
        raise ValueError("must be an absolute HTTPS URL without whitespace")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("must be an absolute HTTPS URL without credentials")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
        raise ValueError("must have a valid DNS hostname")
    port = parts.port
    authority = host if port in (None, 443) else f"{host}:{port}"
    return urlunsplit(("https", authority, parts.path or "/", parts.query, ""))


def validate_issue(issue):
    """Return all discovered field-level errors, without modifying the input."""
    errors = []
    if not isinstance(issue, dict):
        return ["issue: must be an object"]
    if type(issue.get("schema_version")) is not int or issue["schema_version"] != 1:
        errors.append("schema_version: must be integer 1")
    issue_date = issue.get("date")
    try:
        if not isinstance(issue_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", issue_date):
            raise ValueError()
        date.fromisoformat(issue_date)
    except ValueError:
        errors.append("date: must be a real calendar date in YYYY-MM-DD format")
    if type(issue.get("synthetic")) is not bool:
        errors.append("synthetic: must be a boolean marking demonstration data")
    items = issue.get("items")
    if not isinstance(items, list):
        return errors + ["items: must be an array containing exactly 10 items"]
    if len(items) != 10:
        errors.append("items: must contain exactly 10 items")
    ids, urls = set(), set()
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item_id):
            errors.append(f"{prefix}.id: must be a lowercase ASCII slug of 1 to 64 characters")
        elif item_id in ids:
            errors.append(f"{prefix}.id: duplicate item id {item_id!r}")
        else:
            ids.add(item_id)
        for locale in ("zh-TW", "en"):
            translation = item.get(locale)
            if not isinstance(translation, dict):
                errors.append(f"{prefix}.{locale}: must be an object")
                continue
            for field in ("title", "summary"):
                if not _text(translation.get(field)):
                    errors.append(f"{prefix}.{locale}.{field}: must be nonempty text")
        try:
            key = _url_key(item.get("source_url"))
            if key in urls:
                errors.append(f"{prefix}.source_url: duplicate source URL")
            urls.add(key)
        except (ValueError, UnicodeError):
            errors.append(f"{prefix}.source_url: must be a valid absolute HTTPS URL without credentials")
    return errors


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue", type=Path, help="UTF-8 JSON issue file")
    args = parser.parse_args(argv)
    try:
        issue = json.loads(args.issue.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"INVALID: cannot read issue: {exc}", file=sys.stderr)
        return 1
    errors = validate_issue(issue)
    if errors:
        print("INVALID:\n" + "\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    label = "synthetic fixture" if issue["synthetic"] else "issue"
    print(f"VALID: {issue['date']}, 10 bilingual items ({label})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
