"""Textual TUI for MailVault — clean implementation."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree, RichLog
from textual import on
from textual.events import Key

from .db import get_db, search, stats
from .sync import list_accounts


class MailVaultTUI(App):
    """Classic email client TUI."""

    CSS = """
    #main { height: 1fr; layout: horizontal; }
    #folders { width: 25%; border: solid $primary; padding: 1; }
    #messages { width: 35%; border: solid $primary; }
    #detail { width: 1fr; border: solid $primary; padding: 1; overflow-y: auto; }
    #status { height: 3; border: solid $primary; padding: 0 1; }
    """

    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("q", "quit", "Quit"),
        ("s", "sync", "Sync"),
    ]

    def __init__(self, account=None, initial_query=None):
        super().__init__()
        self.account = account
        self.initial_query = initial_query
        self._results = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search... (press / then type, Enter to search)", id="search")
        yield Horizontal(
            Tree("Accounts", id="folders"),
            DataTable(id="messages"),
            VerticalScroll(RichLog(id="detail", markup=False), id="detail-scroll"),
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

    def query_messages(self, query):
        conn = get_db()
        if query:
            results = search(conn, query, account=self.account, limit=100)
        else:
            sql = "SELECT * FROM messages"
            params = []
            if self.account:
                sql += " WHERE account = ?"
                params.append(self.account)
            sql += " ORDER BY date DESC LIMIT 100"
            results = [dict(r) for r in conn.execute(sql, params).fetchall()]
        self._results = results
        self._update_list()

    def _update_list(self):
        table = self.query_one("#messages", DataTable)
        table.clear(columns=True)
        if not self._results:
            table.add_columns("No messages")
            return
        table.add_columns("S", "From", "Subject", "Date")
        for r in self._results:
            seen = " " if r.get("seen") else "*"
            table.add_row(
                seen,
                r.get("from_name") or r.get("from_addr", ""),
                (r.get("subject") or "")[:40],
                (r.get("date") or "")[:16],
                key=str(r.get("id", "")),
            )
        stats_data = stats(get_db())
        self.query_one("#status", Static).update(
            f"Total: {stats_data['total']} | Showing: {len(self._results)} | Account: {self.account or 'All'}"
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
            text = f"""{subject}
{'=' * len(subject)}

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
            self.query_one("#detail-scroll", VerticalScroll).scroll_home()

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

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event):
        self._show_detail(event.cursor_row)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event):
        self._show_detail(event.cursor_row)

    @on(Tree.NodeSelected)
    def on_folder_selected(self, event):
        if event.node.data:
            self.account = event.node.data.get("account")
            self.sub_title = self.account or "All Accounts"
            self.query_messages("")

    def action_focus_search(self):
        self.query_one("#search", Input).focus()

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


def run_tui(account=None, query=None):
    MailVaultTUI(account=account, initial_query=query).run()
