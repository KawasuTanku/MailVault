"""Import/Export for MailVault."""

import json
import sys
from pathlib import Path
from typing import Optional

from .db import get_db, init_db, insert_message


def export_all(output: Optional[Path] = None) -> int:
    """Export all messages as JSONL. Returns count."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM messages ORDER BY account, date").fetchall()

    count = 0
    out = open(output, "w", encoding="utf-8") if output else sys.stdout

    try:
        for row in rows:
            msg = {
                "account": row["account"],
                "envelope_id": row["envelope_id"],
                "message_id": row["message_id"],
                "date": row["date"],
                "from_addr": row["from_addr"],
                "from_name": row["from_name"],
                "to_addr": row["to_addr"],
                "to_name": row["to_name"],
                "subject": row["subject"],
                "body_text": row["body_text"],
                "headers_json": row["headers_json"],
                "seen": row["seen"],
            }
            raw = row["raw_rfc5322"]
            if raw:
                if isinstance(raw, bytes):
                    msg["raw_rfc5322"] = raw.decode("utf-8", errors="replace")
                else:
                    msg["raw_rfc5322"] = raw

            out.write(json.dumps(msg, ensure_ascii=False) + "\n")
            count += 1

            if count % 100 == 0:
                print(f"  Exported {count}...", file=sys.stderr)

    finally:
        if output:
            out.close()

    return count


def import_from_jsonl(input_file: Path) -> int:
    """Import messages from JSONL file. Returns count."""
    conn = get_db()
    init_db(conn)

    count = 0
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                insert_message(conn, msg)
                count += 1
                if count % 100 == 0:
                    print(f"  Imported {count}...", file=sys.stderr)
            except json.JSONDecodeError as e:
                print(f"  Skipping invalid line: {e}", file=sys.stderr)
                continue
            except Exception as e:
                print(f"  Error importing message: {e}", file=sys.stderr)
                continue

    conn.commit()
    return count