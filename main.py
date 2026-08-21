#!/usr/bin/env python3
"""
nameer - GUI (PySide6)

Queue with a live preview of the new name on the left, naming settings on the right, presets in the menu.
Set NAMEER_SELFTEST=<video file> to run a headless smoke test (rename + verify) and exit.
"""
import json
import os
import sys
import time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QIcon, QTextCursor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from config import (APP_NAME, APP_VERSION, CASES, COLLISIONS, DEFAULT_SETTINGS, DEFAULT_TEMPLATE, SEPARATORS,  # noqa: E402
                    TOKENS, VIDEO_EXTENSIONS, WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH)
from utils import childproc  # noqa: E402
from utils.naturalsort import natural_key  # noqa: E402
from nameer import (MediaInfo, app_dir, build_name, collect, ffprobe_version, find_ffprobe, probe,  # noqa: E402
                    process_file, undo)

_BTN = """
    QPushButton { font-size: 14px; font-weight: bold; padding: 8px; background-color: %s; color: %s; border-radius: 5px; }
    QPushButton:hover { background-color: %s; }
    QPushButton:disabled { background-color: #cccccc; color: #666; }
"""
_BAR = """
    QProgressBar { border: 1px solid #c8c8c8; border-radius: 4px; background: #f0f0f0;
                   text-align: center; height: 18px; font-weight: bold; color: #333; }
    QProgressBar::chunk { background-color: %s; border-radius: 3px; }
"""
_STATUS_COLORS = {"pending": "#ffffff", "probing": "#fff3cd", "running": "#fff3cd", "renamed": "#d4edda",
                  "dry-run": "#d1ecf1", "unchanged": "#e2e3e5", "skipped": "#e2e3e5", "failed": "#f8d7da",
                  "stopped": "#e2e3e5", "ready": "#ffffff"}

PRESETS = {
    "classic": {"name": "Classic (codec, resolution, fps, bitrate, audio, languages)",
                "settings": {"template": DEFAULT_TEMPLATE, "separator": "_", "case": "upper"}},
    "short": {"name": "Short (codec, resolution, audio)",
              "settings": {"template": "{name}_{vcodec}_{height}p_{acodec}_{channels}ch", "separator": "_",
                           "case": "upper", "check_iframes": False}},
    "scene": {"name": "Scene style (dots, lower case, HDR + bit depth)",
              "settings": {"template": "{name}.{height}p.{hdr}.{bitdepth}.{vcodec}.{acodec}.{channels}ch.{langs}",
                           "separator": ".", "case": "lower"}},
    "archive": {"name": "Archive (everything incl. duration and size)",
                "settings": {"template": "{name}_{vcodec}_{width}x{height}_{fps}fps_{vbitrate}kbs_{bitdepth}_{hdr}_"
                                         "{acodecs}_{channels}ch_{abitrate}kbs_{langs}_{duration}_{size}_{flags}",
                             "separator": "_", "case": "upper"}},
}


# =============================================================================== workers
class ProbeWorker(QThread):
    """Probes queued files so the table can show the new name before anything is renamed."""
    probed = Signal(int, object, str)      # row, MediaInfo | None, error

    def __init__(self, jobs: List[tuple], settings: Dict, ffprobe: str):
        super().__init__()
        self.jobs, self.settings, self.ffprobe = jobs, settings, ffprobe
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        for row, path in self.jobs:
            if self._stop:
                return
            try:
                info = probe(path, self.ffprobe, self.settings["check_iframes"], self.settings["iframe_seconds"],
                             self.settings["iframe_min"])
                self.probed.emit(row, info, "")
            except Exception as exc:
                self.probed.emit(row, None, str(exc))


