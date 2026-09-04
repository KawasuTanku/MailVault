"""Email header analysis for spam source detection.

Parses Received headers, authentication results, and originating IPs
to determine the actual source of an email for abuse reporting.
"""

import re
import ipaddress
from dataclasses import dataclass, field
from typing import Optional
from email import message_from_string
from email.utils import parseaddr


@dataclass
class ReceivedHop:
    """A single Received header hop."""
    from_host: str = ""
    from_ip: Optional[str] = None
    by_host: str = ""
    with_protocol: str = ""
    date: str = ""
    raw: str = ""


@dataclass
class SpamSource:
    """Detected spam source information."""
    # Originating info
    originating_ip: Optional[str] = None
    originating_host: str = ""
    originating_domain: str = ""
    
    # Sending service
    sending_service: str = ""  # e.g., "SendGrid", "Mailchimp", "Amazon SES"
    
    # Authentication results
    spf_result: str = ""
    dkim_result: str = ""
    dmarc_result: str = ""
    
    # Abuse reporting
    abuse_address: str = ""
    abuse_headers: list = field(default_factory=list)
    
    # Full path
    hops: list = field(default_factory=list)
    
    # Detected provider for reporting
    detected_provider: str = ""
    report_address: str = ""


# Known sending services and their abuse addresses
SENDING_SERVICES = {
    "sendgrid": {
        "name": "SendGrid",
        "domains": ["sendgrid.net", "sendgrid.com"],
        "abuse": "abuse@sendgrid.net",
        "patterns": ["sendgrid", "sg_send", "sending-pool"],
    },
    "mailchimp": {
        "name": "Mailchimp",
        "domains": ["mailchimp.com", "mailchimpapp.net", "list-manage.com"],
        "abuse": "abuse@mailchimp.com",
        "patterns": ["mailchimp", "mc5", "list-manage"],
    },
    "amazonses": {
        "name": "Amazon SES",
        "domains": ["amazonses.com", "amazon.com"],
        "abuse": "abuse@amazon.com",
        "patterns": ["amazonses", "ses\\.amazon"],
    },
    "google": {
        "name": "Google/Gmail",
        "domains": ["google.com", "gmail.com", "googlemail.com"],
        "abuse": "abuse@gmail.com",
        "patterns": ["google\\.com", "gmail\\.com", "googlemail"],
    },
    "outlook": {
        "name": "Microsoft/Outlook",
        "domains": ["outlook.com", "hotmail.com", "live.com", "msn.com"],
        "abuse": "junk@office365.com",
        "patterns": ["outlook\\.com", "hotmail\\.com", "live\\.com"],
    },
    "yahoo": {
        "name": "Yahoo",
        "domains": ["yahoo.com", "ymail.com", "rocketmail.com"],
        "abuse": "abuse@yahoo.com",
        "patterns": ["yahoo\\.com", "ymail\\.com"],
    },
    "aol": {
        "name": "AOL",
        "domains": ["aol.com"],
        "abuse": "abuse@aol.com",
        "patterns": ["aol\\.com"],
    },
    "zoho": {
        "name": "Zoho",
        "domains": ["zoho.com", "zohomail.com"],
        "abuse": "abuse@zoho.com",
        "patterns": ["zoho\\.com", "zohomail"],
    },
    "protonmail": {
        "name": "Protonmail",
        "domains": ["protonmail.com", "proton.me"],
        "abuse": "abuse@protonmail.com",
        "patterns": ["protonmail", "proton\\.me"],
    },
    "yandex": {
        "name": "Yandex",
        "domains": ["yandex.com", "yandex.ru"],
        "abuse": "abuse@yandex.ru",
        "patterns": ["yandex\\.com", "yandex\\.ru"],
    },
    "icloud": {
        "name": "Apple/iCloud",
        "domains": ["icloud.com", "me.com", "mac.com"],
        "abuse": "abuse@icloud.com",
        "patterns": ["icloud\\.com", "me\\.com", "mac\\.com"],
    },
    "fastmail": {
        "name": "Fastmail",
        "domains": ["fastmail.com", "fastmail.fm", "messagingengine.com"],
        "abuse": "abuse@fastmail.com",
        "patterns": ["fastmail", "messagingengine"],
    },
    "tutanota": {
        "name": "Tutanota",
        "domains": ["tutanota.com", "tuta.com", "tutamail.com"],
        "abuse": "abuse@tutanota.com",
        "patterns": ["tutanota", "tuta\\.com"],
    },
    "ovh": {
        "name": "OVH",
        "domains": ["ovh.net", "ovh.com"],
        "abuse": "abuse@ovh.net",
        "patterns": ["ovh\\.net", "ovh\\.com"],
    },
    "namecheap": {
        "name": "Namecheap/PrivateEmail",
        "domains": ["privateemail.com", "namecheap.com"],
        "abuse": "abuse@namecheap.com",
        "patterns": ["privateemail", "namecheap"],
    },
    "ionos": {
        "name": "IONOS/1&1",
        "domains": ["ionos.com", "1and1.com", "1und1.de"],
        "abuse": "abuse@ionos.com",
        "patterns": ["ionos\\.com", "1and1\\.com"],
    },
    "godaddy": {
        "name": "GoDaddy",
        "domains": ["godaddy.com", "secureserver.net"],
        "abuse": "abuse@godaddy.com",
        "patterns": ["godaddy", "secureserver"],
    },
    "cloudflare": {
        "name": "Cloudflare Email",
        "domains": ["cloudflare.com"],
        "abuse": "abuse@cloudflare.com",
        "patterns": ["cloudflare"],
    },
    "mailgun": {
        "name": "Mailgun",
        "domains": ["mailgun.net", "mailgun.org", "mg.example.com"],
        "abuse": "abuse@mailgun.com",
        "patterns": ["mailgun"],
    },
    "postmark": {
        "name": "Postmark",
        "domains": ["postmarkapp.com", "pstmrk.it"],
        "abuse": "abuse@postmarkapp.com",
        "patterns": ["postmarkapp", "pstmrk"],
    },
    "constantcontact": {
        "name": "Constant Contact",
        "domains": ["constantcontact.com", "ctctcdn.com"],
        "abuse": "abuse@constantcontact.com",
        "patterns": ["constantcontact", "ctctcdn"],
    },
    "campaignmonitor": {
        "name": "Campaign Monitor",
        "domains": ["campaignmonitor.com", "cmail.com"],
        "abuse": "abuse@campaignmonitor.com",
        "patterns": ["campaignmonitor", "cmail"],
    },
    "aweber": {
        "name": "AWeber",
        "domains": ["aweber.com"],
        "abuse": "abuse@aweber.com",
        "patterns": ["aweber"],
    },
    "getresponse": {
        "name": "GetResponse",
        "domains": ["getresponse.com"],
        "abuse": "abuse@getresponse.com",
        "patterns": ["getresponse"],
    },
    "activecampaign": {
        "name": "ActiveCampaign",
        "domains": ["activecampaign.com"],
        "abuse": "abuse@activecampaign.com",
        "patterns": ["activecampaign"],
    },
    "hubspot": {
        "name": "HubSpot",
        "domains": ["hubspot.com", "hs-analytics.net"],
        "abuse": "abuse@hubspot.com",
        "patterns": ["hubspot"],
    },
    "salesforce": {
        "name": "Salesforce",
        "domains": ["salesforce.com", "exacttarget.com"],
        "abuse": "abuse@salesforce.com",
        "patterns": ["salesforce", "exacttarget"],
    },
    "mailjet": {
        "name": "Mailjet",
        "domains": ["mailjet.com"],
        "abuse": "abuse@mailjet.com",
        "patterns": ["mailjet"],
    },
    "sparkpost": {
        "name": "SparkPost",
        "domains": ["sparkpost.com", "sparkpostmail.com"],
        "abuse": "abuse@sparkpost.com",
        "patterns": ["sparkpost"],
    },
    "elasticemail": {
        "name": "Elastic Email",
        "domains": ["elasticemail.com"],
        "abuse": "abuse@elasticemail.com",
        "patterns": ["elasticemail"],
    },
}


