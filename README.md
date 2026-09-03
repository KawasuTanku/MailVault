# MailVault

Local email archive with full-text search. Syncs multiple IMAP accounts
(via himalaya) into a single SQLite database. One file to back up,
instant search across all accounts.

## Features

- Multi-account IMAP sync (Gmail, Outlook, etc.)
- Full-text search via SQLite FTS5
- Raw RFC 5322 storage (headers + body + MIME)
- Single-file backup
- CLI for sync, search, and stats

## Setup

```bash
pip install -e .
mailvault init
mailvault sync --account gmail
mailvault search "invoice August"
```

## Architecture

```
IMAP accounts ──► himalaya CLI ──► MailVault ──► SQLite + FTS5
```
