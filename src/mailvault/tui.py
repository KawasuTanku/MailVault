"""Textual TUI for MailVault — classic email client feel."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Static, Tree
from textual.binding import Binding
from textual.message import Message

from .db import get_db, search, stats
from .sync import list_accounts


class FolderTree(Tree):
    """Folder/account tree on the left."""

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
        Binding("d", "delete", "Delete"),
        Binding("r", "toggle_read", "Read/Unread"),
        Binding("v", "view_raw", "View Raw"),
        Binding("enter", "open_message", "Open"),
    ]


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
        overflow-y: auto;
    }
    
    #status {
        height: 3;
        border: solid $primary;
        padding: 0 1;
    }
    
    DataTable {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("/", "search", "Search"),
        Binding("q", "quit", "Quit"),
        Binding("g", "go_top", "Top"),
        Binding("G", "go_bottom", "Bottom"),
        Binding("s", "sync", "Sync"),
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
            Static("Select a message to view details", id="detail"),
            id="main",
        )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "MailVault"
        self.sub_title = self.account or "All Accounts"
        self._populate_folders()
        self.query_messages(self.initial_query or "")

    def _populate_folders(self) -> None:
        tree = self.query_one("#folders", FolderTree)
        root = tree.root
        root.data = {"account": None}
        root.label = "All Accounts"
        root.expand()

        for acc in list_accounts():
            root.add_leaf(
                f"{acc.get('name', 'default')} ({acc.get('email', '')})",
                data={"account": acc.get("name", "default")},
            )

    def query_messages(self, query: str) -> None:
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
            results = [dict(r) for r in conn.execute(sql, params).fetchall()]

        self._results = results
        self._update_list()

    def _update_list(self) -> None:
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
                (r.get("subject") or "")[:40],
                (r.get("date") or "")[:16],
                key=str(r.get("id", "")),
            )

        stats_data = stats(get_db())
        self.query_one("#status", Static).update(
            f"Total: {stats_data['total']} | "
            f"Showing: {len(self._results)} | "
            f"Account: {self.account or 'All'}"
        )

    def on_data_table_cursor_moved(self, event: DataTable.CursorMoved) -> None:
        """Show message detail when cursor moves (j/k navigation)."""
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is not None and self._results:
            row = self._results[table.cursor_row]
            conn = get_db()
            row_data = conn.execute("SELECT * FROM messages WHERE id = ?", (row["id"],)).fetchone()
            if row_data:
                text = f"""[bold]{row_data['subject']}[/bold]
From: {row_data['from_name'] or ''} <{row_data['from_addr']}>
To: {row_data['to_name'] or ''} <{row_data['to_addr']}>
Date: {row_data['date']}
Account: {row_data['account']}
Seen: {'Yes' if row_data['seen'] else 'No'}

{row_data['body_text'] or '(no body)'}
"""
                self.query_one("#detail", Static).update(text)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show message detail when row is selected (Enter)."""
        self.on_data_table_cursor_moved(event)

    def on_folder_tree_selected(self, event: FolderTree.Selected) -> None:
        self.account = event.account
        self.sub_title = self.account or "All Accounts"
        self.query_messages("")

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_go_top(self) -> None:
        table = self.query_one("#messages", MessageList)
        table.cursor_coordinate = (0, 0)

    def action_go_bottom(self) -> None:
        table = self.query_one("#messages", MessageList)
        if table.row_count > 0:
            table.cursor_coordinate = (table.row_count - 1, 0)

    def action_delete(self) -> None:
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        conn.execute("DELETE FROM messages WHERE id = ?", (row["id"],))
        conn.commit()
        self.query_messages("")

    def action_toggle_read(self) -> None:
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is None or not self._results:
            return
        row = self._results[table.cursor_row]
        conn = get_db()
        new_seen = 0 if row["seen"] else 1
        conn.execute("UPDATE messages SET seen = ? WHERE id = ?", (new_seen, row["id"]))
        conn.commit()
        self.query_messages("")

    def action_view_raw(self) -> None:
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
            self.query_one("#detail", Static).update(raw[:5000])

    def action_open_message(self) -> None:
        """Open selected message (triggered by Enter)."""
        table = self.query_one("#messages", MessageList)
        if table.cursor_row is not None and self._results:
            row = self._results[table.cursor_row]
            conn = get_db()
            row_data = conn.execute("SELECT * FROM messages WHERE id = ?", (row["id"],)).fetchone()
            if row_data:
                text = f"""[bold]{row_data['subject']}[/bold]
From: {row_data['from_name'] or ''} <{row_data['from_addr']}>
To: {row_data['to_name'] or ''} <{row_data['to_addr']}>
Date: {row_data['date']}
Account: {row_data['account']}
Seen: {'Yes' if row_data['seen'] else 'No'}

{row_data['body_text'] or '(no body)'}
"""
                self.query_one("#detail", Static).update(text)

    def action_sync(self) -> None:
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
                    })
                    new_count += 1
                except HimalayaError:
                    continue

            conn.commit()
            update_sync_state(conn, acc_name, 1, new_count, 0)

        self.query_messages("")


def run_tui(account: str | None = None, query: str | None = None) -> None:
    MailVaultTUI(account=account, initial_query=query).run()