class RenameWorker(QThread):
    file_started = Signal(int)
    file_done = Signal(int, str, str, str)   # row, status, new path, message
    log = Signal(str, str)
    finished_all = Signal(int, int, int)     # renamed, failed, total

    def __init__(self, jobs: List[tuple], settings: Dict, ffprobe: str):
        super().__init__()
        self.jobs, self.settings, self.ffprobe = jobs, settings, ffprobe
        self._stop = False

    def request_stop(self):
        self._stop = True

    def run(self):
        renamed = failed = 0
        for n, (row, path) in enumerate(self.jobs):
            if self._stop:
                self.log.emit("WARNING", f"Stopped after {n} of {len(self.jobs)} files")
                for r, _p in self.jobs[n:]:
                    self.file_done.emit(r, "stopped", "", "")
                break
            self.file_started.emit(row)
            res = process_file(path, self.settings, self.ffprobe)
            if res.status == "failed":
                failed += 1
                self.log.emit("ERROR", f"{os.path.basename(path)}: {res.message}")
            elif res.status == "renamed":
                renamed += 1
                self.log.emit("INFO", f"{os.path.basename(path)}  ->  {os.path.basename(res.dst)}")
            elif res.status == "dry-run":
                self.log.emit("INFO", f"[dry run] {os.path.basename(path)}  ->  {os.path.basename(res.dst)}")
            else:
                self.log.emit("DEBUG", f"{os.path.basename(path)}: {res.status} ({res.message})")
            self.file_done.emit(row, res.status, res.dst or "", res.message)
        self.finished_all.emit(renamed, failed, len(self.jobs))


