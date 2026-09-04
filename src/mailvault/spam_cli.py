"""Spam reporting CLI for MailVault."""

import click
from .spam import report_spam_using_himalaya, PROVIDERS, load_smtp_config
from .header_analysis import analyze_headers, format_source_report
from .db import get_db


@click.group()
def spam():
    """Spam reporting commands."""
    pass


@spam.command()
@click.option("--account", "-a", help="Himalaya account to send from")
@click.option("--from-addr", help="From address for the report (auto-detected if not set)")
@click.option(
    "--provider",
    type=click.Choice(list(PROVIDERS.keys())),
    default="spamhaus",
    help="Spam reporting provider",
)
@click.option("--custom", help="Custom reporting address (overrides --provider)")
@click.option("--analyze", is_flag=True, help="Analyze headers before reporting")
@click.argument("message_id", type=int)
def report(account, from_addr, provider, custom, analyze, message_id):
    """Report a message as spam."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM messages WHERE id = ?", (message_id,)
    ).fetchone()
    
    if not row:
        click.echo(f"Message {message_id} not found.", err=True)
        return
    
    raw = row["raw_rfc5322"]
    if not raw:
        click.echo(f"Message {message_id} has no raw content.", err=True)
        return
    
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    
    # Analyze headers if requested
    if analyze:
        click.echo("Analyzing headers...")
        source = analyze_headers(raw)
        click.echo(format_source_report(source))
        click.echo()
    
    if custom:
        recipient = custom
    else:
        provider_info = PROVIDERS.get(provider)
        if not provider_info:
            click.echo(f"Unknown provider: {provider}", err=True)
            return
        recipient = provider_info["address"]
    
    if not from_addr:
        smtp_config = load_smtp_config(account)
        from_addr = smtp_config["from_addr"] if smtp_config else "reporter@localhost"
    
    click.echo(f"Reporting message {message_id} to {recipient}...")
    
    success = report_spam_using_himalaya(
        raw_rfc5322=raw,
        recipient=recipient,
        from_addr=from_addr,
        account=account,
        subject=row["subject"] or "Spam report",
        message_id=row["message_id"] or "",
    )
    
    if success:
        click.echo("Report sent successfully.")
    else:
        click.echo("Failed to send report.", err=True)


@spam.command()
@click.argument("message_id", type=int)
def analyze(message_id):
    """Analyze email headers to detect spam source."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM messages WHERE id = ?", (message_id,)
    ).fetchone()
    
    if not row:
        click.echo(f"Message {message_id} not found.", err=True)
        return
    
    raw = row["raw_rfc5322"]
    if not raw:
        click.echo(f"Message {message_id} has no raw content.", err=True)
        return
    
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    
    source = analyze_headers(raw)
    click.echo(format_source_report(source))


@spam.command()
def list():
    """List available spam reporting providers."""
    click.echo("Available spam reporting providers:")
    click.echo()
    for key, info in PROVIDERS.items():
        click.echo(f"  {info['name']:15} {info['address']:30} {info['description']}")
