"""Import EML files into MailVault."""

import hashlib
import os
from pathlib import Path
from typing import Optional

import click

from .db import get_db, init_db, insert_message, is_message_id_synced
from .sync import parse_raw_message


def generate_envelope_id(message_id: str, file_path: str) -> str:
    """Generate a deterministic envelope_id for an EML file.
    
    Uses the file path and message_id to create a unique identifier
    that is stable across re-imports of the same file.
    """
    hash_input = f"{file_path}:{message_id}"
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]


def import_eml_file(file_path: Path, account: str, conn, dry_run: bool = False) -> tuple:
    """Import a single EML file. Returns (success, message_id or error)."""
    try:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return (False, str(e))
    
    parsed = parse_raw_message(raw)
    message_id = parsed.get("message_id", "")
    
    if not message_id:
        # Generate a synthetic Message-ID if missing
        message_id = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    
    # Check for duplicates
    if is_message_id_synced(conn, message_id):
        return (False, f"already synced: {message_id}")
    
    envelope_id = generate_envelope_id(message_id, str(file_path))
    
    # Also check envelope_id (in case same file is imported twice)
    existing = conn.execute(
        "SELECT id FROM messages WHERE envelope_id = ?", (envelope_id,)
    ).fetchone()
    if existing:
        return (False, f"already synced: {envelope_id}")
    
    if dry_run:
        return (True, f"[dry-run] {file_path.name}: {parsed.get('subject', '(no subject)')}")
    
    msg = {
        "account": account,
        "envelope_id": envelope_id,
        "message_id": message_id,
        "date": parsed.get("date"),
        "from_addr": parsed.get("from_addr"),
        "from_name": parsed.get("from_name"),
        "to_addr": parsed.get("to_addr"),
        "to_name": parsed.get("to_name"),
        "subject": parsed.get("subject"),
        "body_text": parsed.get("body_text"),
        "body_html": parsed.get("body_html"),
        "headers_json": parsed.get("headers", {}),
        "raw_rfc5322": raw,
        "seen": 1,  # EML imports are already-read archives
    }
    
    insert_message(conn, msg)
    return (True, f"{file_path.name}: {parsed.get('subject', '(no subject)')[:60]}")


def import_eml_directory(
    directory: Path,
    account: str,
    recursive: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    batch_size: int = 1000,
) -> tuple:
    """Import all EML files from a directory. Returns (imported_count, skipped_count, errors)."""
    conn = get_db()
    init_db(conn)
    
    pattern = "**/*.eml" if recursive else "*.eml"
    files = sorted(directory.glob(pattern))
    
    if not files:
        click.echo("No .eml files found.")
        return (0, 0, 0)
    
    click.echo(f"Found {len(files)} .eml files in {directory}")
    
    imported = 0
    skipped = 0
    errors = 0
    
    for i, file_path in enumerate(files, 1):
        if verbose and i % 50 == 0:
            click.echo(f"  Progress: {i}/{len(files)}...")
        
        success, detail = import_eml_file(file_path, account, conn, dry_run=dry_run)
        
        if success:
            if dry_run or verbose:
                click.echo(f"  {detail}")
            imported += 1
        else:
            if "already synced" in detail:
                skipped += 1
            else:
                errors += 1
                if verbose:
                    click.echo(f"  ERROR: {detail}")
        
        # Periodic commit so a failure mid-import doesn't lose all progress
        if i % batch_size == 0 and not dry_run:
            conn.commit()
            if verbose:
                click.echo(f"  Committed {i}...")
    
    conn.commit()
    
    return (imported, skipped, errors)


@click.command()
@click.argument("path", type=click.Path(exists=True, resolve_path=True))
@click.option(
    "--account",
    "-a",
    default="imported",
    help="Account name to assign (default: 'imported')",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    help="Recursively search subdirectories for .eml files",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be imported without saving",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show progress for each file",
)
def import_eml(path, account, recursive, dry_run, verbose):
    """Import .eml files into MailVault.
    
    Accepts a single .eml file or a directory containing .eml files.
    Files are parsed, deduplicated by Message-ID, and inserted into
    the database. Already-imported files are skipped.
    """
    file_path = Path(path)
    
    if file_path.is_file():
        if not file_path.suffix.lower() == ".eml":
            click.echo(f"Warning: {file_path.name} does not have .eml extension", err=True)
        
        conn = get_db()
        init_db(conn)
        
        success, detail = import_eml_file(file_path, account, conn, dry_run=dry_run)
        conn.commit()
        
        if success:
            click.echo(detail)
        else:
            if "already synced" in detail:
                click.echo(f"Skipped: {detail}")
            else:
                click.echo(f"Error: {detail}", err=True)
                raise click.Abort()
    else:
        imported, skipped, errors = import_eml_directory(
            file_path, account, recursive=recursive, dry_run=dry_run, verbose=verbose
        )
        
        action = "Would import" if dry_run else "Imported"
        click.echo(f"\n{action} {imported} messages, skipped {skipped}, errors {errors}")
        
        if dry_run and imported > 0:
            click.echo("Run without --dry-run to apply.")
