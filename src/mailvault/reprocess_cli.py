"""Message reprocessing for MailVault."""

import click
from .db import get_db, insert_message


@click.command()
@click.option("--account", "-a", help="Only reprocess messages from specific account")
@click.option("--dry-run", is_flag=True, help="Show what would be updated without saving")
@click.option("--verbose", "-v", is_flag=True, help="Show progress")
def reprocess(account, dry_run, verbose):
    """Re-process raw RFC 5322 to extract body content.
    
    This re-parses existing messages to populate body_text and body_html
    columns without re-fetching from the server. Useful for messages
    synced before HTML body extraction was added.
    """
    conn = get_db()
    
    # Build query
    sql = "SELECT id, account, raw_rfc5322 FROM messages WHERE raw_rfc5322 IS NOT NULL"
    params = []
    if account:
        sql += " AND account = ?"
        params.append(account)
    
    rows = conn.execute(sql, params).fetchall()
    
    if not rows:
        click.echo("No messages to reprocess.")
        return
    
    click.echo(f"Processing {len(rows)} messages...")
    
    updated = 0
    skipped = 0
    
    for row in rows:
        if verbose and updated % 100 == 0 and updated > 0:
            click.echo(f"  Processed {updated}...")
        
        msg_id = row["id"]
        raw = row["raw_rfc5322"]
        
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        
        # Re-parse the raw message
        from .sync import parse_raw_message
        parsed = parse_raw_message(raw)
        
        # Update the database
        if not dry_run:
            conn.execute("""
                UPDATE messages 
                SET body_text = ?, body_html = ?
                WHERE id = ?
            """, (parsed["body_text"], parsed["body_html"] or None, msg_id))
            updated += 1
        else:
            # Check if update would change anything
            current = conn.execute(
                "SELECT body_text, body_html FROM messages WHERE id = ?",
                (msg_id,)
            ).fetchone()
            if (current["body_text"] or "") != (parsed["body_text"] or "") or \
               (current["body_html"] or "") != (parsed["body_html"] or ""):
                updated += 1
                click.echo(f"  Would update message {msg_id}: body_text={len(parsed['body_text'] or '')} chars, body_html={len(parsed['body_html'] or '')} chars")
            else:
                skipped += 1
    
    if not dry_run:
        conn.commit()
    
    if dry_run:
        click.echo(f"\nWould update {updated} messages. Use without --dry-run to apply.")
    else:
        click.echo(f"Updated {updated} messages.")
