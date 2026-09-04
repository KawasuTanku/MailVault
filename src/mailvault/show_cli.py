"""Message output commands for MailVault."""

import click
from .db import get_db
from .header_analysis import analyze_headers, format_source_report


@click.command()
@click.argument("message_id", type=int)
@click.option("--raw", is_flag=True, help="Output raw RFC 5322 message")
@click.option("--headers", is_flag=True, help="Output only headers")
@click.option("--body", is_flag=True, help="Output only body")
@click.option("--analyze", "-a", is_flag=True, help="Analyze headers for spam source")
def show(message_id, raw, headers, body, analyze):
    """Output a message to the terminal."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM messages WHERE id = ?", (message_id,)
    ).fetchone()
    
    if not row:
        click.echo(f"Message {message_id} not found.", err=True)
        return
    
    if analyze:
        raw_data = row["raw_rfc5322"]
        if raw_data:
            if isinstance(raw_data, str):
                raw_data = raw_data.encode("utf-8")
            source = analyze_headers(raw_data)
            click.echo(format_source_report(source))
        else:
            click.echo("No raw content available.", err=True)
        return
    
    if raw:
        raw_data = row["raw_rfc5322"]
        if raw_data:
            if isinstance(raw_data, bytes):
                click.echo(raw_data.decode("utf-8", errors="replace"))
            else:
                click.echo(raw_data)
        else:
            click.echo("No raw content available.", err=True)
        return
    
    # Default: show formatted message
    subject = row['subject'] or ''
    from_name = row['from_name'] or ''
    from_addr = row['from_addr'] or ''
    to_name = row['to_name'] or ''
    to_addr = row['to_addr'] or ''
    date = row['date'] or ''
    account = row['account'] or ''
    body_text = row['body_text'] or '(no body)'
    body_html = row['body_html'] or ''
    
    # Prefer HTML body, convert to text
    if body_html:
        try:
            import html2text
            h = html2text.HTML2Text()
            h.body_width = 0
            body_text = h.handle(body_html)
        except ImportError:
            pass
    
    if headers:
        click.echo(f"Subject: {subject}")
        click.echo(f"From: {from_name} <{from_addr}>")
        click.echo(f"To: {to_name} <{to_addr}>")
        click.echo(f"Date: {date}")
        click.echo(f"Account: {account}")
        return
    
    if body:
        click.echo(body_text)
        return
    
    # Full formatted output
    click.echo(f"ID: {row['id']}")
    click.echo(f"Subject: {subject}")
    click.echo(f"From: {from_name} <{from_addr}>")
    click.echo(f"To: {to_name} <{to_addr}>")
    click.echo(f"Date: {date}")
    click.echo(f"Account: {account}")
    click.echo()
    click.echo(body_text)
