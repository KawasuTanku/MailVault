"""Himalaya sync backend for MailVault."""

import json
import subprocess
from email import message_from_string
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Optional


class HimalayaError(Exception):
    """Raised when himalaya CLI fails."""


def run_himalaya(args: list, account: Optional[str] = None) -> str:
    """Run himalaya CLI and return stdout."""
    cmd = ["himalaya"]
    if account:
        cmd += ["--account", account]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HimalayaError(f"himalaya failed: {result.stderr.strip()}")
    return result.stdout


def run_himalaya_json(args: list, account: Optional[str] = None) -> dict | list:
    """Run himalaya CLI with JSON output."""
    cmd = ["himalaya", "--json"]
    if account:
        cmd += ["--account", account]
    cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HimalayaError(f"himalaya failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def list_accounts() -> list:
    """Get list of configured accounts."""
    data = run_himalaya_json(["account", "list"])
    return data.get("accounts", [])


def get_envelopes(account: Optional[str] = None, page: int = 1, page_size: int = 100) -> tuple:
    """Get envelope list from himalaya with pagination.
    
    Returns (envelopes, total_count) where total_count may be None
    if the backend doesn't report it.
    """
    data = run_himalaya_json(
        ["envelope", "list", "--page", str(page), "--page-size", str(page_size)],
        account=account,
    )
    envelopes = data.get("envelopes", [])
    total = data.get("total")
    return envelopes, total


def get_raw_message(envelope_id: str, account: Optional[str] = None) -> str:
    """Get raw RFC 5322 message."""
    return run_himalaya(["message", "read", envelope_id, "--raw"], account=account)


def decode_mime_header(value: str) -> str:
    """Decode MIME encoded-word headers."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def parse_raw_message(raw: str) -> dict:
    """Parse raw RFC 5322 into structured fields."""
    msg = message_from_string(raw)
    from_name, from_addr = parseaddr(msg.get("From", ""))
    to_name, to_addr = parseaddr(msg.get("To", ""))
    date_str = msg.get("Date", "")
    try:
        date_parsed = parsedate_to_datetime(date_str).isoformat() if date_str else None
    except (ValueError, TypeError):
        date_parsed = date_str

    # Extract plain text body
    body_text = ""
    body_html = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and not part.get_filename() and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif content_type == "text/html" and not part.get_filename() and not body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                body_html = body
            else:
                body_text = body

    # Build headers dict
    headers = {}
    for key, value in msg.items():
        headers[key] = decode_mime_header(value)

    return {
        "message_id": msg.get("Message-ID", ""),
        "date": date_parsed,
        "from_addr": from_addr,
        "from_name": decode_mime_header(from_name),
        "to_addr": to_addr,
        "to_name": decode_mime_header(to_name),
        "subject": decode_mime_header(msg.get("Subject", "")),
        "body_text": body_text,
        "body_html": body_html,
        "headers": headers,
    }
