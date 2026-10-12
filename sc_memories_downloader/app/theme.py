import flet as ft

from ..paths import resource_path

BG = "#0E0E10"
SURFACE = "#151518"
CARD = "#1C1C21"
CARD_HI = "#24242A"
BORDER = "#2C2C33"
TEXT = "#EDEDF0"
MUTED = "#9B9BA5"
ACCENT = "#FFFC00"
ON_ACCENT = "#111111"
SUCCESS = "#4ADE80"
DANGER = "#F87171"
WARNING = "#FBBF24"
INFO = "#60A5FA"

STATE_COLORS = {
    "queued": MUTED,
    "running": INFO,
    "paused": WARNING,
    "stopped": MUTED,
    "done": SUCCESS,
    "skipped": SUCCESS,
    "failed": DANGER,
    "expired": WARNING,
}
STATE_LABELS = {
    "queued": "Queued",
    "running": "Working",
    "paused": "Paused",
    "stopped": "Stopped",
    "done": "Done",
    "skipped": "Done",
    "failed": "Failed",
    "expired": "Link expired",
}


def build_theme() -> ft.Theme:
    return ft.Theme(color_scheme_seed=ACCENT, use_material3=True)


def svg_path(name: str) -> str:
    """Path relative to the Flet assets dir (`assets/`), so it works in desktop and web mode."""
    if name in {"logo", "logo-mark"}:
        return f"svg/{name}.svg"
    return f"svg/icons/{name}.svg"


def assets_dir() -> str:
    return str(resource_path("assets"))


def icon(name: str, size: int = 20, color: str = TEXT) -> ft.Image:
    return ft.Image(src=svg_path(name), width=size, height=size, color=color, color_blend_mode=ft.BlendMode.SRC_IN)


def logo(size: int = 40) -> ft.Image:
    return ft.Image(src=svg_path("logo-mark"), width=size, height=size)


def card(content: ft.Control, padding: int = 20, expand: bool | int = False, bgcolor: str = CARD) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        bgcolor=bgcolor,
        border_radius=ft.BorderRadius.all(16),
        border=ft.Border.all(1, BORDER),
        expand=expand,
    )


def title(text: str, size: int = 22) -> ft.Text:
    return ft.Text(text, size=size, weight=ft.FontWeight.W_700, color=TEXT)


def muted(text: str, size: int = 13, **kw) -> ft.Text:
    return ft.Text(text, size=size, color=MUTED, **kw)


def _button_content(text: str, icon_name: str | None, color: str) -> ft.Control:
    if not icon_name:
        return ft.Text(text, weight=ft.FontWeight.W_600)
    return ft.Row([icon(icon_name, 18, color), ft.Text(text, weight=ft.FontWeight.W_600)], spacing=8, tight=True)


def primary_button(text: str, icon_name: str | None = None, on_click=None, disabled: bool = False) -> ft.FilledButton:
    return ft.FilledButton(
        content=_button_content(text, icon_name, ON_ACCENT),
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DISABLED: CARD_HI, ft.ControlState.DEFAULT: ACCENT},
            color={ft.ControlState.DISABLED: MUTED, ft.ControlState.DEFAULT: ON_ACCENT},
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding.symmetric(horizontal=18, vertical=14),
        ),
    )


def secondary_button(text: str, icon_name: str | None = None, on_click=None, disabled: bool = False, color: str = TEXT) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        content=_button_content(text, icon_name, color),
        on_click=on_click,
        disabled=disabled,
        style=ft.ButtonStyle(
            color={ft.ControlState.DISABLED: "#5A5A63", ft.ControlState.DEFAULT: color},
            side=ft.BorderSide(1, BORDER),
            shape=ft.RoundedRectangleBorder(radius=10),
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
        ),
    )


def icon_button(name: str, tooltip: str, on_click=None, color: str = TEXT, disabled: bool = False) -> ft.IconButton:
    return ft.IconButton(icon=icon(name, 18, color), tooltip=tooltip, on_click=on_click, disabled=disabled)


def chip(text: str, color: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=11, weight=ft.FontWeight.W_600, color=color),
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=ft.BorderRadius.all(20),
        border=ft.Border.all(1, color),
    )


def banner(text: str, color: str, actions: list[ft.Control] | None = None) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [ft.Container(width=4, height=36, bgcolor=color, border_radius=ft.BorderRadius.all(2)), ft.Text(text, color=TEXT, expand=True), *(actions or [])],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
        ),
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        bgcolor=CARD_HI,
        border_radius=ft.BorderRadius.all(12),
    )


def format_bytes(n: int | None) -> str:
    if not n:
        return "0 MB"
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    return f"{n / 1024**2:.1f} MB"
