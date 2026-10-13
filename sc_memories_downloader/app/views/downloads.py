import flet as ft

from .. import theme as t
from ..controller import ACTIVE_STATES, ItemView

KIND_ICONS = {"zip_url": "download", "zip_file": "import", "folder": "folder", "memories": "library"}
STAGE_LABELS = {"download": "Downloading", "extract": "Unzipping", "organize": "Sorting"}


class ItemCard:
    def __init__(self, view: "DownloadsView", item: ItemView) -> None:
        self.view = view
        self.id = item.id
        self.title = ft.Text(item.title, size=14, weight=ft.FontWeight.W_600, color=t.TEXT, overflow=ft.TextOverflow.ELLIPSIS)
        self.detail = t.muted("", size=12, overflow=ft.TextOverflow.ELLIPSIS)
        self.bar = ft.ProgressBar(value=0, color=t.ACCENT, bgcolor=t.CARD_HI, bar_height=6, border_radius=ft.BorderRadius.all(3))
        self.size = ft.Text("", size=12, color=t.TEXT, text_align=ft.TextAlign.RIGHT)
        self.rate = t.muted("", size=12, text_align=ft.TextAlign.RIGHT)
        self.state = ft.Container()
        self.pause_btn = ft.IconButton(on_click=self._toggle_pause)
        self.stop_btn = t.icon_button("stop", "Stop this item", on_click=self._stop, color=t.DANGER)
        self.control = t.card(
            ft.Row(
                [
                    ft.Container(t.icon(KIND_ICONS.get(item.kind, "download"), 22, t.ACCENT), padding=10, bgcolor=t.CARD_HI, border_radius=ft.BorderRadius.all(12)),
                    ft.Column([ft.Row([ft.Container(self.title, expand=True), self.state]), self.detail, self.bar], spacing=6, expand=True),
                    ft.Column([self.size, self.rate], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END, width=110),
                    self.pause_btn,
                    self.stop_btn,
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
        )
        self.update(item)

    def update(self, item: ItemView) -> None:
        self.bar.value = item.percent / 100
        stage = STAGE_LABELS.get(item.stage, "")
        if item.done_count is not None and item.total_count:
            self.size.value = f"{item.done_count}/{item.total_count}"
        elif item.bytes:
            self.size.value = t.format_bytes(item.bytes) + (f" / {t.format_bytes(item.total_bytes)}" if item.total_bytes else "")
        else:
            self.size.value = f"{item.percent}%" if item.state in ACTIVE_STATES else ""
        self.rate.value = f"{item.rate_mb_s:.1f} MB/s" if item.state == "running" and item.rate_mb_s > 0 and item.stage == "download" else ""
        detail = item.detail if item.state not in {"running", "queued"} or not stage else f"{stage} - {item.percent}%"
        self.detail.value = detail
        self.state.content = t.chip(t.STATE_LABELS.get(item.state, item.state), t.STATE_COLORS.get(item.state, t.MUTED))
        active = item.state in ACTIVE_STATES
        paused = item.state == "paused"
        self.pause_btn.icon = t.icon("play" if paused else "pause", 18, t.TEXT)
        self.pause_btn.tooltip = "Resume" if paused else "Pause"
        self.pause_btn.visible = active
        self.stop_btn.visible = active

    async def _toggle_pause(self, e) -> None:
        self.view.ctrl.toggle_pause(self.id)
        self.view.app.redraw({"items"})

    async def _stop(self, e) -> None:
        self.view.ctrl.stop_item(self.id)
        self.view.app.redraw({"items"})


class DownloadsView:
    def __init__(self, app) -> None:
        self.app = app
        self.ctrl = app.ctrl
        self.cards: dict[str, ItemCard] = {}

    def build(self) -> ft.Control:
        self.phase = ft.Text("", size=16, weight=ft.FontWeight.W_600, color=t.TEXT)
        self.overall_bar = ft.ProgressBar(value=0, color=t.ACCENT, bgcolor=t.CARD_HI, bar_height=10, border_radius=ft.BorderRadius.all(5))
        self.overall_text = t.muted("")
        self.start_btn = t.primary_button("Start", "play", on_click=self._start)
        self.cancel_btn = t.secondary_button("Cancel", "stop", on_click=self._cancel, color=t.DANGER)
        self.banner = ft.Container()
        self.list = ft.Column(spacing=10)
        self.empty = t.card(
            ft.Row([t.icon("download", 22, t.MUTED), t.muted("Nothing queued yet. Sign in or import files on the Connect page, then press Start.")], spacing=12),
            padding=18,
        )
        self.log_list = ft.ListView(spacing=2, auto_scroll=True, height=150)

        top = t.card(
            ft.Column(
                [
                    ft.Row([ft.Column([self.phase, self.overall_text], spacing=2, expand=True), self.start_btn, self.cancel_btn], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    self.overall_bar,
                ],
                spacing=12,
            )
        )
        log_card = t.card(ft.Column([t.muted("Activity", size=12, weight=ft.FontWeight.W_600), self.log_list], spacing=8), padding=14)
        self.refresh({"items", "logs", "status"})
        return ft.Column(
            [t.title("Downloads"), top, self.banner, self.empty, self.list, log_card],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def refresh(self, changed: set[str]) -> None:
        c = self.ctrl
        if changed & {"items", "status"}:
            ids = list(c.items)
            if list(self.cards) != ids:
                self.cards = {i: self.cards.get(i) or ItemCard(self, c.items[i]) for i in ids}
                self.list.controls = [card.control for card in self.cards.values()]
            for i, card in self.cards.items():
                card.update(c.items[i])
            self.empty.visible = not ids
            if c.running:
                self.phase.value = c.phase
            elif c.last_result:
                self.phase.value = "All done" if c.last_result["ok"] else "Finished with problems"
            else:
                self.phase.value = "Ready"
            overall = c.overall
            self.overall_bar.value = overall
            done = sum(1 for v in c.items.values() if v.state in {"done", "skipped"})
            self.overall_text.value = f"{int(overall * 100)}% - {done}/{len(c.items)} item(s) finished" if c.items else ""
            self.start_btn.visible = not c.running
            self.start_btn.disabled = not c.can_start
            self.cancel_btn.visible = c.running
            self._update_banner()
        if "logs" in changed:
            lines = list(c.logs)[-200:]
            self.log_list.controls = [ft.Text(line, size=12, color=t.MUTED, font_family="Consolas", selectable=True) for line in lines]

    def _update_banner(self) -> None:
        c = self.ctrl
        if c.links_expired and not c.running:
            self.banner.content = t.banner(
                "Snapchat says some links have expired. Sign in again to refresh them, then press Start; finished parts are kept.",
                t.WARNING,
                [t.secondary_button("Refresh links", "refresh", on_click=self._refresh_links)],
            )
        elif c.last_result and not c.running:
            ok = c.last_result["ok"]
            self.banner.content = t.banner(
                c.last_result["message"],
                t.SUCCESS if ok else t.DANGER,
                [
                    t.secondary_button("Open folder", "folder", on_click=lambda e: c.open_folder()),
                    t.primary_button("View library", "library", on_click=lambda e: self.app.navigate("library")),
                ],
            )
        else:
            self.banner.content = None

    async def _start(self, e) -> None:
        self.ctrl.start()
        self.app.redraw({"items", "status"})

    async def _cancel(self, e) -> None:
        self.ctrl.cancel()
        self.app.redraw({"status"})

    async def _refresh_links(self, e) -> None:
        self.ctrl.clear_links()
        self.ctrl.sign_in()
        self.app.navigate("connect")