def parse_received_headers(msg) -> list:
    """Parse all Received headers into hops."""
    hops = []
    for header_name, header_value in msg.items():
        if header_name.lower() == "received":
            hop = parse_received_hop(header_value)
            hops.append(hop)
    return hops


def parse_received_hop(raw: str) -> ReceivedHop:
    """Parse a single Received header."""
    hop = ReceivedHop(raw=raw)
    
    # Extract from host
    from_match = re.search(r'from\s+([^\s(]+)', raw, re.IGNORECASE)
    if from_match:
        hop.from_host = from_match.group(1).strip()
    
    # Extract IP address
    ip_match = re.search(r'\[?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\]?', raw)
    if ip_match:
        hop.from_ip = ip_match.group(1)
    
    # Extract by host
    by_match = re.search(r'by\s+([^\s(]+)', raw, re.IGNORECASE)
    if by_match:
        hop.by_host = by_match.group(1).strip()
    
    # Extract protocol
    with_match = re.search(r'with\s+(\S+)', raw, re.IGNORECASE)
    if with_match:
        hop.with_protocol = with_match.group(1)
    
    # Extract date (after semicolon)
    date_match = re.search(r';\s*(.+)$', raw)
    if date_match:
        hop.date = date_match.group(1).strip()
    
    return hop


def detect_sending_service(msg, hops: list) -> tuple:
    """Detect the sending service from headers and hops.
    
    Returns (service_name, abuse_address) or ("", "").
    """
    # Check all headers for known service patterns
    all_headers = " ".join(f"{k}: {v}" for k, v in msg.items()).lower()
    
    # Check hop hosts
    hop_hosts = " ".join(h.from_host + " " + h.by_host for h in hops).lower()
    
    combined = all_headers + " " + hop_hosts
    
    for service_key, service_info in SENDING_SERVICES.items():
        for pattern in service_info["patterns"]:
            if re.search(pattern, combined, re.IGNORECASE):
                return service_info["name"], service_info["abuse"]
    
    # Check Return-Path
    return_path = msg.get("Return-Path", "")
    _, return_addr = parseaddr(return_path)
    if return_addr:
        domain = return_addr.split("@")[-1].lower() if "@" in return_addr else ""
        for service_key, service_info in SENDING_SERVICES.items():
            for known_domain in service_info["domains"]:
                if known_domain in domain:
                    return service_info["name"], service_info["abuse"]
    
    return "", ""


