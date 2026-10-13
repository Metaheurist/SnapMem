import flet as ft

from ... import paths as app_paths
from ...settings import Settings
from .. import theme as t

LAYOUT_OPTIONS = [
    ("year_month", "Year / Month   (media/2023/05/...)"),
    ("year", "Year   (media/2023/...)"),
    ("flat", "Flat   (everything in media/)"),
]
MODE_OPTIONS = [
    ("move", "Move files (saves space)"),
    ("copy", "Copy files (keeps extracted/)"),
]


def _dropdown(label: str, value: str, options: list[tuple[str, str]], width: int = 380) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        value=value,
        options=[ft.DropdownOption(key=k, text=v) for k, v in options],
        width=width,
        border_color=t.BORDER,
        focused_border_color=t.ACCENT,
    )


def _row(label: str, help_text: str, control: ft.Control) -> ft.Row:
    return ft.Row(
        [ft.Column([ft.Text(label, size=14, color=t.TEXT, weight=ft.FontWeight.W_600), t.muted(help_text, size=12)], spacing=2, expand=True), control],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=16,
    )


class SettingsView:
    def __init__(self, app) -> None:
        self.app = app
        self.ctrl = app.ctrl

    def build(self) -> ft.Control:
        s = self.ctrl.settings
        self.output_dir = ft.TextField(value=s.output_dir, hint_text=str(app_paths.default_base_dir()), read_only=True, expand=True, border_color=t.BORDER)
        self.layout = _dropdown("Folder layout", s.layout, LAYOUT_OPTIONS)
        self.file_mode = _dropdown("After unzipping", s.file_mode, MODE_OPTIONS)
        self.delete_extracted = ft.Switch(value=s.delete_extracted, active_color=t.ACCENT)
        self.zip_workers = _dropdown("ZIP downloads at once", str(s.max_zip_downloads), [(str(n), str(n)) for n in range(1, 7)], width=200)
        self.memory_workers = _dropdown("Memories at once", str(s.max_memory_downloads), [(str(n), str(n)) for n in (1, 2, 4, 6, 8, 12, 16)], width=200)
        self.rate_limit = ft.TextField(label="Speed limit", value=f"{s.rate_limit_mb_s:g}", suffix="MB/s", width=200, keyboard_type=ft.KeyboardType.NUMBER, border_color=t.BORDER)
        self.min_gap = ft.TextField(label="Gap between requests", value=str(s.min_request_gap_ms), suffix="ms", width=200, keyboard_type=ft.KeyboardType.NUMBER, border_color=t.BORDER)
        self.keep_signed_in = ft.Switch(value=s.keep_signed_in, active_color=t.ACCENT)
        self.write_urls = ft.Switch(value=s.write_urls_file, active_color=t.ACCENT)

        storage = t.card(
            ft.Column(
                [
                    ft.Row([t.icon("folder", 20, t.ACCENT), t.title("Storage", 16)], spacing=10),
                    _row("Output folder", "downloads/, extracted/ and media/ are created here. Empty means next to the app.", ft.Container(width=0)),
                    ft.Row([self.output_dir, t.secondary_button("Browse", "folder", on_click=self._browse), t.secondary_button("Default", None, on_click=self._default_dir)], spacing=10),
                    ft.Row([self.layout, self.file_mode], spacing=16, wrap=True),
                    _row("Delete extracted files after sorting", "Removes extracted/<export>/ once its media is in the library.", self.delete_extracted),
                ],
                spacing=14,
            )
        )
        network = t.card(
            ft.Column(
                [
                    ft.Row([t.icon("download", 20, t.ACCENT), t.title("Downloads", 16)], spacing=10),
                    t.muted("On HTTP 429 or 5xx the app waits and retries, using Retry-After when Snapchat sends it. Lower these if downloads keep getting throttled.", size=12),
                    ft.Row([self.zip_workers, self.memory_workers, self.rate_limit, self.min_gap], spacing=16, wrap=True),
                    t.muted("Speed limit 0 means unlimited. Defaults: 2 ZIPs and 4 Memories at a time, 250 ms between requests.", size=12),
                ],
                spacing=14,
            )
        )
        privacy = t.card(
            ft.Column(
                [
                    ft.Row([t.icon("shield", 20, t.ACCENT), t.title("Privacy", 16)], spacing=10),
                    _row("Keep me signed in", "Saves the Snapchat browser session in your Windows profile.", self.keep_signed_in),
                    _row("Save export links to urls.txt", "The links are signed and identify your export. Leave this off unless you need it.", self.write_urls),
                    ft.Row([t.secondary_button("Sign out now", "signout", on_click=self._sign_out)]),
                ],
                spacing=14,
            )
        )
        danger = t.card(
            ft.Column(
                [
                    ft.Row([t.icon("error", 20, t.DANGER), t.title("Clear data", 16)], spacing=10),
                    _row("Clear previous data", "Deletes downloads/, extracted/ and media/ in the output folder.", t.secondary_button("Clear...", None, on_click=self._confirm_clear, color=t.DANGER)),
                ],
                spacing=14,
            )
        )
        return ft.Column(
            [
                ft.Row([t.title("Settings"), ft.Container(expand=True), t.primary_button("Save settings", "check", on_click=self._save)]),
                storage,
                network,
                privacy,
                danger,
            ],
            spacing=14,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def refresh(self, changed: set[str]) -> None:
        if "auth" in changed:
            self.keep_signed_in.value = self.ctrl.settings.keep_signed_in

    def _collect(self) -> Settings:
        def num(field: ft.TextField, cast, default):
            try:
                return cast(str(field.value).strip() or default)
            except ValueError:
                return default

        return Settings(
            output_dir=self.output_dir.value or "",
            layout=self.layout.value or "year_month",
            file_mode=self.file_mode.value or "move",
            delete_extracted=bool(self.delete_extracted.value),
            max_zip_downloads=int(self.zip_workers.value or 2),
            max_memory_downloads=int(self.memory_workers.value or 4),
            rate_limit_mb_s=num(self.rate_limit, float, 0.0),
            min_request_gap_ms=num(self.min_gap, int, 250),
            keep_signed_in=bool(self.keep_signed_in.value),
            write_urls_file=bool(self.write_urls.value),
        )

    async def _save(self, e) -> None:
        if self.ctrl.running:
            self.app.toast("Settings can be changed once the current job finishes.")
            return
        s = self.ctrl.update_settings(self._collect())
        self.rate_limit.value = f"{s.rate_limit_mb_s:g}"
        self.min_gap.value = str(s.min_request_gap_ms)
        self.app.toast("Settings saved.")
        self.app.redraw({"library", "auth", "links"})

    async def _browse(self, e) -> None:
        path = await self.app.picker.get_directory_path(dialog_title="Choose where SnapMem saves files")
        if path:
            self.output_dir.value = path
            self.app.page.update()

    async def _default_dir(self, e) -> None:
        self.output_dir.value = ""
        self.app.page.update()

    async def _sign_out(self, e) -> None:
        removed = self.ctrl.sign_out()
        self.app.toast("Signed out." if removed else "There was no saved session.")

    async def _confirm_clear(self, e) -> None:
        async def do_clear(ev) -> None:
            self.app.page.pop_dialog()
            if self.ctrl.clear_previous_data():
                self.app.toast("Cleared previous data.")
            else:
                self.app.toast("Wait for the current job to finish first.")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete previous data?"),
            content=ft.Text(f"This deletes downloads/, extracted/ and media/ in\n{self.ctrl.paths.base_dir}"),
            actions=[
                ft.TextButton("Cancel", on_click=lambda ev: self.app.page.pop_dialog()),
                ft.FilledButton("Delete", on_click=do_clear, style=ft.ButtonStyle(bgcolor=t.DANGER, color=t.ON_ACCENT)),
            ],
        )
        self.app.page.show_dialog(dialog)
