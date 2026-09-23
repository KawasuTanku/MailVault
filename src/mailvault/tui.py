"""Textual TUI for MailVault — minimal working version."""

import os

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree, RichLog
from textual import on
from textual.events import Key

from .db import get_db, search, stats, delete_message, mark_read
from .sync import list_accounts
from .spam import report_spam_using_himalaya, PROVIDERS
from .header_analysis import analyze_headers, format_source_report


def parse_rgb_env(name, default):
    """Parse a TankuOS TANKUOS_THEME_* env var ('r,g,b') into hex (#rrggbb)."""
    raw = os.environ.get(name, "")
    if "," in raw:
        parts = raw.split(",")[:3]
        try:
            r, g, b = (int(p) for p in parts)
            return f"#{r:02x}{g:02x}{b:02x}"
        except ValueError:
            pass
    return default


class MailVaultTUI(App):
    """Classic email client TUI with TankuOS theme support."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto;
        background: $background;
    }
    #main { height: 1fr; layout: horizontal; }
    #folders {
        width: 25;
        height: 100%;
        border: solid $primary;
        padding: 1;
        background: $surface;
    }
    #right { width: 1fr; layout: grid; grid-rows: 1fr 2fr; }
    #messages {
        border: solid $primary;
        background: $surface;
    }
    #detail {
        border: solid $primary;
        padding: 1;
        overflow-y: auto;
        background: $surface;
    }
    #status {
        height: 3;
        border: solid $primary;
        padding: 0 1;
        background: $surface;
        color: $success;
    }
    DataTable > .datatable--cursor {
        background: $accent;
        color: $background;
    }
    Tree > .tree--cursor {
        background: $accent;
        color: $background;
    }
    Header {
        color: $accent;
        background: $surface;
    }
    Footer {
        color: $foreground;
        background: $surface;
    }
    Static {
        color: $foreground;
    }
    Input {
        color: $foreground;
        background: $surface;
    }
    RichLog {
        background: $surface;
        color: $foreground;
    }
    VerticalScroll {
        background: $surface;
    }
    .warning { color: $warning; }
    .success { color: $success; }
    .error { color: $error; }
    """

    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("q", "quit", "Quit"),
        ("s", "sync", "Sync"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("enter", "open_message", "Open"),
        ("n", "next_page", "Next page"),
        ("p", "previous_page", "Prev page"),
        ("v", "view_raw", "View Raw"),
        ("r", "toggle_read", "Read/Unread"),
        ("d", "delete", "Delete"),
        ("S", "report_spam", "Report Spam"),
        ("a", "analyze_headers", "Analyze"),
    ]

    def __init__(self, account=None, initial_query=None):
        super().__init__()
        self.account = account
        self.initial_query = initial_query
        self._results = []
        self._offset = 0
        self._page_size = 100
        self._total_count = 0
        self._last_query = ""

        # Apply TankuOS theme via TANKUOS_THEME_* env vars (injected by PTY host)
        self.stylesheet.set_variables({
            "primary": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "accent": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "background": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "surface": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "panel": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "boost": parse_rgb_env("TANKUOS_THEME_SECONDARY", "#2d3a55"),
            "error": parse_rgb_env("TANKUOS_THEME_ERROR", "#ff6b6b"),
            "warning": parse_rgb_env("TANKUOS_THEME_WARNING", "#f0c674"),
            "success": parse_rgb_env("TANKUOS_THEME_SUCCESS", "#98c379"),
            # Textual default CSS variables (ansi, scrollbar, border, etc.)
            "ansi-background": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "ansi-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "screen-selection-background": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "screen-selection-foreground": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "scrollbar-background": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "scrollbar": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "scrollbar-active": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "scrollbar-hover": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "scrollbar-background-hover": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "scrollbar-background-active": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "scrollbar-corner-color": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "link-background": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "link-color": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "link-style": "bold",
            "link-background-hover": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "link-color-hover": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "link-style-hover": "bold",
            "block-cursor-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "block-cursor-background": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "block-cursor-text-style": "reverse",
            "block-cursor-blurred-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "block-cursor-blurred-background": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "block-cursor-blurred-text-style": "reverse",
            "border": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "border-blurred": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "panel-darken-1": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "panel-darken-2": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "panel-lighten-1": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "panel-lighten-2": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "panel-lighten-3": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "surface-lighten-1": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "surface-lighten-2": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "surface-lighten-3": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "surface-darken-1": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "primary-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "primary-lighten-3": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "primary-darken-2": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "primary-darken-3": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "accent-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "accent-darken-1": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "success-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "success-lighten-1": parse_rgb_env("TANKUOS_THEME_SUCCESS", "#98c379"),
            "success-lighten-2": parse_rgb_env("TANKUOS_THEME_SUCCESS", "#98c379"),
            "success-darken-2": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "success-darken-3": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "warning-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "warning-darken-1": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "error-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "error-lighten-2": parse_rgb_env("TANKUOS_THEME_ERROR", "#ff6b6b"),
            "error-darken-1": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "error-darken-2": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "text": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "text-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "text-primary": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "text-secondary": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "text-success": parse_rgb_env("TANKUOS_THEME_SUCCESS", "#98c379"),
            "text-warning": parse_rgb_env("TANKUOS_THEME_WARNING", "#f0c674"),
            "text-error": parse_rgb_env("TANKUOS_THEME_ERROR", "#ff6b6b"),
            "text-accent": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "text-disabled": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "foreground-muted": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "foreground-darken-1": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "secondary": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "secondary-muted": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "button-focus-text-style": "reverse bold",
            "button-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "button-color-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "input-cursor-background": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "input-cursor-foreground": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "input-cursor-text-style": "reverse",
            "input-selection-background": parse_rgb_env("TANKUOS_THEME_ACCENT", "#6cb6ff"),
            "input-selection-foreground": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "footer-item-background": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "footer-key-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "footer-key-background": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "footer-description-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "footer-description-background": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
            "footer-foreground": parse_rgb_env("TANKUOS_THEME_FG", "#c8d0dc"),
            "footer-background": parse_rgb_env("TANKUOS_THEME_PANEL", "#1d2433"),
            "block-hover-background": parse_rgb_env("TANKUOS_THEME_BG", "#11141d"),
        })

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search... (press / then type, Enter to search)", id="search")
        yield Horizontal(
            Tree("Accounts", id="folders"),
            Vertical(
                DataTable(id="messages"),
                VerticalScroll(RichLog(id="detail", markup=False), id="detail-scroll"),
                id="right",
            ),
            id="main",
        )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "MailVault"
        self.sub_title = self.account or "All Accounts"
        self._populate_folders()
        self.query_messages(self.initial_query or "")
        self.query_one("#messages", DataTable).focus()

    def _populate_folders(self):
        tree = self.query_one("#folders", Tree)
        root = tree.root
        root.label = "All Accounts"
        root.data = {"account": None}
        root.expand()
        for acc in list_accounts():
            root.add_leaf(
                f"{acc.get('name', 'default')} ({acc.get('email', '')})",
                data={"account": acc.get("name", "default")},
            )

    def query_messages(self, query, offset=0):
        conn = get_db()
        self._offset = offset
        self._last_query = query
        if query:
            # Count total matches
            count_sql = "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH ?"
            params = [query]
            if self.account:
                count_sql += " AND account = ?"
                params.append(self.account)
            self._total_count = conn.execute(count_sql, params).fetchone()[0]
            results = search(conn, query, account=self.account, limit=self._page_size, offset=offset)
        else:
            # Count total messages
            count_sql = "SELECT COUNT(*) FROM messages"
            params = []
            if self.account:
                count_sql += " WHERE account = ?"
                params.append(self.account)
            self._total_count = conn.execute(count_sql, params).fetchone()[0]
            
            sql = "SELECT * FROM messages"
            params = []
            if self.account:
                sql += " WHERE account = ?"
                params.append(self.account)
            sql += " ORDER BY date DESC LIMIT ? OFFSET ?"
            params.extend([self._page_size, offset])
            results = [dict(r) for r in conn.execute(sql, params).fetchall()]
        self._results = results
        self._update_list()

    def _update_list(self):
        table = self.query_one("#messages", DataTable)
        table.clear(columns=True)
        if not self._results:
            table.add_columns("No messages")
            return
        table.add_columns("From", "Subject", "Date")
        for r in self._results:
            table.add_row(
                r.get("from_name") or r.get("from_addr", ""),
                (r.get("subject") or "")[:40],
                (r.get("date") or "")[:16],
                key=str(r.get("id", "")),
            )
        stats_data = stats(get_db())
        page_end = min(self._offset + len(self._results), self._total_count)
        page_label = f"Page {self._offset // self._page_size + 1}/{(self._total_count + self._page_size - 1) // self._page_size}"
        self.query_one("#status", Static).update(
            f"Total: {stats_data['total']} | Showing {self._offset+1}-{page_end}/{self._total_count} | {page_label} | Account: {self.account or 'All'}"
        )

    def _show_detail(self, row_index):
        if row_index is None or row_index < 0 or row_index >= len(self._results):
            return
        row = self._results[row_index]
        conn = get_db()
        row_data = conn.execute("SELECT * FROM messages WHERE id = ?", (row["id"],)).fetchone()
        if row_data:
            subject = row_data['subject'] or ''
            from_name = row_data['from_name'] or ''
            from_addr = row_data['from_addr'] or ''
            to_name = row_data['to_name'] or ''
            to_addr = row_data['to_addr'] or ''
            date = row_data['date'] or ''
            account = row_data['account'] or ''
            seen = 'Yes' if row_data['seen'] else 'No'
            body = row_data['body_text'] or ''
            body_html = row_data['body_html'] or ''
            if body_html:
                try:
                    import html2text
                    h = html2text.HTML2Text()
                    h.body_width = 0
                    body = h.handle(body_html)
                except ImportError:
                    body = body_html
            text = f"""ID: {row['id']}
Subject: {subject}
From: {from_name} <{from_addr}>
To: {to_name} <{to_addr}>
Date: {date}
Account: {account}
Seen: {seen}

{body}
"""
            detail = self.query_one("#detail", RichLog)
            detail.clear()
            detail.write(text)
            scroll = self.query_one("#detail-scroll", VerticalScroll)
            scroll.scroll_to(y=0)

    def _show_raw(self):
        table = self.query_one("#messages", DataTable)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        raw_row = conn.execute("SELECT raw_rfc5322 FROM messages WHERE id = ?", (row["id"],)).fetchone()
        if raw_row and raw_row["raw_rfc5322"]:
            raw = raw_row["raw_rfc5322"]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            detail = self.query_one("#detail", RichLog)
            detail.clear()
            detail.write(raw[:5000])
            self.query_one("#detail-scroll", VerticalScroll).scroll_home()

    @on(Input.Submitted, "#search")
    def on_search_submitted(self, event):
        self.query_messages(event.value)
        self.query_one("#messages", DataTable).focus()

    @on(Key)
    def on_key(self, event: Key) -> None:
        """Handle key events at app level."""
        search = self.query_one("#search", Input)
        if search.has_focus:
            return
            
        table = self.query_one("#messages", DataTable)
        
        if event.key == "j":
            table.action_cursor_down()
            self._show_detail(table.cursor_row)
            event.prevent_default()
        elif event.key == "k":
            table.action_cursor_up()
            self._show_detail(table.cursor_row)
            event.prevent_default()
        elif event.key == "enter":
            if table.cursor_row is not None:
                self._show_detail(table.cursor_row)
            elif self._results:
                table.cursor_coordinate = (0, 0)
                self._show_detail(0)
            event.prevent_default()
        elif event.key == "v":
            self._show_raw()
            event.prevent_default()
        elif event.key == "r":
            self._toggle_read()
            event.prevent_default()
        elif event.key == "d":
            self._delete()
            event.prevent_default()

    @on(Tree.NodeSelected)
    def on_folder_selected(self, event):
        if event.node.data:
            self.account = event.node.data.get("account")
            self.sub_title = self.account or "All Accounts"
            self.query_messages("")

    def action_next_page(self):
        """Load next page of results."""
        next_offset = self._offset + self._page_size
        if next_offset < self._total_count:
            self.query_messages(self._last_query, offset=next_offset)

    def action_previous_page(self):
        """Load previous page of results."""
        prev_offset = self._offset - self._page_size
        if prev_offset >= 0:
            self.query_messages(self._last_query, offset=prev_offset)

    def action_focus_search(self):
        self.query_one("#search", Input).focus()

    def _delete(self):
        """Delete the message at the cursor row."""
        table = self.query_one("#messages", DataTable)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        if delete_message(conn, row["id"]):
            self.query_one("#status", Static).update(
                f"Deleted message {row['id']}"
            )
            self.query_messages(self._last_query, offset=self._offset)
        else:
            self.query_one("#status", Static).update("Delete failed")

    def _toggle_read(self):
        """Toggle read/unread on the message at the cursor row."""
        table = self.query_one("#messages", DataTable)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        new_seen = 0 if row.get("seen") else 1
        conn = get_db()
        mark_read(conn, row["id"], new_seen)
        row["seen"] = new_seen
        status_str = "Read" if new_seen else "Unread"
        self.query_one("#status", Static).update(
            f"Marked {status_str} (id {row['id']})"
        )

    def action_sync(self):
        from .sync import get_envelopes, get_raw_message, parse_raw_message, HimalayaError
        from .db import insert_message, is_message_id_synced, update_sync_state
        conn = get_db()
        for acc in list_accounts():
            acc_name = acc.get("name", "default")
            if self.account and acc_name != self.account:
                continue
            try:
                envelopes, _ = get_envelopes(account=acc_name, page=1, page_size=50)
            except HimalayaError:
                continue
            new_count = 0
            for env in envelopes:
                env_id = env.get("id", "")
                if not env_id:
                    continue
                msg_id = env.get("message-id", "")
                if msg_id and is_message_id_synced(conn, msg_id):
                    continue
                try:
                    raw = get_raw_message(env_id, account=acc_name)
                    parsed = parse_raw_message(raw)
                    flags = env.get("flags", [])
                    seen = 1 if any(f.get("iana") == "seen" for f in flags) else 0
                    insert_message(conn, {
                        "account": acc_name, "envelope_id": env_id, "message_id": parsed["message_id"],
                        "date": parsed["date"], "from_addr": parsed["from_addr"], "from_name": parsed["from_name"],
                        "to_addr": parsed["to_addr"], "to_name": parsed["to_name"], "subject": parsed["subject"],
                        "body_text": parsed["body_text"], "body_html": parsed.get("body_html", ""),
                        "headers_json": parsed["headers"], "raw_rfc5322": raw, "seen": seen,
                    })
                    new_count += 1
                except HimalayaError:
                    continue
            conn.commit()
            update_sync_state(conn, acc_name, 1, new_count, 0)
        self.query_messages("")

    def action_report_spam(self):
        """Report selected message as spam."""
        table = self.query_one("#messages", DataTable)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        raw_row = conn.execute(
            "SELECT raw_rfc5322 FROM messages WHERE id = ?", (row["id"],)
        ).fetchone()
        if not raw_row or not raw_row["raw_rfc5322"]:
            return
        
        raw = raw_row["raw_rfc5322"]
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        
        recipient = PROVIDERS["spamhaus"]["address"]
        
        smtp_config = None
        try:
            from .spam import load_smtp_config
            smtp_config = load_smtp_config()
        except Exception:
            pass
        
        from_addr = smtp_config["from_addr"] if smtp_config else "reporter@localhost"
        
        success = report_spam_using_himalaya(
            raw_rfc5322=raw,
            recipient=recipient,
            from_addr=from_addr,
            subject=row["subject"] or "Spam report",
            message_id=row["message_id"] or "",
        )
        
        if success:
            self.query_one("#status", Static).update(
                f"Spam report sent to {recipient}"
            )
        else:
            self.query_one("#status", Static).update(
                f"Failed to send spam report"
            )

    def action_analyze_headers(self):
        """Analyze headers of selected message to detect spam source."""
        table = self.query_one("#messages", DataTable)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        raw_row = conn.execute(
            "SELECT raw_rfc5322 FROM messages WHERE id = ?", (row["id"],)
        ).fetchone()
        if not raw_row or not raw_row["raw_rfc5322"]:
            return
        
        raw = raw_row["raw_rfc5322"]
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        
        source = analyze_headers(raw)
        report = format_source_report(source)
        
        detail = self.query_one("#detail", RichLog)
        detail.clear()
        detail.write(report)
        self.query_one("#detail-scroll", VerticalScroll).scroll_home()


def run_tui(account=None, query=None):
    MailVaultTUI(account=account, initial_query=query).run()
