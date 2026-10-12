import asyncio

import flet as ft

from .. import __version__
from ..main import StartupOptions
from ..paths import resource_path
from . import theme as t
from .controller import AppController
from .views.connect import ConnectView
from .views.downloads import DownloadsView
from .views.library import LibraryView
from .views.settings import SettingsView

NAV = [
    ("connect", "Connect", "connect"),
    ("downloads", "Downloads", "download"),
    ("library", "Library", "library"),
    ("settings", "Settings", "settings"),
]
POLL_INTERVAL = 0.1


class SnapMemApp:
    def __init__(self, page: ft.Page, opts: StartupOptions) -> None:
        self.page = page
        self.ctrl = AppController(opts)
        self.picker = ft.FilePicker()
        self.views = {
            "connect": ConnectView(self),
            "downloads": DownloadsView(self),
            "library": LibraryView(self),
            "settings": SettingsView(self),
        }
        self.built: dict[str, ft.Control] = {}
        self.current = opts.view if opts.view in self.views else "connect"

    def mount(self) -> None:
        p = self.page
        p.title = "SnapMem"
        p.theme_mode = ft.ThemeMode.DARK
        p.theme = t.build_theme()
        p.dark_theme = t.build_theme()
        p.bgcolor = t.BG
        p.padding = 0
        p.window.width = 1240
        p.window.height = 820
        p.window.min_width = 980
        p.window.min_height = 640
        p.window.icon = str(resource_path("assets", "icons", "app-icon.ico"))

        self.rail = ft.NavigationRail(
            selected_index=[k for k, _, _ in NAV].index(self.current),
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=96,
            bgcolor=t.SURFACE,
            indicator_color="#33FFFC00",
            leading=ft.Container(t.logo(40), padding=ft.Padding.only(top=20, bottom=16)),
            trailing=ft.Container(t.muted(f"v{__version__}" if __version__[:1].isdigit() else "dev build", size=11), padding=ft.Padding.only(top=24)),
            destinations=[
                ft.NavigationRailDestination(icon=t.icon(ic, 22, t.MUTED), selected_icon=t.icon(ic, 22, t.ACCENT), label=label)
                for _, label, ic in NAV
            ],
            on_change=self._on_nav,
            selected_label_text_style=ft.TextStyle(color=t.ACCENT, weight=ft.FontWeight.W_600),
            unselected_label_text_style=ft.TextStyle(color=t.MUTED),
        )
        self.body = ft.Container(padding=ft.Padding.symmetric(horizontal=32, vertical=28), expand=True)
        p.add(ft.Row([self.rail, ft.VerticalDivider(width=1, color=t.BORDER), self.body], spacing=0, expand=True))
        self._show(self.current)
        if self.ctrl.opts.sign_in_on_start:
            self.ctrl.sign_in()
        p.run_task(self._poll)

    def _show(self, name: str) -> None:
        self.current = name
        if name not in self.built:
            self.built[name] = self.views[name].build()
        else:
            self.views[name].refresh({"items", "logs", "status", "auth", "links", "library"})
        self.body.content = self.built[name]
        self.rail.selected_index = [k for k, _, _ in NAV].index(name)
        self.page.update()

    def navigate(self, name: str) -> None:
        self._show(name)

    def redraw(self, changed: set[str]) -> None:
        for name in self.built:
            self.views[name].refresh(changed)
        self.page.update()

    def toast(self, message: str) -> None:
        self.page.show_dialog(ft.SnackBar(ft.Text(message, color=t.TEXT), bgcolor=t.CARD_HI, duration=3000))

    async def _on_nav(self, e) -> None:
        self._show(NAV[int(self.rail.selected_index)][0])

    async def _poll(self) -> None:
        while True:
            changed = self.ctrl.drain()
            if changed:
                try:
                    self.redraw(changed)
                except Exception:
                    return
            await asyncio.sleep(POLL_INTERVAL)


def run_app(opts: StartupOptions, web_port: int | None = None) -> None:
    def main(page: ft.Page) -> None:
        SnapMemApp(page, opts).mount()

    if web_port:
        # Flet's default host binds every interface; the UI can delete files, so keep it on loopback.
        ft.run(main, assets_dir=t.assets_dir(), view=ft.AppView.WEB_BROWSER, port=web_port, host="127.0.0.1")
    else:
        ft.run(main, assets_dir=t.assets_dir())
