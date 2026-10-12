from pathlib import Path

import flet as ft

from .. import theme as t

STEPS = [
    'On Snapchat\'s "Download My Data" page, request an export with "Export your Memories" and "Export JSON Files" turned on.',
    "When Snapchat emails you that it is ready, sign in here. A browser window opens; finish the login there.",
    "SnapMem picks up the export links by itself. Snapchat's exports expire after a few days.",
]


def _step(n: int, text: str) -> ft.Row:
    badge = ft.Container(
        content=ft.Text(str(n), size=12, weight=ft.FontWeight.W_700, color=t.ON_ACCENT),
        width=24,
        height=24,
        alignment=ft.Alignment.CENTER,
        bgcolor=t.ACCENT,
        border_radius=ft.BorderRadius.all(12),
    )
    return ft.Row([badge, ft.Text(text, size=13, color=t.TEXT, expand=True)], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)


class ConnectView:
    def __init__(self, app) -> None:
        self.app = app
        self.ctrl = app.ctrl

    def build(self) -> ft.Control:
        s = self.ctrl.settings
        self.keep_signed_in = ft.Checkbox(label="Keep me signed in on this PC", value=s.keep_signed_in, on_change=self._on_keep_signed_in, active_color=t.ACCENT, check_color=t.ON_ACCENT)
        self.sign_in_btn = t.primary_button("Sign in and find exports", "connect", on_click=self._on_sign_in)
        self.cancel_btn = t.secondary_button("Cancel sign-in", "stop", on_click=lambda e: self.ctrl.cancel_sign_in(), color=t.DANGER)
        self.sign_out_btn = t.secondary_button("Sign out", "signout", on_click=self._on_sign_out)
        self.auth_status = t.muted("")
        self.links_chip = ft.Container()
        self.expired_banner = ft.Container()

        sign_in_card = t.card(
            ft.Column(
                [
                    ft.Row([t.icon("connect", 22, t.ACCENT), t.title("Sign in to Snapchat", 18)], spacing=10),
                    *[_step(i, s_) for i, s_ in enumerate(STEPS, start=1)],
                    ft.Divider(color=t.BORDER, height=8),
                    self.keep_signed_in,
                    t.muted(
                        "Saves the Snapchat session in your Windows user profile. Other programs running as you could read it. Sign out deletes it.",
                        size=12,
                    ),
                    self.expired_banner,
                    ft.Row([self.sign_in_btn, self.cancel_btn, self.sign_out_btn], spacing=10, wrap=True),
                    ft.Row([self.links_chip, self.auth_status], spacing=10, wrap=True),
                ],
                spacing=14,
            ),
            expand=True,
        )

        self.selection_list = ft.Column(spacing=6)
        import_card = t.card(
            ft.Column(
                [
                    ft.Row([t.icon("import", 22, t.ACCENT), t.title("Import files you already have", 18)], spacing=10),
                    t.muted("Already downloaded your export? Pick the ZIP files, an unzipped export folder, or memories_history.json."),
                    ft.Row(
                        [
                            t.secondary_button("ZIP files", "download", on_click=self._pick_zips),
                            t.secondary_button("Export folder", "folder", on_click=self._pick_folder),
                            t.secondary_button("memories_history.json", "import", on_click=self._pick_json),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    self.selection_list,
                ],
                spacing=14,
            ),
            expand=True,
        )

        self.summary = ft.Text("", size=14, color=t.TEXT)
        self.start_btn = t.primary_button("Start", "play", on_click=self._on_start)
        footer = t.card(
            ft.Row([t.icon("shield", 22, t.MUTED), ft.Column([self.summary, t.muted("Files are saved to " + str(self.ctrl.paths.base_dir), size=12)], spacing=2, expand=True), self.start_btn], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=16,
        )

        header = ft.Row(
            [
                t.logo(48),
                ft.Column([t.title("SnapMem", 26), t.muted("Save your Snapchat Memories, sorted by date.", 14)], spacing=2),
            ],
            spacing=16,
        )
        self.refresh({"auth", "links", "status"})
        return ft.Column(
            [header, ft.Row([sign_in_card, import_card], spacing=16, vertical_alignment=ft.CrossAxisAlignment.START), footer],
            spacing=18,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def refresh(self, changed: set[str]) -> None:
        c = self.ctrl
        self.sign_in_btn.visible = not c.auth_running
        self.sign_in_btn.disabled = c.running
        self.cancel_btn.visible = c.auth_running
        self.sign_out_btn.disabled = c.auth_running or not c.has_saved_session
        self.auth_status.value = c.auth_message
        self.links_chip.content = t.chip(f"{len(c.urls)} export link(s) ready", t.SUCCESS) if c.urls else None
        self.expired_banner.content = (
            t.banner("Some export links have expired. Sign in again to get fresh ones.", t.WARNING) if c.links_expired else None
        )

        rows: list[ft.Control] = []
        sel = c.selection
        for p in sel.zip_files:
            rows.append(self._selection_row("download", p.name))
        for d in sel.export_dirs:
            rows.append(self._selection_row("folder", d.name))
        if sel.memories_json:
            rows.append(self._selection_row("import", sel.memories_json.name))
        if rows:
            rows.append(ft.TextButton("Clear selection", on_click=self._clear_selection, style=ft.ButtonStyle(color=t.MUTED)))
        self.selection_list.controls = rows

        parts = []
        if c.urls:
            parts.append(f"{len(c.urls)} export link(s)")
        if sel.zip_files:
            parts.append(f"{len(sel.zip_files)} ZIP file(s)")
        if sel.export_dirs:
            parts.append(f"{len(sel.export_dirs)} folder(s)")
        if sel.memories_json:
            parts.append("memories_history.json")
        self.summary.value = ("Ready: " + ", ".join(parts)) if parts else "Sign in or pick files to get started."
        self.start_btn.disabled = not c.can_start

    def _selection_row(self, icon_name: str, text: str) -> ft.Control:
        return ft.Container(
            content=ft.Row([t.icon(icon_name, 16, t.MUTED), ft.Text(text, size=13, color=t.TEXT, overflow=ft.TextOverflow.ELLIPSIS, expand=True)], spacing=8),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            bgcolor=t.CARD_HI,
            border_radius=ft.BorderRadius.all(8),
        )

    async def _on_keep_signed_in(self, e) -> None:
        s = self.ctrl.settings
        s.keep_signed_in = bool(self.keep_signed_in.value)
        self.ctrl.update_settings(s)

    async def _on_sign_in(self, e) -> None:
        self.ctrl.sign_in()
        self.app.redraw({"auth"})

    async def _on_sign_out(self, e) -> None:
        removed = self.ctrl.sign_out()
        self.app.toast("Signed out." if removed else "There was no saved session.")
        self.app.redraw({"auth"})

    async def _on_start(self, e) -> None:
        if self.ctrl.start():
            self.app.navigate("downloads")

    async def _clear_selection(self, e) -> None:
        self.ctrl.clear_import()
        self.app.redraw({"links"})

    async def _add(self, paths: list[str]) -> None:
        if not paths:
            return
        picked = self.ctrl.add_import([Path(p) for p in paths])
        if picked.errors:
            self.app.toast("; ".join(picked.errors[:2]))
        self.app.redraw({"links"})

    async def _pick_zips(self, e) -> None:
        files = await self.app.picker.pick_files(dialog_title="Choose Snapchat export ZIP files", allowed_extensions=["zip"], allow_multiple=True, file_type=ft.FilePickerFileType.CUSTOM)
        await self._add([f.path for f in files or [] if f.path])

    async def _pick_folder(self, e) -> None:
        path = await self.app.picker.get_directory_path(dialog_title="Choose an unzipped Snapchat export folder")
        await self._add([path] if path else [])

    async def _pick_json(self, e) -> None:
        files = await self.app.picker.pick_files(dialog_title="Choose memories_history.json", allowed_extensions=["json"], file_type=ft.FilePickerFileType.CUSTOM)
        await self._add([f.path for f in files or [] if f.path])