# =============================================================================== widgets
class QueueTable(QTableWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__(0, 3)
        self.setHorizontalHeaderLabels(["Current name", "New name", "Status"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAcceptDrops(True)
        self.setStyleSheet("QTableWidget { border: 2px solid #aaa; border-radius: 5px; background: #f9f9f9; }")

    def dragEnterEvent(self, e: QDragEnterEvent):
        e.accept() if e.mimeData().hasUrls() else e.ignore()

    def dragMoveEvent(self, e):
        e.accept() if e.mimeData().hasUrls() else e.ignore()

    def dropEvent(self, e: QDropEvent):
        if e.mimeData().hasUrls():
            e.accept()
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls()])


# =============================================================================== main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(1180, 760)
        self.qsettings = QSettings(APP_NAME, "Settings")
        self.presets_dir = os.path.join(app_dir(), "presets")
        os.makedirs(self.presets_dir, exist_ok=True)
        self.files: List[str] = []
        self.infos: Dict[int, Optional[MediaInfo]] = {}
        self.controls: Dict[str, QWidget] = {}
        self.worker: Optional[RenameWorker] = None
        self.prober: Optional[ProbeWorker] = None
        self.ffprobe: Optional[str] = None
        self._run_start = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._build_ui()
        self._build_menu()
        self.apply_settings(dict(DEFAULT_SETTINGS))
        self._load_persisted()
        self._wire_preview()
        self._refresh_ffprobe()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._left_panel())
        split.addWidget(self._right_panel())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 460])
        root.addWidget(split, 1)
        self.statusBar().showMessage("Ready")

    def _left_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("<b>Queue</b> — drop video files or folders here; the new name is previewed before anything is renamed"))
        self.table = QueueTable()
        self.table.files_dropped.connect(self.add_paths)
        lay.addWidget(self.table, 3)
        row = QHBoxLayout()
        for text, fn in (("Add files", self.add_files), ("Add folder", self.add_folder),
                         ("Remove", self.remove_selected), ("Clear", self.clear_queue)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        undo_btn = QPushButton("Undo last run in folder…")
        undo_btn.setToolTip("Pick a folder: every rename listed in its nameer-undo.log is reverted")
        undo_btn.clicked.connect(self._undo_folder)
        row.addWidget(undo_btn)
        lay.addLayout(row)

        prog = QGroupBox("Progress")
        pl = QVBoxLayout(prog)
        top = QHBoxLayout()
        self.phase_label = QLabel("Idle")
        self.phase_label.setStyleSheet("font-weight: bold;")
        self.counter_label = QLabel("")
        self.counter_label.setStyleSheet("color: #666;")
        top.addWidget(self.phase_label)
        top.addStretch()
        top.addWidget(self.counter_label)
        pl.addLayout(top)
        self.total_bar = QProgressBar()
        self.total_bar.setStyleSheet(_BAR % "#28a745")
        self.total_bar.setFormat("%v / %m files")
        pl.addWidget(self.total_bar)
        stats = QHBoxLayout()
        self.stat_queued = self._stat(stats, "queued")
        self.stat_renamed = self._stat(stats, "renamed")
        self.stat_flagged = self._stat(stats, "flagged")
        self.stat_elapsed = self._stat(stats, "elapsed")
        pl.addLayout(stats)
        lay.addWidget(prog)

        lay.addWidget(QLabel("<b>Log</b>"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("QTextEdit { font-family: monospace; font-size: 12px; background: #fcfcfc; }")
        lay.addWidget(self.log, 2)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("▶  Rename")
        self.start_btn.setStyleSheet(_BTN % ("#28a745", "white", "#218838"))
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setStyleSheet(_BTN % ("#dc3545", "white", "#c82333"))
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        btns.addWidget(self.start_btn, 2)
        btns.addWidget(self.stop_btn, 1)
        lay.addLayout(btns)
        return w

    @staticmethod
    def _stat(layout, caption) -> QLabel:
        box = QVBoxLayout()
        c = QLabel(caption)
        c.setStyleSheet("color: #888; font-size: 10px;")
        v = QLabel("--")
        v.setStyleSheet("font-weight: bold; font-size: 13px;")
        box.addWidget(c)
        box.addWidget(v)
        layout.addLayout(box)
        return v

    def _right_panel(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._wrap(self._naming_tab()), "Naming")
        self.tabs.addTab(self._wrap(self._checks_tab()), "Checks")
        self.tabs.addTab(self._wrap(self._tools_tab()), "Tools")
        for w in self.controls.values():
            if isinstance(w, QComboBox):
                w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                w.setMinimumContentsLength(8)
            if isinstance(w, (QComboBox, QLineEdit, QSpinBox)):
                w.setMinimumWidth(0)
                w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return self.tabs

    @staticmethod
    def _wrap(widget: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(widget)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return sa

    @staticmethod
    def _hint(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet("color: #666; font-size: 11px;")
        return lab

    def _combo(self, key: str, options: Dict[str, str]) -> QComboBox:
        c = QComboBox()
        for value, label in options.items():
            c.addItem(label, value)
        self.controls[key] = c
        return c

    def _check(self, key: str, text: str, tip: str = "") -> QCheckBox:
        c = QCheckBox(text)
        c.setToolTip(tip)
        self.controls[key] = c
        return c

    def _spin(self, key: str, lo: int, hi: int, suffix: str = "") -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSuffix(suffix)
        self.controls[key] = s
        return s

    def _naming_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        g = QGroupBox("Name template")
        f = QVBoxLayout(g)
        self.template_edit = QLineEdit()
        self.template_edit.setToolTip("Tokens in braces are replaced by the file's properties; anything else is kept literally.")
        self.controls["template"] = self.template_edit
        f.addWidget(self.template_edit)
        row = QHBoxLayout()
        self.token_combo = QComboBox()
        for tok, desc in TOKENS.items():
            self.token_combo.addItem(f"{{{tok}}} — {desc}", tok)
        self.token_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.token_combo.setMinimumContentsLength(8)
        self.token_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        ins = QPushButton("Insert")
        ins.setFixedWidth(60)
        ins.clicked.connect(self._insert_token)
        row.addWidget(self.token_combo, 1)
        row.addWidget(ins)
        f.addLayout(row)
        f.addWidget(self._hint("A token with no value (no audio, unknown language, SDR file with {hdr}) disappears "
                               "together with the text glued to it — {height}p becomes nothing, never just \"p\"."))
        self.example_label = QLabel("")
        self.example_label.setWordWrap(True)
        self.example_label.setStyleSheet("font-family: monospace; font-size: 11px; color: #2c3e50; "
                                         "background: #f4f4f4; padding: 4px; border-radius: 3px;")
        f.addWidget(self.example_label)
        lay.addWidget(g)

        g = QGroupBox("Style")
        f = QFormLayout(g)
        f.addRow("Separator:", self._combo("separator", SEPARATORS))
        f.addRow("Codec case:", self._combo("case", CASES))
        f.addRow("", self._check("strip_old_tags", "Strip tags from an earlier run",
                                 "Recognises a trailing run of nameer tags (H264_1080p_24fps_...) and removes it "
                                 "before renaming, so re-running never doubles the tags."))
        lay.addWidget(g)
        lay.addWidget(self._hint("Spaces in the original name are replaced by the separator. Characters that are "
                                 "illegal in file names are dropped."))

        g = QGroupBox("When the new name already exists")
        f = QFormLayout(g)
        f.addRow("Collision:", self._combo("collision", COLLISIONS))
        lay.addWidget(g)
        lay.addStretch()
        return w

    def _checks_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox("I-frame check")
        f = QFormLayout(g)
        f.addRow("", self._check("check_iframes", "Flag files with too few key frames",
                                 "Decodes the first seconds and counts I-frames. Files with almost none are "
                                 "broken or badly encoded and get an i_frame_issue tag through {flags}."))
        f.addRow("Inspect first:", self._spin("iframe_seconds", 5, 600, " s"))
        f.addRow("Minimum I-frames:", self._spin("iframe_min", 1, 100))
        lay.addWidget(g)
        lay.addWidget(self._hint("The check reads and decodes video, so it is the slow part of probing. Turn it off "
                                 "for quick runs over large collections."))

        g = QGroupBox("Safety")
        f = QVBoxLayout(g)
        f.addWidget(self._check("dry_run", "Dry run — show the new names, rename nothing",
                                "Everything is probed and logged; no file on disk is touched."))
        f.addWidget(self._check("write_undo", "Write nameer-undo.log next to renamed files",
                                "One JSON line per rename. 'Undo last run in folder…' reverts it."))
        f.addWidget(self._check("recurse", "Include sub-folders when a folder is added"))
        lay.addWidget(g)
        lay.addStretch()
        return w

    def _tools_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        g = QGroupBox("ffprobe")
        f = QVBoxLayout(g)
        self.ffprobe_label = QLabel("checking…")
        self.ffprobe_label.setWordWrap(True)
        f.addWidget(self.ffprobe_label)
        row = QHBoxLayout()
        self.ffprobe_edit = QLineEdit()
        self.ffprobe_edit.setPlaceholderText("auto (next to the app, then PATH)")
        self.ffprobe_edit.setToolTip("Leave empty to auto-detect; or point at an ffprobe binary.")
        self.controls["ffprobe_path"] = self.ffprobe_edit
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse_ffprobe)
        recheck = QPushButton("Re-check")
        recheck.clicked.connect(self._refresh_ffprobe)
        row.addWidget(self.ffprobe_edit, 1)
        row.addWidget(browse)
        row.addWidget(recheck)
        f.addLayout(row)
        f.addWidget(self._hint("ffprobe is part of FFmpeg (ffmpeg.org, or `winget install ffmpeg`, `brew install "
                               "ffmpeg`, `apt install ffmpeg`). Dropping ffprobe next to the nameer executable also works."))
        lay.addWidget(g)

        g = QGroupBox("Tokens")
        f = QVBoxLayout(g)
        tok = QTextEdit()
        tok.setReadOnly(True)
        tok.setStyleSheet("font-family: monospace; font-size: 11px;")
        tok.setPlainText("\n".join(f"{{{k}}}".ljust(12) + v for k, v in TOKENS.items()))
        tok.setMinimumHeight(260)
        f.addWidget(tok)
        lay.addWidget(g)
        lay.addStretch()
        return w

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        fm.addAction("Add files…", self.add_files, "Ctrl+O")
        fm.addAction("Add folder…", self.add_folder, "Ctrl+Shift+O")
        fm.addAction("Undo last run in folder…", self._undo_folder)
        fm.addSeparator()
        fm.addAction("Exit", self.close, "Ctrl+Q")
        self.presets_menu = mb.addMenu("&Presets")
        self._rebuild_presets_menu()
        hm = mb.addMenu("&Help")
        hm.addAction("About", self._about)

    def _rebuild_presets_menu(self):
        m = self.presets_menu
        m.clear()
        for key, p in PRESETS.items():
            m.addAction(p["name"], lambda k=key: self._apply_preset(k))
        m.addSeparator()
        user = sorted((f[:-5] for f in os.listdir(self.presets_dir) if f.endswith(".json") and f != "defaults.json"), key=natural_key)
        if user:
            for name in user:
                m.addAction(name, lambda n=name: self._load_preset_file(os.path.join(self.presets_dir, n + ".json")))
            m.addSeparator()
        m.addAction("Save preset…", self._save_preset)
        m.addAction("Delete preset…", self._delete_preset)
        m.addAction("Import preset…", self._import_preset)
        m.addAction("Export preset…", self._export_preset)
        m.addSeparator()
        m.addAction("Save current settings as defaults", self._save_defaults)
        m.addAction("Reset to factory defaults", lambda: self.apply_settings(dict(DEFAULT_SETTINGS)))

    # ------------------------------------------------------------- settings io
    def get_settings(self) -> Dict:
        s = {}
        for key, w in self.controls.items():
            if isinstance(w, QCheckBox):
                s[key] = w.isChecked()
            elif isinstance(w, QComboBox):
                s[key] = w.currentData()
            elif isinstance(w, QSpinBox):
                s[key] = w.value()
            elif isinstance(w, QLineEdit):
                s[key] = w.text().strip()
        if not s.get("template"):
            s["template"] = DEFAULT_TEMPLATE
        return s

    def apply_settings(self, s: Dict):
        for key, w in self.controls.items():
            if key not in s:
                continue
            v = s[key]
            try:
                if isinstance(w, QCheckBox):
                    w.setChecked(bool(v))
                elif isinstance(w, QComboBox):
                    idx = w.findData(v)
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif isinstance(w, QSpinBox):
                    w.setValue(int(v))
                elif isinstance(w, QLineEdit):
                    w.setText("" if v is None else str(v))
                    w.setCursorPosition(0)
            except Exception:
                pass
        self._refresh_preview()

    def _load_persisted(self):
        defaults = os.path.join(self.presets_dir, "defaults.json")
        if os.path.isfile(defaults):
            try:
                with open(defaults, encoding="utf-8") as fh:
                    self.apply_settings(json.load(fh))
            except Exception:
                pass
        raw = self.qsettings.value("settings")
        if raw:
            try:
                self.apply_settings(json.loads(raw))
            except Exception:
                pass
        geo = self.qsettings.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            if QMessageBox.question(self, "Quit", "Renaming is running. Stop and quit?") != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.request_stop()
            self.worker.wait(5000)
        if self.prober and self.prober.isRunning():
            self.prober.request_stop()
            self.prober.wait(5000)
        self.qsettings.setValue("settings", json.dumps(self.get_settings()))
        self.qsettings.setValue("geometry", self.saveGeometry())
        event.accept()

    # ---------------------------------------------------------------- presets
    def _apply_preset(self, key):
        self.apply_settings(PRESETS[key]["settings"])
        self.statusBar().showMessage(f"Preset applied: {PRESETS[key]['name']}")

    def _write_json(self, path: str, data: Dict) -> bool:
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, path)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Preset", f"Could not write {path}:\n{exc}")
            return False

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            if self._write_json(os.path.join(self.presets_dir, name.strip() + ".json"), self.get_settings()):
                self._rebuild_presets_menu()

    def _delete_preset(self):
        user = sorted((f[:-5] for f in os.listdir(self.presets_dir) if f.endswith(".json") and f != "defaults.json"), key=natural_key)
        if not user:
            QMessageBox.information(self, "Presets", "No saved presets.")
            return
        name, ok = QInputDialog.getItem(self, "Delete preset", "Preset:", user, 0, False)
        if ok and name:
            os.remove(os.path.join(self.presets_dir, name + ".json"))
            self._rebuild_presets_menu()

    def _load_preset_file(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                self.apply_settings(json.load(fh))
            self.statusBar().showMessage(f"Preset loaded: {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.warning(self, "Preset", f"Could not read preset:\n{exc}")

    def _import_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import preset", "", "JSON (*.json)")
        if path:
            self._load_preset_file(path)

    def _export_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export preset", "preset.json", "JSON (*.json)")
        if path:
            self._write_json(path, self.get_settings())

    def _save_defaults(self):
        if self._write_json(os.path.join(self.presets_dir, "defaults.json"), self.get_settings()):
            self.statusBar().showMessage("Current settings saved as defaults")

    # ------------------------------------------------------------- ffprobe
    def _browse_ffprobe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Locate ffprobe", "", "ffprobe (ffprobe ffprobe.exe);;All files (*)")
        if path:
            self.ffprobe_edit.setText(path)
            self._refresh_ffprobe()

    def _refresh_ffprobe(self, *_):
        self.ffprobe = find_ffprobe(self.ffprobe_edit.text().strip())
        if self.ffprobe:
            self.ffprobe_label.setText(f"<span style='color:#28a745'>found</span> — {self.ffprobe} "
                                       f"(version {ffprobe_version(self.ffprobe)})")
        else:
            self.ffprobe_label.setText("<span style='color:#c0392b'>not found</span> — install FFmpeg or put ffprobe "
                                       "next to the app, then Re-check.")
            self._append_log("WARNING", "ffprobe not found: nothing can be probed. Install FFmpeg or put ffprobe next to the app.")
        self._reprobe_all()

    # ------------------------------------------------------------- preview
    def _wire_preview(self):
        for key, w in self.controls.items():
            if key in ("check_iframes", "iframe_seconds", "iframe_min"):
                (w.toggled if isinstance(w, QCheckBox) else w.valueChanged).connect(self._reprobe_all)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self._refresh_preview)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._refresh_preview)
            elif isinstance(w, QSpinBox):
                w.valueChanged.connect(self._refresh_preview)
            elif isinstance(w, QLineEdit) and key == "template":
                w.textChanged.connect(self._refresh_preview)
        self.ffprobe_edit.editingFinished.connect(self._refresh_ffprobe)

    def _insert_token(self):
        tok = self.token_combo.currentData()
        self.template_edit.insert(f"{{{tok}}}")
        self.template_edit.setFocus()

    _EXAMPLE = MediaInfo(path="home recording.mkv", vcodec="h264", width=1920, height=1080, fps=23.976,
                         vbitrate=5819, bitdepth=8, hdr="SDR", acodec="aac", acodecs=["aac", "ac3"], channels="5.1",
                         abitrate=384, langs=["eng", "cze"], subs=["eng"], duration=6120, size=4_500_000_000)

    def _refresh_preview(self, *_):
        s = self.get_settings()
        try:
            self.example_label.setText("Example:  home recording.mkv  →  " + build_name(self._EXAMPLE, s))
        except Exception as exc:
            self.example_label.setText(f"Template error: {exc}")
        flagged = 0
        for row, info in self.infos.items():
            if info is None or row >= self.table.rowCount():
                continue
            try:
                new = build_name(info, s)
            except Exception:
                new = "?"
            self.table.item(row, 1).setText(new)
            self.table.item(row, 1).setToolTip(self._info_tip(info))
            if info.flags:
                flagged += 1
            if self.table.item(row, 2).text() in ("ready", "unchanged", "probing"):
                status = "unchanged" if new == os.path.basename(self.files[row]) else "ready"
                self.table.item(row, 2).setText(status)
                self._color_row(row, status)
        self.stat_flagged.setText(str(flagged))

    @staticmethod
    def _info_tip(info: MediaInfo) -> str:
        return (f"{info.vcodec} {info.width}x{info.height} {info.fps:.3f} fps {info.vbitrate} kb/s {info.bitdepth}bit "
                f"{info.hdr}\naudio: {', '.join(info.acodecs) or '-'} {info.channels}ch {info.abitrate} kb/s "
                f"langs: {', '.join(info.langs) or '-'}\nsubs: {', '.join(info.subs) or '-'}\n"
                f"I-frames: {info.iframes if info.iframes is not None else 'not checked'}  flags: {', '.join(info.flags) or '-'}")

    def _reprobe_all(self, *_):
        if self.worker and self.worker.isRunning():
            return
        jobs = [(r, p) for r, p in enumerate(self.files)
                if r < self.table.rowCount() and self.table.item(r, 2).text() not in ("renamed",)]
        self._start_probe(jobs)

    def _start_probe(self, jobs: List[tuple]):
        if self.prober and self.prober.isRunning():
            self.prober.request_stop()
            self.prober.wait(5000)
        if not jobs or not self.ffprobe:
            return
        for row, _p in jobs:
            self.infos[row] = None
            self.table.item(row, 2).setText("probing")
            self._color_row(row, "probing")
        self.phase_label.setText("Probing")
        self.prober = ProbeWorker(jobs, self.get_settings(), self.ffprobe)
        self.prober.probed.connect(self._on_probed)
        self.prober.finished.connect(lambda: self.phase_label.setText("Idle") if not (self.worker and self.worker.isRunning()) else None)
        self.prober.start()

    def _on_probed(self, row: int, info, err: str):
        if row >= self.table.rowCount():
            return
        if info is None:
            self.table.item(row, 1).setText("")
            self.table.item(row, 2).setText("failed")
            self.table.item(row, 2).setToolTip(err)
            self._color_row(row, "failed")
            self._append_log("ERROR", f"{os.path.basename(self.files[row])}: {err}")
            return
        self.infos[row] = info
        self.table.item(row, 2).setText("ready")
        self._refresh_preview()

    # ------------------------------------------------------------------ queue
    def add_paths(self, paths: List[str]):
        norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
        seen = {norm(p) for p in self.files}
        new, dupes = [], 0
        for p in collect(paths, self.controls["recurse"].isChecked()):
            k = norm(p)
            if k in seen:
                dupes += 1
                continue
            seen.add(k)
            new.append(p)
        jobs = []
        for p in new:
            self.files.append(p)
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QTableWidgetItem(os.path.basename(p))
            item.setToolTip(p)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QTableWidgetItem(""))
            self.table.setItem(r, 2, QTableWidgetItem("pending"))
            self._color_row(r, "pending")
            jobs.append((r, p))
        if new:
            msg = f"{len(new)} file(s) added — {len(self.files)} in queue"
            if dupes:
                msg += f" ({dupes} already in queue)"
            self.statusBar().showMessage(msg)
            self.stat_queued.setText(str(len(self.files)))
            self._start_probe(jobs)
        elif dupes:
            self.statusBar().showMessage(f"{dupes} already in queue")
        elif paths:
            self.statusBar().showMessage("No new video files found (" + ", ".join(sorted(VIDEO_EXTENSIONS)) + ")")

    def _color_row(self, row: int, state: str):
        for col in range(3):
            it = self.table.item(row, col)
            if it:
                it.setBackground(QColor(_STATUS_COLORS.get(state, "#ffffff")))

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add video files", "", f"Video ({exts});;All files (*)")
        self.add_paths(files)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder")
        if d:
            self.add_paths([d])

    def _busy(self) -> bool:
        return bool(self.worker and self.worker.isRunning())

    def remove_selected(self):
        if self._busy():
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        if self.prober and self.prober.isRunning():
            self.prober.request_stop()
            self.prober.wait(5000)
        for r in rows:
            self.table.removeRow(r)
            del self.files[r]
        self.infos = {}
        self.stat_queued.setText(str(len(self.files)))
        self._reprobe_all()

    def clear_queue(self):
        if self._busy():
            return
        if self.prober and self.prober.isRunning():
            self.prober.request_stop()
            self.prober.wait(5000)
        self.files.clear()
        self.infos.clear()
        self.table.setRowCount(0)
        self.stat_queued.setText("0")

    def _undo_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder with nameer-undo.log")
        if not d:
            return
        try:
            n = undo(d)
        except Exception as exc:
            QMessageBox.warning(self, "Undo", str(exc))
            return
        self._append_log("INFO", f"Undo: restored {n} file name(s) in {d}")
        QMessageBox.information(self, "Undo", f"Restored {n} file name(s)." if n else "No nameer-undo.log in that folder.")

    # -------------------------------------------------------------- processing
    def start(self):
        if self._busy():
            return
        if not self.files:
            QMessageBox.information(self, APP_NAME, "Add some video files first.")
            return
        if not self.ffprobe:
            QMessageBox.warning(self, APP_NAME, "ffprobe not found. Install FFmpeg or set the path in the Tools tab.")
            return
        if self.prober and self.prober.isRunning():
            self.prober.request_stop()
            self.prober.wait(5000)
        s = self.get_settings()
        jobs = [(r, p) for r, p in enumerate(self.files) if self.table.item(r, 2).text() != "renamed"]
        if not jobs:
            self.statusBar().showMessage("Everything in the queue is already renamed")
            return
        if not s["dry_run"] and s["collision"] == "overwrite":
            if QMessageBox.question(self, "Overwrite", "Collision mode is 'overwrite': an existing file with the target name "
                                    "will be deleted. Continue?") != QMessageBox.StandardButton.Yes:
                return
        self.log.clear()
        self._append_log("INFO", f"{'Dry run' if s['dry_run'] else 'Renaming'}: {len(jobs)} file(s), template {s['template']}")
        self.total_bar.setMaximum(len(jobs))
        self.total_bar.setValue(0)
        self.stat_renamed.setText("0")
        self._run_start = time.time()
        self._timer.start(500)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.phase_label.setText("Dry run" if s["dry_run"] else "Renaming")
        self.worker = RenameWorker(jobs, s, self.ffprobe)
        self.worker.file_started.connect(self._on_file_started)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.log.connect(self._append_log)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.request_stop()
            self.statusBar().showMessage("Stopping after the current file…")

    def _tick(self):
        self.stat_elapsed.setText(f"{time.time() - self._run_start:.0f} s")

    def _on_file_started(self, row: int):
        self.table.item(row, 2).setText("running")
        self._color_row(row, "running")
        self.counter_label.setText(f"{self.total_bar.value() + 1} / {self.total_bar.maximum()}")

    def _on_file_done(self, row: int, status: str, dst: str, message: str):
        self.table.item(row, 2).setText(status)
        self.table.item(row, 2).setToolTip(message)
        self._color_row(row, status)
        if status == "renamed" and dst:
            self.files[row] = dst
            self.table.item(row, 0).setToolTip(f"was: {self.table.item(row, 0).text()}\nnow: {dst}")
            self.table.item(row, 1).setText(os.path.basename(dst))
            self.stat_renamed.setText(str(int(self.stat_renamed.text() or 0) + 1))
        elif dst:
            self.table.item(row, 1).setText(os.path.basename(dst))
        if status != "stopped":
            self.total_bar.setValue(self.total_bar.value() + 1)

    def _on_finished(self, renamed: int, failed: int, total: int):
        self._timer.stop()
        self._tick()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.phase_label.setText("Done")
        self.counter_label.setText("")
        self.total_bar.setValue(self.total_bar.maximum())
        msg = f"Done: {renamed} renamed, {failed} failed, {total} processed"
        self._append_log("INFO", msg)
        self.statusBar().showMessage(msg)
        if self.worker:
            self.worker.wait(5000)
            self.worker.deleteLater()
            self.worker = None

    def _append_log(self, level: str, msg: str):
        color = {"DEBUG": "#888", "INFO": "#2c3e50", "WARNING": "#b8860b", "ERROR": "#c0392b"}.get(level, "#2c3e50")
        safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log.append(f'<span style="color:{color};">{safe}</span>')
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME} {APP_VERSION}</b><br>Rename video files after their real properties.<br><br>"
                          "Probing by ffprobe (FFmpeg). Names are built from a template you control; every run "
                          "writes an undo log.<br><br>"
                          "<a href='https://github.com/hclivess/nameer'>github.com/hclivess/nameer</a>")


