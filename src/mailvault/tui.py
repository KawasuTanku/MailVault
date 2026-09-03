"""Textual TUI for MailVault — classic email client feel."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree, Label
from textual.binding import Binding
from textual.message import Message
from textual import on
from textual.color import Color

from .db import get_db, search, stats
from .sync import list_accounts


class FolderTree(Tree):
    """Folder/account tree on the left."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "select_folder", "Select"),
    ]

    class Selected(Message):
        def __init__(self, account: str | None) -> None:
            self.account = account
            super().__init__()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        if node.data:
            self.post_message(self.Selected(node.data.get("account")))


class MessageList(DataTable):
    """Message list — classic email client style."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("d", "delete", "Delete"),
        Binding("r", "toggle_read", "Read/Unread"),
        Binding("v", "view_raw", "View Raw"),
        Binding("enter", "open_message", "Open"),
    ]

    class Selected(Message):
        def __init__(self, row_key: str) -> None:
            self.row_key = row_key
            super().__init__()


class MessageDetail(ScrollableContainer):
    """Message detail pane."""


class StatusBar(Static):
    """Status bar at the bottom."""


class MailVaultTUI(App):
    """Classic email client TUI for MailVault."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto;
    }
    
    #main {
        height: 1fr;
        layout: horizontal;
    }
    
    #folders {
        width: 25%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    
    #messages {
        width: 35%;
        height: 100%;
        border: solid $primary;
    }
    
    #detail {
        width: 40%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    
    #status {
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }
    
    #search {
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }
    
    DataTable {
        height: 100%;
    }
    
    DataTable > .datatable--cursor {
        background: $accent;
    }
    
    .folder-tree {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("/", "search", "Search"),
        Binding("q", "quit", "Quit"),
        Binding("g", "go_top", "Top"),
        Binding("G", "go_bottom", "Bottom"),
        Binding("s", "sync", "Sync"),
        Binding("a", "accounts", "Accounts"),
    ]

    def __init__(self, account: str | None = None, initial_query: str | None = None):
        super().__init__()
        self.account = account
        self.initial_query = initial_query
        self._results: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search... (press / to focus)", id="search")
        yield Horizontal(
            FolderTree("Accounts", id="folders"),
            MessageList(id="messages"),
            MessageDetail(id="detail"),
            id="main",
        )
        yield StatusBar("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "MailVault"
        self.sub_title = self.account or "All Accounts"
        self._populate_folders()
        self.query_messages(self.initial_query or "")

    def _populate_folders(self) -> None:
        """Populate the folder tree."""
        tree = self.query_one("#folders", FolderTree)
        root = tree.root
        root.data = {"account": None, "name": "All Accounts"}
        root.label = "All Accounts"
        root.expand()

        accounts = list_accounts()
        for acc in accounts:
            node = root.add_leaf(
                f"{acc.get('name', 'default')} ({acc.get('email', '')})",
                data={"account": acc.get("name", "default")},
            )

    def query_messages(self, query: str) -> None:
        """Run a search and update the list."""
        conn = get_db()
        if query:
            results = search(conn, query, account=self.account, limit=100)
        else:
            sql = "SELECT * FROM messages"
            params: list = []
            if self.account:
                sql += " WHERE account = ?"
                params.append(self.account)
            sql += " ORDER BY date DESC LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
            results = [dict(r) for r in rows]

        self._results = results
        self.update_list()

    def update_list(self) -> None:
        """Update the data table with current results."""
        table = self.query_one("#messages", MessageList)
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
                r.get("subject", "")[:40],
                r.get("date", "")[:16],
                key=r.get("id", ""),
            )

        # Update status
        stats_data = stats(get_db())
        status = self.query_one("#status", StatusBar)
        status.update(
            f"Total: {stats_data['total']} | "
            f"Showing: {len(self._results)} | "
            f"Account: {self.account or 'All'}"
        )

    def on_message_list_selected(self, event: MessageList.Selected) -> None:
        """Show message detail when selected."""
        row_id = event.row_key
        conn = get_db()
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (row_id,)).fetchone()
        if not row:
            return

        detail = self.query_one("#detail", MessageDetail)
        detail.remove_children()

        headers = row["headers_json"]
        if isinstance(headers, str):
            import json as json_mod
            try:
                headers = json_mod.loads(headers)
            except Exception:
                headers = {}

        text = f"""[bold]{row['subject']}[/bold]
From: {row['from_name'] or ''} <{row['from_addr']}>
To: {row['to_name'] or ''} <{row['to_addr']}>
Date: {row['date']}
Account: {row['account']}
Seen: {'Yes' if row['seen'] else 'No'}

{row['body_text'] or '(no body)'}
"""
        detail.mount(Static(text))

    def on_folder_tree_selected(self, event: FolderTree.Selected) -> None:
        """Handle folder selection."""
        self.account = event.account
        self.sub_title = self.account or "All Accounts"
        self.query_messages("")

    def action_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search", Input).focus()

    def action_go_top(self) -> None:
        table = self.query_one("#messages", MessageList)
        table.cursor_coordinate = (0, 0)

    def action_go_bottom(self) -> None:
        table = self.query_one("#messages", MessageList)
        table.action_last()

    def action_delete(self) -> None:
        """Delete selected message."""
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        conn.execute("DELETE FROM messages WHERE id = ?", (row["id"],))
        conn.commit()
        self.query_messages("")

    def action_toggle_read(self) -> None:
        """Toggle seen status of selected message."""
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        new_seen = 0 if row["seen"] else 1
        conn.execute(
            "UPDATE messages SET seen = ? WHERE id = ?",
            (new_seen, row["id"]),
        )
        conn.commit()
        self.query_messages("")

    def action_view_raw(self) -> None:
        """View raw RFC 5322 message."""
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        raw_row = conn.execute(
            "SELECT raw_rfc5322 FROM messages WHERE id = ?", (row["id"],)
        ).fetchone()
        if raw_row and raw_row["raw_rfc5322"]:
            raw = raw_row["raw_rfc5322"]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            detail = self.query_one("#detail", MessageDetail)
            detail.remove_children()
            detail.mount(Static(raw[:5000]))

    def action_sync(self) -> None:
        """Trigger a sync."""
        from .sync import get_envelopes, get_raw_message, parse_raw_message, HimalayaError
        from .db import insert_message, is_message_id_synced, update_sync_state, get_sync_state

        conn = get_db()
        accounts = list_accounts()
        for acc in accounts:
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
                except HimalayaError:
                    continue

            conn.commit()
            update_sync_state(conn, acc_name, 1, new_count, 0)

        self.query_messages("")

    def action_accounts(self) -> None:
        """Show accounts."""
        accounts = list_accounts()
        detail = self.query_one("#detail", MessageDetail)
        detail.remove_children()
        text = "Configured Accounts:\n\n"
        for acc in accounts:
            text += f"  {acc.get('name', 'default')} — {acc.get('email', '')}\n"
        detail.mount(Static(text))


def run_tui(account: str | None = None, query: str | None = None) -> None:
    """Run the TUI."""
    app = MailVaultTUI(account=account, initial_query=query)
    app.run()
