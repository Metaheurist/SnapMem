from collections import OrderedDict
from datetime import datetime

import flet as ft

from .. import theme as t
from ..thumbs import thumbnail

LAYOUT_LABELS = {"year_month": "Year / Month", "year": "Year", "flat": "Flat"}
THUMBS_PER_MONTH = 60


class LibraryView:
    def __init__(self, app) -> None:
        self.app = app
        self.ctrl = app.ctrl
        self._loaded_version = -1

    def build(self) -> ft.Control:
        self.stats = t.muted("")
        self.content = ft.Column(spacing=12)
        self.resort_btn = t.secondary_button("Re-sort", "sort", on_click=self._resort)
        self.flatten_btn = t.secondary_button("Flatten", "flatten", on_click=self._flatten)
        header = ft.Row(
            [
                ft.Column([t.title("Library"), self.stats], spacing=2, expand=True),
                t.icon_button("refresh", "Reload", on_click=self._reload),
                self.resort_btn,
                self.flatten_btn,
                t.primary_button("Open folder", "folder", on_click=lambda e: self.ctrl.open_folder()),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.load()
        return ft.Column([header, self.content], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    def refresh(self, changed: set[str]) -> None:
        if "library" in changed and self._loaded_version != self.ctrl.library_version:
            self.load()
        self.resort_btn.disabled = self.ctrl.running
        self.flatten_btn.disabled = self.ctrl.running

    def load(self) -> None:
        self._loaded_version = self.ctrl.library_version
        records = self.ctrl.library()
        layout = LAYOUT_LABELS.get(self.ctrl.settings.layout, self.ctrl.settings.layout)
        counts = {k: sum(1 for r in records if r.kind == k) for k in ("photo", "video", "overlay")}
        self.stats.value = f"{counts['photo']} photo(s), {counts['video']} video(s), {counts['overlay']} overlay(s) - sorted by {layout}"
        self.stats.tooltip = str(self.ctrl.paths.media_dir)
        self.resort_btn.tooltip = f"Move every file into the {layout} layout chosen in Settings"
        self.flatten_btn.tooltip = "Move every file into one folder"

        if not records:
            self.content.controls = [
                t.card(
                    ft.Column(
                        [t.logo(64), t.title("No Memories yet", 18), t.muted("Sign in or import an export on the Connect page. Sorted files show up here.")],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                    ),
                    padding=40,
                )
            ]
            return

        groups: "OrderedDict[str, OrderedDict[str, list]]" = OrderedDict()
        for r in records:
            dt = r.datetime
            groups.setdefault(f"{dt:%Y}", OrderedDict()).setdefault(f"{dt:%m}", []).append(r)

        controls: list[ft.Control] = []
        first = True
        for year, months in groups.items():
            total = sum(len(v) for v in months.values())
            controls.append(ft.Row([t.title(year, 20), t.muted(f"{total} item(s)")], spacing=12, vertical_alignment=ft.CrossAxisAlignment.END))
            for month, recs in months.items():
                controls.append(self._month_tile(year, month, recs, expanded=first))
                first = False
        self.content.controls = controls

    def _month_tile(self, year: str, month: str, recs: list, expanded: bool) -> ft.Control:
        name = datetime(int(year), int(month), 1).strftime("%B %Y")
        grid = ft.GridView(max_extent=132, spacing=8, run_spacing=8, child_aspect_ratio=1.0)
        grid_box = ft.Container(content=grid, height=self._grid_height(len(recs)), padding=ft.Padding.only(top=6))

        def fill() -> None:
            if not grid.controls:
                grid.controls = [self._thumb(r) for r in recs[:THUMBS_PER_MONTH]]

        async def on_change(e) -> None:
            if e.data in (True, "true"):
                fill()
                self.app.page.update()

        if expanded:
            fill()
        extra = f" (showing {THUMBS_PER_MONTH})" if len(recs) > THUMBS_PER_MONTH else ""
        return ft.Container(
            content=ft.ExpansionTile(
                title=ft.Text(name, size=15, weight=ft.FontWeight.W_600, color=t.TEXT),
                subtitle=t.muted(f"{len(recs)} item(s){extra}", size=12),
                controls=[grid_box],
                expanded=expanded,
                on_change=on_change,
                maintain_state=True,
                shape=ft.RoundedRectangleBorder(radius=14),
                collapsed_shape=ft.RoundedRectangleBorder(radius=14),
                icon_color=t.ACCENT,
                collapsed_icon_color=t.MUTED,
            ),
            bgcolor=t.CARD,
            border_radius=ft.BorderRadius.all(14),
            border=ft.Border.all(1, t.BORDER),
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        )

    @staticmethod
    def _grid_height(n: int) -> int:
        shown = min(n, THUMBS_PER_MONTH)
        rows = max(1, -(-shown // 7))
        return min(rows * 140 + 12, 600)

    def _thumb(self, r) -> ft.Control:
        path = self.ctrl.paths.media_dir / r.path
        dt = r.datetime
        data = thumbnail(path) if r.kind != "video" else None
        if data is None:
            inner = ft.Container(
                t.icon("play" if r.kind == "video" else "library", 30, t.ACCENT if r.kind == "video" else t.MUTED),
                bgcolor=t.CARD_HI,
                alignment=ft.Alignment.CENTER,
            )
        else:
            inner = ft.Image(src=data, fit=ft.BoxFit.COVER)
        label = ft.Container(
            content=ft.Text(f"{dt:%d %b %H:%M}", size=10, color=t.TEXT),
            bgcolor="#99000000",
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            border_radius=ft.BorderRadius.all(6),
            left=6,
            bottom=6,
        )
        return ft.Container(
            content=ft.Stack([inner, label], fit=ft.StackFit.EXPAND),
            border_radius=ft.BorderRadius.all(10),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            tooltip=f"{r.kind.title()} - {dt:%Y-%m-%d %H:%M:%S} UTC",
            on_click=lambda e, p=path: self.ctrl.open_folder(p),
            ink=True,
        )

    async def _reload(self, e) -> None:
        self.load()
        self.app.page.update()

    async def _resort(self, e) -> None:
        if self.ctrl.resort_library():
            self.app.toast("Re-sorting your library...")

    async def _flatten(self, e) -> None:
        if self.ctrl.flatten_library():
            self.app.toast("Flattening your library...")
