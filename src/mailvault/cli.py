"""MailVault CLI."""

import click
from pathlib import Path

from .db import get_db, init_db, search, stats, insert_message, is_message_id_synced, get_sync_state, update_sync_state
from .sync import (
    list_accounts,
    get_envelopes,
    get_raw_message,
    parse_raw_message,
    HimalayaError,
)
from .io import export_all, import_from_jsonl
from .tui import run_tui
from .spam_cli import spam


@click.group()
def main():
    """MailVault — local email archive with full-text search."""
    pass


main.add_command(spam)


@main.command()
def init():
    """Initialize the database."""
    conn = get_db()
    init_db(conn)
    click.echo("Database initialized at ~/.local/share/mailvault/mailvault.db")


@main.command()
@click.option("--account", "-a", help="Sync specific account (default: all)")
@click.option("--full", is_flag=True, help="Full sync (re-fetch all pages)")
@click.option("--page-size", default=100, help="Page size for envelope fetching")
@click.option("--max-pages", default=10, help="Max pages to sync per run")
def sync(account, full, page_size, max_pages):
    """Sync emails from himalaya into MailVault."""
    conn = get_db()
    init_db(conn)

    accounts = list_accounts()
    if not accounts:
        click.echo("No himalaya accounts configured.", err=True)
        return

    for acc in accounts:
        acc_name = acc.get("name", "default")
        if account and acc_name != account:
            continue

        click.echo(f"Syncing {acc_name}...")
        sync_account(conn, acc_name, full=full, page_size=page_size, max_pages=max_pages)


def sync_account(conn, acc_name: str, full: bool = False, page_size: int = 100, max_pages: int = 10) -> None:
    """Sync a single account with pagination and Message-ID dedup."""
    state = get_sync_state(conn, acc_name)
    last_page = state.get("last_page", 0) if state else 0

    page = 1 if full else max(1, last_page + 1)
    total_new = 0
    total_skipped = 0
    total_pages = 0

    while page <= max_pages:
        try:
            envelopes, _ = get_envelopes(account=acc_name, page=page, page_size=page_size)
        except HimalayaError as e:
            click.echo(f"  Error fetching page {page}: {e}", err=True)
            break

        if not envelopes:
            break

        total_pages = page

        for env in envelopes:
            env_id = env.get("id", "")
            if not env_id:
                continue

            # Get Message-ID for dedup
            msg_id = env.get("message-id", "")

            # Check by Message-ID (globally unique)
            if msg_id and is_message_id_synced(conn, msg_id):
                total_skipped += 1
                continue

            # Also check by envelope_id (fast path)
            existing = conn.execute(
                "SELECT id FROM messages WHERE account = ? AND envelope_id = ?",
                (acc_name, env_id),
            ).fetchone()
            if existing:
                # Update seen status
                flags = env.get("flags", [])
                seen = 1 if any(f.get("iana") == "seen" for f in flags) else 0
                conn.execute(
                    "UPDATE messages SET seen = ? WHERE account = ? AND envelope_id = ?",
                    (seen, acc_name, env_id),
                )
                total_skipped += 1
                continue

            try:
                raw = get_raw_message(env_id, account=acc_name)
                parsed = parse_raw_message(raw)

                flags = env.get("flags", [])
                seen = 1 if any(f.get("iana") == "seen" for f in flags) else 0

                msg = {
                    "account": acc_name,
                    "envelope_id": env_id,
                    "message_id": parsed["message_id"],
                    "date": parsed["date"],
                    "from_addr": parsed["from_addr"],
                    "from_name": parsed["from_name"],
                    "to_addr": parsed["to_addr"],
                    "to_name": parsed["to_name"],
                    "subject": parsed["subject"],
                    "body_text": parsed["body_text"],
                    "headers_json": parsed["headers"],
                    "raw_rfc5322": raw,
                    "seen": seen,
                }
                insert_message(conn, msg)
                total_new += 1
                click.echo(f"  [{total_new}] {parsed['subject'][:60]}")
            except HimalayaError as e:
                click.echo(f"  Error fetching {env_id}: {e}", err=True)
                continue

        conn.commit()
        click.echo(f"  Page {page}: {total_new} new, {total_skipped} skipped")

        page += 1

    update_sync_state(conn, acc_name, total_pages, total_new, total_skipped)
    conn.commit()
    click.echo(f"  {acc_name}: {total_new} new, {total_skipped} skipped (pages: {total_pages})")


@main.command()
@click.argument("query")
@click.option("--account", "-a", help="Filter by account")
@click.option("--limit", "-n", default=20, help="Max results")
def search_cmd(query, account, limit):
    """Search emails."""
    conn = get_db()
    results = search(conn, query, account=account, limit=limit)

    if not results:
        click.echo("No results found.")
        return

    for r in results:
        seen = " " if r["seen"] else "*"
        click.echo(f"{seen} [{r['account']}] {r['subject']}")
        click.echo(f"  From: {r['from_name'] or r['from_addr']}")
        click.echo(f"  Date: {r['date']}")
        if r.get("snip"):
            click.echo(f"  {r['snip']}")
        click.echo()


@main.command()
def stats_cmd():
    """Show database stats."""
    conn = get_db()
    s = stats(conn)
    click.echo(f"Total messages: {s['total']}")
    for acc, count in s.get("accounts", {}).items():
        click.echo(f"  {acc}: {count}")


@main.command()
def sync_state():
    """Show sync state for all accounts."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM sync_state ORDER BY account").fetchall()
    if not rows:
        click.echo("No sync state found.")
        return
    for r in rows:
        click.echo(f"{r['account']}: {r['total_synced']} synced, {r['total_skipped']} skipped, last sync: {r['last_sync']}")


@main.command()
def accounts():
    """List configured himalaya accounts."""
    accs = list_accounts()
    for acc in accs:
        click.echo(f"{acc.get('name', 'default')} — {acc.get('email', '')}")


@main.command()
def tui():
    """Launch the TUI."""
    run_tui()


@main.command()
@click.argument("output", required=False, type=click.Path())
def export(output):
    """Export all messages to JSONL. Defaults to stdout."""
    out_path = Path(output) if output else None
    count = export_all(out_path)
    click.echo(f"Exported {count} messages.")


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
def import_(input_file):
    """Import messages from JSONL file."""
    count = import_from_jsonl(Path(input_file))
    click.echo(f"Imported {count} messages.")
