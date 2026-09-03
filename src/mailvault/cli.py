"""MailVault CLI."""

import click
from pathlib import Path

from .db import get_db, init_db, search, stats, get_last_sync, insert_message
from .sync import (
    list_accounts,
    get_envelopes,
    get_raw_message,
    parse_raw_message,
    HimalayaError,
)


@click.group()
def main():
    """MailVault — local email archive with full-text search."""
    pass


@main.command()
def init():
    """Initialize the database."""
    conn = get_db()
    init_db(conn)
    click.echo("Database initialized at ~/.local/share/mailvault/mailvault.db")


@main.command()
@click.option("--account", "-a", help="Sync specific account (default: all)")
@click.option("--full", is_flag=True, help="Full sync (ignore last sync date)")
@click.option("--limit", "-l", default=50, help="Max messages to sync per account")
def sync(account, full, limit):
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
        try:
            envelopes = get_envelopes(account=acc_name)
        except HimalayaError as e:
            click.echo(f"  Error: {e}", err=True)
            continue

        # Limit to most recent N
        envelopes = envelopes[:limit]

        new_count = 0
        for env in envelopes:
            env_id = env.get("id", "")
            if not env_id:
                continue

            # Check if already synced
            existing = conn.execute(
                "SELECT id FROM messages WHERE account = ? AND envelope_id = ?",
                (acc_name, env_id),
            ).fetchone()
            if existing and not full:
                # Update seen status
                flags = env.get("flags", [])
                seen = 1 if any(f.get("iana") == "seen" for f in flags) else 0
                conn.execute(
                    "UPDATE messages SET seen = ? WHERE account = ? AND envelope_id = ?",
                    (seen, acc_name, env_id),
                )
                continue

            try:
                raw = get_raw_message(env_id, account=acc_name)
                parsed = parse_raw_message(raw)

                # Determine seen status from flags
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
                new_count += 1
                click.echo(f"  [{new_count}/{len(envelopes)}] {parsed['subject'][:60]}")
            except HimalayaError as e:
                click.echo(f"  Error fetching {env_id}: {e}", err=True)
                continue

        conn.commit()
        click.echo(f"  {acc_name}: {new_count} new messages synced ({len(envelopes)} envelopes checked)")


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
def accounts():
    """List configured himalaya accounts."""
    accs = list_accounts()
    for acc in accs:
        click.echo(f"{acc.get('name', 'default')} — {acc.get('email', '')}")
