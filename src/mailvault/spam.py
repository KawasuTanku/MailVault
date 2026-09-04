"""Spam reporting for MailVault using Python smtplib."""

import smtplib
import tomllib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.message import MIMEMessage
from pathlib import Path
from typing import Optional


# Default reporting addresses for major providers
PROVIDERS = {
    "gmail": {
        "name": "Gmail",
        "address": "spam@gmail.com",
        "description": "Report spam to Google",
    },
    "outlook": {
        "name": "Outlook/Microsoft",
        "address": "junk@office365.com",
        "description": "Report junk to Microsoft",
    },
    "spamhaus": {
        "name": "SpamHaus",
        "address": "submit@spamhaus.org",
        "description": "Report to SpamHaus (requires registration)",
    },
    "spamcop": {
        "name": "SpamCop",
        "address": "submit@spamcop.net",
        "description": "Report to SpamCop",
    },
    "sendgrid": {
        "name": "SendGrid",
        "address": "abuse@sendgrid.net",
        "description": "Report abuse to SendGrid",
    },
    "yahoo": {
        "name": "Yahoo",
        "address": "spam@ymail.com",
        "description": "Report spam to Yahoo",
    },
    "aol": {
        "name": "AOL",
        "address": "spam@aol.com",
        "description": "Report spam to AOL",
    },
}


def load_smtp_config(account: str = "default") -> Optional[dict]:
    """Load SMTP configuration from himalaya config."""
    himalaya_config = Path.home() / ".config" / "himalaya" / "config.toml"
    if not himalaya_config.exists():
        return None
    
    try:
        with open(himalaya_config, "rb") as f:
            config = tomllib.load(f)
    except Exception:
        return None
    
    # Try to find SMTP settings for the account
    accounts = config.get("accounts", {})
    acc_config = accounts.get(account, {})
    
    smtp = acc_config.get("smtp", {})
    if not smtp:
        return None
    
    # Extract password from command or raw
    password = None
    auth = smtp.get("sasl", {}).get("plain", {})
    if "password" in auth:
        pwd_config = auth["password"]
        if "raw" in pwd_config:
            password = pwd_config["raw"]
        elif "command" in pwd_config:
            import subprocess
            try:
                result = subprocess.run(
                    pwd_config["command"],
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                password = result.stdout.strip()
            except Exception:
                pass
    
    return {
        "host": smtp.get("host", "localhost"),
        "port": smtp.get("port", 587),
        "username": smtp.get("sasl", {}).get("plain", {}).get("username", ""),
        "password": password,
        "starttls": smtp.get("starttls", True),
        "from_addr": acc_config.get("email", smtp.get("sasl", {}).get("plain", {}).get("username", "")),
    }


def report_spam(
    raw_rfc5322: bytes,
    recipient: str,
    from_addr: str,
    smtp_host: str = "localhost",
    smtp_port: int = 587,
    smtp_username: str = "",
    smtp_password: str = "",
    smtp_starttls: bool = True,
    subject: str = "Spam report",
    message_id: str = "",
) -> bool:
    """Report spam by forwarding the raw message to the recipient.
    
    Args:
        raw_rfc5322: The raw RFC 5322 message bytes
        recipient: Email address to report to
        from_addr: From address for the report
        smtp_host: SMTP server host
        smtp_port: SMTP server port
        smtp_username: SMTP username
        smtp_password: SMTP password
        smtp_starttls: Whether to use STARTTLS
        subject: Subject of the original spam message
        message_id: Message-ID of the original spam message
        
    Returns:
        True if report was sent successfully
    """
    # Build the report email with the spam message attached
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = recipient
    msg["Subject"] = f"[Spam Report] {subject}"
    
    # Body text
    body = f"""This is a spam report submitted via MailVault.

The attached message has been identified as spam and is being reported
for investigation.

Original Message-ID: {message_id}
---
This report was generated automatically by MailVault.
"""
    msg.attach(MIMEText(body, "plain"))
    
    # Attach the original spam message
    spam_msg = MIMEMessage(
        MIMEText(raw_rfc5322.decode("utf-8", errors="replace"), "rfc822")
    )
    spam_msg.add_header("Content-Disposition", "attachment", filename="spam_message.eml")
    msg.attach(spam_msg)
    
    # Send via SMTP
    try:
        if smtp_starttls:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port)
        
        if smtp_username and smtp_password:
            server.login(smtp_username, smtp_password)
        
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending spam report: {e}")
        return False


def report_spam_using_himalaya(
    raw_rfc5322: bytes,
    recipient: str,
    from_addr: str,
    account: Optional[str] = None,
    subject: str = "Spam report",
    message_id: str = "",
) -> bool:
    """Report spam using himalaya CLI.
    
    This saves the raw message to a temp file and uses himalaya to send it.
    """
    import subprocess
    import tempfile
    
    # Save raw message to temp file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".eml", delete=False) as f:
        f.write(raw_rfc5322)
        temp_path = f.name
    
    try:
        # Build report body
        body = f"""This is a spam report submitted via MailVault.

The attached message has been identified as spam and is being reported
for investigation.

Original Message-ID: {message_id}
---
This report was generated automatically by MailVault.
"""
        
        cmd = ["himalaya"]
        if account:
            cmd += ["--account", account]
        cmd += [
            "message", "send",
            "--from", from_addr,
            "--to", recipient,
            "--subject", f"[Spam Report] {subject}",
            "--body", body,
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False
    finally:
        import os
        os.unlink(temp_path)


def get_provider(name: str) -> Optional[dict]:
    """Get a provider by name."""
    return PROVIDERS.get(name)


def list_providers() -> dict:
    """List all available providers."""
    return PROVIDERS
