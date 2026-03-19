import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk

from .auth import fetch_snapchat_export_urls
from .events import post_event
from .worker import worker_main
from .urls import get_zip_filename_from_url


def setup_sc_dark_theme(style: ttk.Style, root: tk.Tk) -> None:
    """Apply a dark gray + yellow theme to ttk widgets."""
    # Windows ttk themes don't support every color property consistently,
    # but `clam` gives the best chance of getting the look we want.
    bg_root = "#1f1f1f"
    panel_bg = "#262626"
    panel_bg_2 = "#2f2f2f"
    fg = "#eaeaea"
    accent = "#f1c40f"  # SC-like yellow

    root.configure(bg=panel_bg)

    try:
        style.theme_use("clam")
    except tk.TclError:
        # Fall back to whatever theme is available.
        pass

    # Base widget styles.
    style.configure("TFrame", background=panel_bg)
    style.configure("TLabel", background=panel_bg, foreground=fg, font=("Segoe UI", 10))
    style.configure("TSeparator", background=panel_bg, foreground=panel_bg)

    # Buttons.
    style.configure(
        "TButton",
        background=panel_bg_2,
        foreground=fg,
        borderwidth=1,
        focusthickness=1,
        focuscolor=accent,
        padding=(10, 4),
    )
    style.map(
        "TButton",
        background=[("active", panel_bg_2), ("pressed", "#3a3a3a")],
        foreground=[("disabled", "#888888")],
    )

    # Progress bars.
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=panel_bg_2,
        background=accent,
        bordercolor=panel_bg_2,
        lightcolor=accent,
        darkcolor=accent,
    )

    # Treeview.
    style.configure(
        "Treeview",
        background=panel_bg_2,
        fieldbackground=panel_bg_2,
        foreground=fg,
        bordercolor=panel_bg_2,
        rowheight=22,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Treeview.Heading",
        background=panel_bg,
        foreground=accent,
        relief="flat",
        font=("Segoe UI", 10, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", "#3a3a3a")],
        foreground=[("selected", fg)],
    )
    style.configure("Treeview.TScrollbar", background=bg_root)


def configure_window_behavior(root: tk.Tk) -> None:
    """Apply safe, cross-platform Tk window behavior."""
    try:
        root.resizable(False, False)
    except Exception:
        pass
    try:
        # Guard against platform-specific style glitches producing a tiny/empty client area.
        root.minsize(920, 620)
        root.state("normal")
        root.update_idletasks()
    except Exception:
        pass


class DownloaderUI:
    def __init__(
        self,
        root: tk.Tk,
        urls: list[str],
        urls_file: Path,
        min_urls: int,
        timeout_sec: int,
        write_urls_file: bool,
    ):
        self.root = root
        self.urls = urls
        self.urls_file = urls_file
        self.min_urls = min_urls
        self.timeout_sec = timeout_sec
        self.write_urls_file = write_urls_file
        self.refresh_retry_count = 0
        self.refresh_retry_max = 3

        self.stop_event = threading.Event()
        self.q: queue.Queue = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.progress_by_index: dict[int, float] = {}
        self.item_pause_events: dict[int, threading.Event] = {}
        self.item_stop_events: dict[int, threading.Event] = {}
        self.item_paused: dict[int, bool] = {}
        self.item_stopped: dict[int, bool] = {}

        root.title("SC Memories Downloader (ZIP + Unzip + Media Collector)")
        root.geometry("920x620")
        configure_window_behavior(root)

        # Ensure the main background is consistent even for non-ttk widgets.
        try:
            self.root.configure(bg="#262626")
        except Exception:
            pass

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="Ready")
        self.phase_var = tk.StringVar(value="Idle")

        ttk.Label(frm, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(frm, textvariable=self.status_var).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Phase:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(frm, textvariable=self.phase_var).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Separator(frm).grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

        ttk.Label(frm, text="Current progress:").grid(row=3, column=0, sticky="w")
        self.current_percent_var = tk.StringVar(value="0%")
        self.current_pb_frame = ttk.Frame(frm, width=520, height=20)
        self.current_pb_frame.grid(row=3, column=1, sticky="w", pady=(2, 0))

        self.current_pb = ttk.Progressbar(self.current_pb_frame, length=520, mode="determinate", maximum=100)
        self.current_pb.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)

        # ttk.Progressbar can't show text, so we overlay a label in the middle.
        self.current_percent_label = tk.Label(
            self.current_pb_frame,
            textvariable=self.current_percent_var,
            bg="#262626",
            fg="#f1c40f",
            font=("Segoe UI", 10, "bold"),
        )
        self.current_percent_label.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frm, text="Overall zips:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.overall_pb = ttk.Progressbar(frm, length=520, mode="determinate", maximum=100)
        self.overall_pb.grid(row=4, column=1, sticky="w", pady=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

        self.clear_btn = ttk.Button(btns, text="Clear previous data", command=self.clear_previous_data)
        self.clear_btn.pack(side="left")

        self.refresh_btn = ttk.Button(btns, text="Refresh URLs", command=self.refresh_urls)
        self.refresh_btn.pack(side="left", padx=(8, 0))

        self.start_btn = ttk.Button(btns, text="Start", command=self.start)
        self.start_btn.pack(side="left")

        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))

        ttk.Label(frm, text="Download progress per ZIP: (pause/resume/stop in Control column)").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        # Treeview can't embed real ttk.Button widgets per-row; instead we render clickable icons
        # in the "control" column. Click left half to pause/resume, right half to stop.
        self.tree = ttk.Treeview(
            frm,
            columns=("name", "progress", "mb", "rate", "control"),
            show="headings",
            height=7,
        )
        self.tree.heading("name", text="ZIP")
        self.tree.heading("progress", text="%")
        self.tree.heading("mb", text="MB")
        self.tree.heading("rate", text="MB/s")
        self.tree.heading("control", text="Control")
        self.tree.column("name", width=500, stretch=True, anchor="w")
        self.tree.column("progress", width=70, stretch=False, anchor="e")
        self.tree.column("mb", width=110, stretch=False, anchor="e")
        self.tree.column("rate", width=110, stretch=False, anchor="e")
        self.tree.column("control", width=120, stretch=False, anchor="center")
        self.tree.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        # Map 1-based index -> tree iid (string)
        self.zip_names_by_index: dict[int, str] = {i: get_zip_filename_from_url(urls[i - 1]) for i in range(1, len(urls) + 1)}
        for _, zip_name in self.zip_names_by_index.items():
            pass

        for i, zip_name in self.zip_names_by_index.items():
            iid = str(i)
            self.tree.insert("", "end", iid=iid, values=(zip_name, "0%", "0.00 MB", "0.00 MB/s", "||  X"))

        if not urls:
            # Without URLs (hardcoded defaults removed), user must refresh URLs after login/auth.
            self.start_btn.config(state="disabled")
            self.status_var.set("No URLs. Click 'Refresh URLs' to login/auth.")
            self.phase_var.set("Idle")

        # Enable clicking on the control column.
        self.tree.bind("<Button-1>", self.on_tree_click)

        self.log = ScrolledText(frm, height=14, wrap="word")
        # Match the dark theme log styling.
        try:
            self.log.configure(bg="#1f1f1f", fg="#eaeaea", insertbackground="#f1c40f")
        except Exception:
            pass
        self.log.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        frm.rowconfigure(8, weight=1)
        frm.columnconfigure(1, weight=1)

        self.poll_queue()

    def log_line(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")

    def on_tree_click(self, event: tk.Event) -> None:
        """Handle clicks on the Treeview 'control' column.

        Treeview doesn't support real buttons per row, so we interpret the click:
        - click left half in the control cell: pause/resume
        - click right half in the control cell: stop that download
        """
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            idx = int(iid)

            columns = list(self.tree["columns"])
            control_col = "control"
            if control_col not in columns:
                return
            control_col_no = columns.index(control_col) + 1
            col = self.tree.identify_column(event.x)
            if col != f"#{control_col_no}":
                return

            bbox = self.tree.bbox(iid, control_col)
            if not bbox:
                return
            x0, _y0, w, _h = bbox

            if idx not in self.item_pause_events or idx not in self.item_stop_events:
                return  # downloads not started yet
            if self.item_stopped.get(idx, False):
                return

            # Left half => pause/resume. Right half => stop.
            if event.x < x0 + w / 2:
                self.toggle_item_pause(idx)
            else:
                self.stop_item_download(idx)
        except Exception:
            # Never let UI click handling crash the app.
            return

    def toggle_item_pause(self, idx: int) -> None:
        paused = self.item_paused.get(idx, False)
        if paused:
            # Resume
            self.item_pause_events[idx].set()
            self.item_paused[idx] = False
            if self.tree.exists(str(idx)):
                self.tree.set(str(idx), "control", "||  X")
            self.log_line(f"Resumed: {self.tree.set(str(idx), 'name')}")
        else:
            # Pause
            self.item_pause_events[idx].clear()
            self.item_paused[idx] = True
            if self.tree.exists(str(idx)):
                self.tree.set(str(idx), "control", ">   X")
            self.log_line(f"Paused: {self.tree.set(str(idx), 'name')}")

    def stop_item_download(self, idx: int) -> None:
        if self.item_stopped.get(idx, False):
            return
        self.item_stop_events[idx].set()
        self.item_stopped[idx] = True
        # Stop icon state.
        if self.tree.exists(str(idx)):
            self.tree.set(str(idx), "control", "X")
        self.log_line(f"Stopped: {self.tree.set(str(idx), 'name')}")

    def start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        self.clear_btn.config(state="disabled")
        self.progress_by_index = {i: 0.0 for i in range(1, len(self.urls) + 1)}

        # Per-download pause/stop signals.
        self.item_pause_events = {i: threading.Event() for i in range(1, len(self.urls) + 1)}
        self.item_stop_events = {i: threading.Event() for i in range(1, len(self.urls) + 1)}
        for i in self.item_pause_events:
            self.item_pause_events[i].set()  # allow running
            self.item_stop_events[i].clear()
        self.item_paused = {i: False for i in range(1, len(self.urls) + 1)}
        self.item_stopped = {i: False for i in range(1, len(self.urls) + 1)}

        for i in range(1, len(self.urls) + 1):
            iid = str(i)
            if self.tree.exists(iid):
                self.tree.set(iid, "progress", "0%")
                self.tree.set(iid, "mb", "0.00 MB")
                self.tree.set(iid, "rate", "0.00 MB/s")
                self.tree.set(iid, "control", "||  X")
        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.status_var.set("Running")
        self.phase_var.set("Starting...")
        self.log_line("Starting downloads...")

        self.worker_thread = threading.Thread(
            target=worker_main,
            args=(self.urls, self.stop_event, self.item_pause_events, self.item_stop_events, self.q),
            daemon=True,
        )
        self.worker_thread.start()

    def apply_new_urls(self, urls: list[str]) -> None:
        """Replace current URL set and update the ZIP list."""
        self.urls = urls

        # Reset progress tracking.
        self.progress_by_index = {i: 0.0 for i in range(1, len(self.urls) + 1)}

        # Clear and repopulate the table.
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        self.zip_names_by_index = {i: get_zip_filename_from_url(urls[i - 1]) for i in range(1, len(urls) + 1)}
        for i, zip_name in self.zip_names_by_index.items():
            iid = str(i)
            self.tree.insert("", "end", iid=iid, values=(zip_name, "0%", "0.00 MB", "0.00 MB/s", "||  X"))

        self.current_pb["value"] = 0
        self.overall_pb["value"] = 0
        if hasattr(self, "current_percent_var"):
            self.current_percent_var.set("0%")

        if not self.urls:
            self.start_btn.config(state="disabled")
            self.status_var.set("No URLs. Click 'Refresh URLs' to login/auth.")
            self.phase_var.set("Idle")
        else:
            self.start_btn.config(state="normal")
            self.status_var.set("Ready")
            self.phase_var.set("Idle")

    def refresh_urls(self) -> None:
        """Scrape fresh Snapchat URLs in a background thread."""
        if self.worker_thread and self.worker_thread.is_alive():
            return

        # Disable buttons while scraping to avoid concurrent operations.
        self.refresh_btn.config(state="disabled")
        self.clear_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")

        self.status_var.set("Refreshing URLs")
        self.phase_var.set("Scraping Snapchat download page...")
        self.log_line("Refreshing URLs... (log in + wait for exports list)")

        def run() -> None:
            try:
                urls = fetch_snapchat_export_urls(
                    self.urls_file,
                    min_urls=self.min_urls,
                    timeout_sec=self.timeout_sec,
                    write_urls_file=self.write_urls_file,
                )
                post_event(self.q, "urls_refreshed", urls=urls)
            except Exception as e:
                post_event(self.q, "urls_refresh_failed", error=str(e))

        threading.Thread(target=run, daemon=True).start()

    def cancel(self) -> None:
        self.stop_event.set()
        self.status_var.set("Cancelling...")
        self.phase_var.set("Cancelling...")
        self.log_line("Cancel requested.")

    def clear_previous_data(self) -> None:
        import shutil

        if self.worker_thread and self.worker_thread.is_alive():
            return

        if not messagebox.askyesno("Confirm", "Delete previous contents of downloads/, extracted/, and media/?"):
            return

        from .paths import get_script_paths

        paths = get_script_paths()
        for d in (paths.downloads_dir, paths.extracted_dir, paths.media_dir):
            try:
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
                d.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.log_line(f"Clear failed for {d.name}: {e}")
                continue

        self.log_line("Cleared previous data folders.")

    def poll_queue(self) -> None:
        try:
            while True:
                event = self.q.get_nowait()
                etype = event.get("type")
                if etype == "log":
                    self.log_line(event.get("message", ""))
                elif etype == "set_phase":
                    self.phase_var.set(event.get("text", ""))
                elif etype == "current_progress":
                    percent = float(event.get("percent", 0))
                    idx = event.get("index")
                    if idx is None:
                        # Extraction phase sends a single global progress value.
                        self.current_pb["value"] = percent
                        self.current_percent_var.set(f"{percent:.0f}%")
                    else:
                        # Download phase sends per-zip progress; show the average.
                        idx_i = int(idx)
                        self.progress_by_index[idx_i] = percent
                        iid = str(idx_i)
                        if self.tree.exists(iid):
                            bytes_downloaded = event.get("bytes_downloaded")
                            rate_mb_s = event.get("rate_mb_s", 0.0)
                            if isinstance(bytes_downloaded, (int, float)) and bytes_downloaded >= 0:
                                mb_downloaded = bytes_downloaded / (1024 * 1024)
                            else:
                                mb_downloaded = 0.0

                            self.tree.set(iid, "progress", f"{percent:.0f}%")
                            self.tree.set(iid, "mb", f"{mb_downloaded:.2f} MB")
                            self.tree.set(iid, "rate", f"{float(rate_mb_s):.2f} MB/s")

                        if self.progress_by_index:
                            avg = sum(self.progress_by_index.values()) / len(self.progress_by_index)
                            self.current_pb["value"] = avg
                            self.current_percent_var.set(f"{avg:.0f}%")
                elif etype == "overall_progress":
                    self.overall_pb["value"] = float(event.get("percent", 0))
                elif etype == "done":
                    self.status_var.set("Done")
                    self.phase_var.set("Idle")
                    self.cancel_btn.config(state="disabled")
                    msg = event.get("message", "Done.")
                    self.log_line(msg)
                elif etype == "download_stopped":
                    idx = event.get("index")
                    if idx is not None:
                        idx_i = int(idx)
                        self.item_stopped[idx_i] = True
                        self.item_paused[idx_i] = False
                        if self.tree.exists(str(idx_i)):
                            self.tree.set(str(idx_i), "control", "X")
                        self.log_line(f"Stopped ZIP #{idx_i}")
                elif etype == "urls_refreshed":
                    urls = event.get("urls", []) or []
                    if not urls:
                        self.status_var.set("Error")
                        self.phase_var.set("Idle")
                        self.refresh_btn.config(state="normal")
                        self.clear_btn.config(state="normal")
                        self.start_btn.config(state="disabled")
                        self.log_line("Refresh completed but no URLs were found.")
                    else:
                        self.refresh_retry_count = 0
                        self.apply_new_urls(urls)
                        self.status_var.set("Ready")
                        self.phase_var.set("Idle")
                        self.refresh_btn.config(state="normal")
                        self.clear_btn.config(state="normal")
                        self.start_btn.config(state="normal")
                        self.log_line(f"Refreshed {len(urls)} URLs.")
                elif etype == "urls_refresh_failed":
                    err = event.get("error", "Refresh failed.")
                    self.status_var.set("Error")
                    self.phase_var.set("Idle")
                    self.refresh_btn.config(state="normal")
                    self.clear_btn.config(state="normal")
                    self.start_btn.config(state="disabled")
                    self.log_line(f"URL refresh failed: {err}")

                    # Most common case: user hasn't completed login/MFA/captcha or exports are not visible yet.
                    needs_reauth = ("No download ZIP URLs found" in err) or ("Make sure the exports list is visible" in err)
                    if needs_reauth and self.refresh_retry_count < self.refresh_retry_max:
                        retry = messagebox.askyesno(
                            "Login/Auth needed",
                            "I couldn't find the export ZIP links.\n\n"
                            "Please complete login/MFA/captcha in the browser window that opened, then click Yes to retry refreshing URLs.",
                        )
                        if retry:
                            self.refresh_retry_count += 1
                            self.refresh_urls()
                elif etype == "error":
                    self.status_var.set("Error")
                    self.phase_var.set("Idle")
                    self.cancel_btn.config(state="disabled")
                    self.refresh_btn.config(state="normal")
                    self.clear_btn.config(state="normal")
                    self.start_btn.config(state="normal")
                    self.log_line(event.get("message", "Error"))
                else:
                    # Unknown event: ignore
                    pass
        except queue.Empty:
            pass

        self.root.after(200, self.poll_queue)