def extract_abuse_address(msg) -> tuple:
    """Extract abuse reporting address from headers.
    
    Returns (address, header_name) or ("", "").
    """
    # Check various abuse-related headers
    abuse_headers = [
        "X-Complaints-To",
        "X-Report-Abuse",
        "Abuse-Reporting",
        "X-Abuse",
        "X-Abuse-Info",
        "Feedback-ID",
        "X-Feedback-ID",
    ]
    
    for header in abuse_headers:
        value = msg.get(header, "")
        if value:
            # Try to extract email from the value
            _, addr = parseaddr(value)
            if addr:
                return addr, header
            # Some headers have email-like values without proper format
            email_match = re.search(r'[\w.+-]+@[\w.-]+\.\w+', value)
            if email_match:
                return email_match.group(0), header
    
    return "", ""


def extract_originating_ip(hops: list) -> Optional[str]:
    """Extract the originating IP from the first external hop."""
    for hop in hops:
        if hop.from_ip:
            try:
                ip = ipaddress.ip_address(hop.from_ip)
                # Skip private/local IPs
                if not ip.is_private and not ip.is_loopback:
                    return hop.from_ip
            except ValueError:
                continue
    return None


def analyze_authentication(msg) -> tuple:
    """Extract SPF, DKIM, and DMARC results."""
    auth_results = msg.get("Authentication-Results", "")
    
    spf = ""
    dkim = ""
    dmarc = ""
    
    if auth_results:
        spf_match = re.search(r'spf=(\S+)', auth_results, re.IGNORECASE)
        if spf_match:
            spf = spf_match.group(1)
        
        dkim_match = re.search(r'dkim=(\S+)', auth_results, re.IGNORECASE)
        if dkim_match:
            dkim = dkim_match.group(1)
        
        dmarc_match = re.search(r'dmarc=(\S+)', auth_results, re.IGNORECASE)
        if dmarc_match:
            dmarc = dmarc_match.group(1)
    
    return spf, dkim, dmarc


def analyze_headers(raw_rfc5322: bytes) -> SpamSource:
    """Analyze email headers to determine spam source.
    
    Args:
        raw_rfc5322: Raw RFC 5322 message bytes
        
    Returns:
        SpamSource with detected information
    """
    msg = message_from_string(raw_rfc5322.decode("utf-8", errors="replace"))
    source = SpamSource()
    
    # Parse Received headers
    source.hops = parse_received_headers(msg)
    
    # Extract originating IP
    source.originating_ip = extract_originating_ip(source.hops)
    
    # Detect sending service
    source.sending_service, source.report_address = detect_sending_service(msg, source.hops)
    
    # Extract abuse address from headers
    abuse_addr, abuse_header = extract_abuse_address(msg)
    if abuse_addr:
        source.abuse_address = abuse_addr
        source.abuse_headers.append(abuse_header)
    
    # Authentication results
    source.spf_result, source.dkim_result, source.dmarc_result = analyze_authentication(msg)
    
    # Determine originating domain from From header
    from_header = msg.get("From", "")
    _, from_addr = parseaddr(from_header)
    if from_addr and "@" in from_addr:
        source.originating_domain = from_addr.split("@")[-1].lower()
    
    # Determine best report address
    if source.abuse_address:
        source.report_address = source.abuse_address
    elif source.sending_service and source.report_address:
        pass  # Already set from service detection
    elif source.originating_domain:
        # Try to construct abuse@domain
        source.report_address = f"abuse@{source.originating_domain}"
    
    return source


def format_source_report(source: SpamSource) -> str:
    """Format spam source analysis for display."""
    lines = []
    lines.append("Spam Source Analysis")
    lines.append("=" * 40)
    
    if source.originating_ip:
        lines.append(f"Originating IP: {source.originating_ip}")
    
    if source.originating_domain:
        lines.append(f"Sender Domain: {source.originating_domain}")
    
    if source.sending_service:
        lines.append(f"Sending Service: {source.sending_service}")
    
    if source.abuse_address:
        lines.append(f"Abuse Address: {source.abuse_address}")
    
    if source.report_address:
        lines.append(f"Report To: {source.report_address}")
    
    if source.spf_result:
        lines.append(f"SPF: {source.spf_result}")
    
    if source.dkim_result:
        lines.append(f"DKIM: {source.dkim_result}")
    
    if source.dmarc_result:
        lines.append(f"DMARC: {source.dmarc_result}")
    
    if source.hops:
        lines.append("")
        lines.append("Received Path:")
        for i, hop in enumerate(source.hops):
            lines.append(f"  {i+1}. from {hop.from_host} [{hop.from_ip or 'no IP'}] by {hop.by_host}")
    
    return "\n".join(lines)