# =============================================================================== entry
def main():
    app = QApplication(sys.argv)
    childproc.install_qt_hook(app)
    app.setStyle("Fusion")
    icon = os.path.join(app_dir(), "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    win = MainWindow()
    win.show()
    selftest = os.environ.get("NAMEER_SELFTEST")
    if selftest:
        _selftest(win, selftest)
    sys.exit(app.exec())


def _selftest(win: MainWindow, path: str):
    """Headless smoke test for CI: rename `path` for real, check the new file exists with codec tags in its name."""
    win.apply_settings(dict(DEFAULT_SETTINGS, dry_run=False, check_iframes=True, iframe_seconds=5))
    win.add_paths([path])

    def finished(renamed, failed, total):
        new = win.files[0] if win.files else ""
        ok = renamed == 1 and failed == 0 and os.path.isfile(new) and "fps" in os.path.basename(new)
        print(f"selftest: renamed={renamed} failed={failed} -> {os.path.basename(new)} : {'ok' if ok else 'FAILED'}", flush=True)
        QTimer.singleShot(0, lambda: (win.worker and win.worker.wait(10000), QApplication.exit(0 if ok else 1)))

    def go():
        if not win.ffprobe:
            print("selftest: ffprobe not found", flush=True)
            QApplication.exit(1)
            return
        win.start()
        if not win.worker:
            print("selftest: worker did not start", flush=True)
            QApplication.exit(1)
            return
        win.worker.log.connect(lambda lvl, m: print(f"selftest[{lvl}]: {m}", flush=True))
        win.worker.finished_all.connect(finished)
    QTimer.singleShot(500, go)
    QTimer.singleShot(120_000, lambda: (print("selftest: timeout", flush=True), QApplication.exit(1)))


if __name__ == "__main__":
    main()
