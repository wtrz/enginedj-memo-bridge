from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
import subprocess

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QDate, QPoint, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .engine_db import EngineDatabase, default_engine_database
from .models import EnginePlaylist, MappingSource, ScanResult, SlotMappings, SourceKind, SyncOptions
from .sync_service import SyncService
from .waveform import ddj_markers_from_positions, decode_ddm_waveform, decode_engine_overview_waveform, waveform_markers_from_sample_offsets


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str)


class Worker(QRunnable):
    def __init__(self, function, *args):
        super().__init__()
        self.function = function
        self.args = args
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.function(*self.args, self.signals.progress.emit)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))


class EngineWaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[tuple[int, int, int]] = []
        self._maximum_point: tuple[int, int, int] = (255, 255, 255)
        self._markers: list[float] = []
        self.setMinimumHeight(120)

    def set_waveform(
        self,
        points: list[tuple[int, int, int]],
        markers: list[float],
        maximum_point: tuple[int, int, int] = (255, 255, 255),
    ):
        self._points = points
        self._maximum_point = maximum_point
        self._markers = [marker for marker in markers if 0.0 <= marker <= 1.0]
        self.update()

    def _build_band_path(self, values: list[float], baseline: float, width: int, scale: float) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(0, baseline)
        for x, value in enumerate(values):
            path.lineTo(x, baseline - (value * scale))
        path.lineTo(width - 1, baseline)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#111418"))
        if not self._points:
            painter.setPen(QColor("#7f8c8d"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No EngineDJ waveform available")
            return

        width = max(self.width(), 1)
        height = max(self.height(), 1)
        baseline = height * 0.82
        count = len(self._points)
        low_values: list[float] = []
        mid_values: list[float] = []
        high_values: list[float] = []
        for x in range(width):
            start = x * count // width
            end = max(start + 1, (x + 1) * count // width)
            bucket = self._points[start:end]
            low = max(point[0] for point in bucket)
            mid = max(point[1] for point in bucket)
            high = max(point[2] for point in bucket)
            combined = max(low, mid, high)
            low_values.append(combined / max(self._maximum_point[0], self._maximum_point[1], self._maximum_point[2], 1))
            mid_values.append(max(low, mid) / max(self._maximum_point[0], self._maximum_point[1], 1))
            high_values.append(high / max(self._maximum_point[2], 1))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1c46dd"))
        painter.drawPath(self._build_band_path(low_values, baseline, width, height * 0.70))
        painter.setBrush(QColor("#1de05f"))
        painter.drawPath(self._build_band_path(mid_values, baseline, width, height * 0.55))
        painter.setBrush(QColor("#f4fff8"))
        painter.drawPath(self._build_band_path(high_values, baseline - 1, width, height * 0.16))

        painter.setPen(QPen(QColor("#31424f"), 1))
        painter.drawLine(0, int(baseline), width, int(baseline))

        marker_pen = QPen(QColor("#ff5a5f"), 2)
        painter.setPen(marker_pen)
        for marker in self._markers:
            x = int(marker * (width - 1))
            painter.drawLine(x, 0, x, height)


class DDJWaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[int] = []
        self._markers: list[float] = []
        self.setMinimumHeight(90)

    def set_waveform(self, values: list[int], markers: list[float]):
        self._values = values
        self._markers = [marker for marker in markers if 0.0 <= marker <= 1.0]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0f1013"))
        if not self._values:
            painter.setPen(QColor("#7f8c8d"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No DDJMMAN waveform available")
            return

        width = max(self.width(), 1)
        height = max(self.height(), 1)
        baseline = height - 10
        count = len(self._values)
        painter.setPen(QPen(QColor("#80aaff"), 1))
        for x in range(width):
            start = x * count // width
            end = max(start + 1, (x + 1) * count // width)
            value = max(self._values[start:end])
            bar_height = (value / 15.0) * (height - 18)
            painter.drawLine(x, int(baseline - bar_height), x, int(baseline))

        painter.setPen(QPen(QColor("#31424f"), 1))
        painter.drawLine(0, int(baseline), width, int(baseline))
        painter.setPen(QPen(QColor("#ff5a5f"), 2))
        for marker in self._markers:
            x = int(marker * (width - 1))
            painter.drawLine(x, 0, x, height)


class MainWindow(QMainWindow):
    SETTINGS_ORG = "EngineDN3700Sync"
    SETTINGS_APP = "EngineDN-S3700Sync"
    TABLE_HEADER_STATE_VERSION = 2
    UPDATE_ROW_COLOR = QColor("#FFF7E6")
    ERROR_ROW_COLOR = QColor("#FDECEC")
    CHANGED_CELL_COLOR = QColor("#FFF2A8")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Engine DJ → DDJMMAN ID3 Sync")
        self.resize(1180, 760)
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self.thread_pool = QThreadPool.globalInstance()
        self.scan_results: list[ScanResult] = []
        self.playlists: list[EnginePlaylist] = []
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        database_group = QGroupBox("Engine DJ database")
        database_layout = QHBoxLayout(database_group)
        self.database_edit = QLineEdit()
        browse_button = QPushButton("Browse…")
        schema_button = QPushButton("Schema report")
        browse_button.clicked.connect(self._browse_database)
        schema_button.clicked.connect(self._show_schema_report)
        database_layout.addWidget(self.database_edit, 1)
        database_layout.addWidget(browse_button)
        database_layout.addWidget(schema_button)
        root.addWidget(database_group)

        filter_group = QGroupBox("Filter")
        filter_layout = QVBoxLayout(filter_group)
        date_filter_layout = QHBoxLayout()
        self.use_date = QCheckBox("Only tracks changed on or after")
        self.use_date.setChecked(True)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate().addMonths(-1))
        date_filter_layout.addWidget(self.use_date)
        date_filter_layout.addWidget(self.date_edit)
        date_filter_layout.addStretch(1)
        filter_layout.addLayout(date_filter_layout)
        playlist_filter_layout = QHBoxLayout()
        self.use_playlist = QCheckBox("Only tracks in EngineDJ playlist")
        self.playlist_combo = QComboBox()
        self.playlist_combo.setEnabled(False)
        playlist_filter_layout.addWidget(self.use_playlist)
        playlist_filter_layout.addWidget(self.playlist_combo, 1)
        filter_layout.addLayout(playlist_filter_layout)
        root.addWidget(filter_group)

        mapping_group = QGroupBox("DDJMMAN mapping")
        mapping_layout = QFormLayout(mapping_group)
        self.cue_combo = self._make_combo(self._cue_sources())
        self.slot1_combo = self._make_combo(self._slot_sources())
        self.slot2_combo = self._make_combo(self._slot_sources())
        self.slot3_combo = self._make_combo(self._slot_sources())
        self.ab_combo = self._make_combo(self._loop_sources())
        self.smart_mapping = QCheckBox("Use smart mapping")
        mapping_layout.addRow("DN Cue", self.cue_combo)
        mapping_layout.addRow("DN Slot 1", self.slot1_combo)
        mapping_layout.addRow("DN Slot 2", self.slot2_combo)
        mapping_layout.addRow("DN Slot 3", self.slot3_combo)
        mapping_layout.addRow("DN A/B loop", self.ab_combo)
        mapping_layout.addRow("", self.smart_mapping)
        self.smart_mapping.toggled.connect(self._update_mapping_controls)
        root.addWidget(mapping_group)

        options_group = QGroupBox("Write options")
        options_layout = QHBoxLayout(options_group)
        self.waveform_missing = QCheckBox("Create waveform when missing")
        self.waveform_missing.setChecked(True)
        self.force_waveform = QCheckBox("Force waveform regeneration")
        self.write_bpm = QCheckBox("Write Denon TBPM")
        self.write_bpm.setChecked(True)
        self.rewrite_metadata = QCheckBox("Rewrite normal metadata")
        self.experimental_loops = QCheckBox("Enable experimental Auto Loop mapping")
        self.experimental_loops.setChecked(True)
        self.backup = QCheckBox("Create full-file backup")
        options_layout.addWidget(self.waveform_missing)
        options_layout.addWidget(self.force_waveform)
        options_layout.addWidget(self.write_bpm)
        options_layout.addWidget(self.rewrite_metadata)
        options_layout.addWidget(self.experimental_loops)
        options_layout.addWidget(self.backup)
        root.addWidget(options_group)

        action_layout = QHBoxLayout()
        self.scan_button = QPushButton("Scan")
        self.sync_button = QPushButton("Sync selected DDJMMAN ID3 tags")
        self.sync_button.setEnabled(False)
        self.scan_button.clicked.connect(self._scan)
        self.sync_button.clicked.connect(self._sync)
        self.use_playlist.toggled.connect(self.playlist_combo.setEnabled)
        self.database_edit.editingFinished.connect(self._reload_playlists)
        action_layout.addWidget(self.scan_button)
        action_layout.addWidget(self.sync_button)
        action_layout.addStretch(1)
        root.addLayout(action_layout)

        self.table = QTableWidget(0, 22)
        self.table.setHorizontalHeaderLabels([
            "Sync", "Status", "Last edit", "Artist", "Title",
            "EngineDJ CUET", "ID3Tag CUET",
            "EngineDJ H1PT", "ID3Tag H1PT",
            "EngineDJ H2PT", "ID3Tag H2PT",
            "EngineDJ H3PT", "ID3Tag H3PT",
            "EngineDJ L1AT + L1BT", "ID3Tag L1AT + L1BT",
            "EngineDJ STUP", "ID3Tag STUP",
            "EngineDJ WAVE", "ID3Tag WAVE",
            "Mappings data", "Warnings", "File"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_context_menu)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table.itemSelectionChanged.connect(self._update_selected_track_details)

        content_layout = QHBoxLayout()
        content_layout.addWidget(self.table, 2)

        details_group = QGroupBox("Selected track details")
        details_layout = QVBoxLayout(details_group)
        self.selected_track_title = QLabel("Select a track to inspect EngineDJ and DDJMMAN data")
        self.selected_track_meta = QLabel("")
        self.selected_track_waveform_status = QLabel("EngineDJ overview waveform: unavailable")
        self.selected_track_waveform = EngineWaveformWidget()
        self.selected_track_ddj_waveform_status = QLabel("DDJMMAN waveform: unavailable")
        self.selected_track_ddj_waveform = DDJWaveformWidget()
        self.selected_track_cues = QListWidget()
        details_layout.addWidget(self.selected_track_title)
        details_layout.addWidget(self.selected_track_meta)
        details_layout.addWidget(self.selected_track_waveform_status)
        details_layout.addWidget(self.selected_track_waveform)
        details_layout.addWidget(self.selected_track_ddj_waveform_status)
        details_layout.addWidget(self.selected_track_ddj_waveform)
        details_layout.addWidget(QLabel("Hot cues"))
        details_layout.addWidget(self.selected_track_cues, 1)

        content_layout.addWidget(details_group, 1)
        root.addLayout(content_layout, 1)
        self._apply_default_column_widths()

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress)
        root.addLayout(status_layout)

    def _cue_sources(self):
        result = [("None", "none"), ("Engine main cue", "main_cue")]
        result += [(f"Engine Hot Cue {i}", f"hot_cue:{i}") for i in range(1, 9)]
        result += [(f"Engine Saved Loop {i} start", f"saved_loop:{i}") for i in range(1, 9)]
        return result

    def _slot_sources(self):
        result = [("None", "none"), ("Engine main cue", "main_cue")]
        result += [(f"Engine Hot Cue {i} → Hot Start", f"hot_cue:{i}") for i in range(1, 9)]
        result += [(f"Engine Saved Loop {i} → Auto Loop start+BPM only", f"saved_loop:{i}") for i in range(1, 9)]
        return result

    def _loop_sources(self):
        return [("None", "none")] + [
            (f"Engine Saved Loop {i} → A/B Loop exact start/end", f"saved_loop:{i}") for i in range(1, 9)
        ]

    def _make_combo(self, entries):
        combo = QComboBox()
        for label, token in entries:
            combo.addItem(label, token)
        return combo

    def _set_combo_token(self, combo: QComboBox, token: str):
        index = combo.findData(token)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _load_settings(self):
        self.database_edit.setText(self.settings.value("database", str(default_engine_database())))
        saved_date = self.settings.value("since_date")
        if saved_date:
            parsed = QDate.fromString(saved_date, "yyyy-MM-dd")
            if parsed.isValid():
                self.date_edit.setDate(parsed)
        defaults = SlotMappings.defaults()
        self._set_combo_token(self.cue_combo, self.settings.value("mapping/cue", defaults.cue.token))
        self._set_combo_token(self.slot1_combo, self.settings.value("mapping/slot1", defaults.slot_1.token))
        self._set_combo_token(self.slot2_combo, self.settings.value("mapping/slot2", defaults.slot_2.token))
        self._set_combo_token(self.slot3_combo, self.settings.value("mapping/slot3", defaults.slot_3.token))
        self._set_combo_token(self.ab_combo, self.settings.value("mapping/ab", defaults.ab_loop.token))
        self.smart_mapping.setChecked(self.settings.value("mapping/smart", False, type=bool))
        self.use_date.setChecked(self.settings.value("use_date", True, type=bool))
        self.use_playlist.setChecked(self.settings.value("use_playlist", False, type=bool))
        self.backup.setChecked(self.settings.value("backup", False, type=bool))
        self._reload_playlists()
        saved_playlist = self.settings.value("playlist_id", "")
        if saved_playlist:
            index = self.playlist_combo.findData(saved_playlist)
            if index >= 0:
                self.playlist_combo.setCurrentIndex(index)
        self.playlist_combo.setEnabled(self.use_playlist.isChecked())
        self._update_mapping_controls(self.smart_mapping.isChecked())
        self._restore_table_header_state()

    def _save_settings(self):
        self.settings.setValue("database", self.database_edit.text())
        self.settings.setValue("since_date", self.date_edit.date().toString("yyyy-MM-dd"))
        self.settings.setValue("use_date", self.use_date.isChecked())
        self.settings.setValue("use_playlist", self.use_playlist.isChecked())
        self.settings.setValue("playlist_id", self.playlist_combo.currentData() or "")
        self.settings.setValue("mapping/cue", self.cue_combo.currentData())
        self.settings.setValue("mapping/slot1", self.slot1_combo.currentData())
        self.settings.setValue("mapping/slot2", self.slot2_combo.currentData())
        self.settings.setValue("mapping/slot3", self.slot3_combo.currentData())
        self.settings.setValue("mapping/ab", self.ab_combo.currentData())
        self.settings.setValue("mapping/smart", self.smart_mapping.isChecked())
        self.settings.setValue("backup", self.backup.isChecked())
        self._save_table_header_state()
        self.settings.sync()

    def _update_mapping_controls(self, smart_enabled: bool):
        for widget in (self.cue_combo, self.slot1_combo, self.slot2_combo, self.slot3_combo, self.ab_combo):
            widget.setEnabled(not smart_enabled)

    def _apply_default_column_widths(self):
        widths = {
            0: 56,
            1: 110,
            2: 135,
            3: 160,
            4: 220,
            5: 90,
            6: 90,
            7: 90,
            8: 90,
            9: 90,
            10: 90,
            11: 90,
            12: 90,
            13: 120,
            14: 120,
            15: 180,
            16: 180,
            17: 100,
            18: 100,
            19: 220,
            20: 260,
            21: 320,
        }
        for column, width in widths.items():
            self.table.setColumnWidth(column, width)

    def _save_table_header_state(self):
        self.settings.setValue("table/header_state", self.table.horizontalHeader().saveState())
        self.settings.setValue("table/header_state_version", self.TABLE_HEADER_STATE_VERSION)

    def _restore_table_header_state(self):
        saved_version = self.settings.value("table/header_state_version", 0, type=int)
        if saved_version != self.TABLE_HEADER_STATE_VERSION:
            self.settings.remove("table/header_state")
            self.settings.setValue("table/header_state_version", self.TABLE_HEADER_STATE_VERSION)
            self._apply_default_column_widths()
            return
        state = self.settings.value("table/header_state")
        if state is not None:
            self.table.horizontalHeader().restoreState(state)

    def _show_header_context_menu(self, position: QPoint):
        header = self.table.horizontalHeader()
        menu = QMenu(self)
        for column in range(self.table.columnCount()):
            title_item = self.table.horizontalHeaderItem(column)
            title = title_item.text() if title_item else f"Column {column + 1}"
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.toggled.connect(lambda checked, column_index=column: self._set_column_visible(column_index, checked))
        menu.exec(header.mapToGlobal(position))

    def _set_column_visible(self, column: int, visible: bool):
        self.table.setColumnHidden(column, not visible)
        self._save_table_header_state()

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    def _browse_database(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Engine DJ m.db", self.database_edit.text(), "SQLite database (m.db *.db)")
        if path:
            self.database_edit.setText(path)
            self._reload_playlists()

    def _show_schema_report(self):
        try:
            report = EngineDatabase(Path(self.database_edit.text())).schema_report()
        except Exception as exc:
            QMessageBox.critical(self, "Schema report", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Engine DJ schema report")
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        details = QTextEdit()
        details.setReadOnly(True)
        details.setPlainText(report)
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _mappings(self) -> SlotMappings:
        return SlotMappings(
            cue=MappingSource.from_token(self.cue_combo.currentData()),
            slot_1=MappingSource.from_token(self.slot1_combo.currentData()),
            slot_2=MappingSource.from_token(self.slot2_combo.currentData()),
            slot_3=MappingSource.from_token(self.slot3_combo.currentData()),
            ab_loop=MappingSource.from_token(self.ab_combo.currentData()),
        )

    def _options(self) -> SyncOptions:
        backup_dir = Path.home() / "Music" / "DN-S3700 Sync Backups"
        return SyncOptions(
            write_waveform_if_missing=self.waveform_missing.isChecked(),
            force_regenerate_waveform=self.force_waveform.isChecked(),
            write_denon_bpm=self.write_bpm.isChecked(),
            rewrite_normal_metadata=self.rewrite_metadata.isChecked(),
            create_backup=self.backup.isChecked(),
            backup_directory=backup_dir,
            experimental_auto_loops=self.experimental_loops.isChecked(),
            smart_mapping=self.smart_mapping.isChecked(),
        )

    def _since(self) -> datetime | None:
        if not self.use_date.isChecked():
            return None
        qdate = self.date_edit.date()
        return datetime.combine(qdate.toPython(), time.min).astimezone()

    def _service(self) -> SyncService:
        return SyncService(Path(self.database_edit.text()), self._mappings(), self._options())

    def _start_worker(self, worker: Worker, finished):
        self.scan_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(finished)
        self.thread_pool.start(worker)

    def _scan(self):
        self._save_settings()
        worker = Worker(self._service().scan, self._since(), self._playlist_id())
        self._start_worker(worker, self._scan_finished)

    def _playlist_id(self) -> str | None:
        if not self.use_playlist.isChecked():
            return None
        return self.playlist_combo.currentData()

    def _reload_playlists(self):
        current = self.playlist_combo.currentData()
        self.playlist_combo.clear()
        try:
            playlists = EngineDatabase(Path(self.database_edit.text())).fetch_playlists()
        except Exception:
            playlists = []
        self.playlists = playlists
        if not playlists:
            self.playlist_combo.addItem("No playlists found", "")
            self.playlist_combo.setEnabled(False)
            return
        for playlist in playlists:
            indent = "    " * playlist.depth
            prefix = "↳ " if playlist.depth else ""
            self.playlist_combo.addItem(f"{indent}{prefix}{playlist.name}", playlist.id)
        restore_id = current or self.settings.value("playlist_id", "")
        if restore_id:
            index = self.playlist_combo.findData(restore_id)
            if index >= 0:
                self.playlist_combo.setCurrentIndex(index)
        self.playlist_combo.setEnabled(self.use_playlist.isChecked())

    def _sync(self):
        for row, result in enumerate(self.scan_results):
            item = self.table.item(row, 0)
            result.selected = bool(item and item.checkState() == Qt.CheckState.Checked)
        worker = Worker(self._service().sync, self.scan_results)
        self._start_worker(worker, self._sync_finished)

    @Slot(int, int, str)
    def _on_progress(self, current: int, total: int, name: str):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self.status_label.setText(f"{current}/{total}: {name}")

    @Slot(str)
    def _on_error(self, message: str):
        self.scan_button.setEnabled(True)
        self.sync_button.setEnabled(bool(self.scan_results))
        self.progress.setVisible(False)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Error", message)

    @Slot(object)
    def _scan_finished(self, results):
        self.scan_results = results
        self._populate_table(results)
        updates = sum(1 for result in results if result.needs_update)
        self.status_label.setText(f"Scanned {len(results)} tracks; {updates} require update")
        self.progress.setVisible(False)
        self.scan_button.setEnabled(True)
        self.sync_button.setEnabled(updates > 0)

    @Slot(object)
    def _sync_finished(self, completed):
        errors = [result for result in completed if result.error]
        self.status_label.setText(f"Synced {len(completed) - len(errors)} tracks; {len(errors)} errors")
        self.progress.setVisible(False)
        self.scan_button.setEnabled(True)
        self.sync_button.setEnabled(False)
        if errors:
            QMessageBox.warning(self, "Sync complete", "Some tracks failed. Scan again to review errors.")
        self._scan()

    def _populate_table(self, results: list[ScanResult]):
        self.table.setRowCount(len(results))
        for row, result in enumerate(results):
            row_color = self.ERROR_ROW_COLOR if result.error else (self.UPDATE_ROW_COLOR if result.needs_update else None)

            def set_cell(column: int, text: str) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                if row_color is not None:
                    item.setBackground(row_color)
                self.table.setItem(row, column, item)
                return item

            def highlight_pair(engine_column: int, id3_column: int, key: str):
                if key in result.differences:
                    engine_item = self.table.item(row, engine_column)
                    id3_item = self.table.item(row, id3_column)
                    if engine_item:
                        engine_item.setBackground(self.CHANGED_CELL_COLOR)
                    if id3_item:
                        id3_item.setBackground(self.CHANGED_CELL_COLOR)

            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if result.needs_update else Qt.CheckState.Unchecked)
            if row_color is not None:
                check.setBackground(row_color)
            self.table.setItem(row, 0, check)
            set_cell(1, result.status)
            edited = result.track.last_edit_time.strftime("%Y-%m-%d %H:%M") if result.track.last_edit_time else ""
            set_cell(2, edited)
            set_cell(3, result.track.artist)
            set_cell(4, result.track.title)
            set_cell(5, result.planned_fields.get("DDJ/CUET", ""))
            set_cell(6, result.current_fields.get("DDJ/CUET", ""))
            set_cell(7, result.planned_fields.get("DDJ/H1PT", ""))
            set_cell(8, result.current_fields.get("DDJ/H1PT", ""))
            set_cell(9, result.planned_fields.get("DDJ/H2PT", ""))
            set_cell(10, result.current_fields.get("DDJ/H2PT", ""))
            set_cell(11, result.planned_fields.get("DDJ/H3PT", ""))
            set_cell(12, result.current_fields.get("DDJ/H3PT", ""))
            set_cell(13, result.planned_fields.get("DDJ/L1AT_L1BT", ""))
            set_cell(14, result.current_fields.get("DDJ/L1AT_L1BT", ""))
            set_cell(15, result.planned_fields.get("DDJ/STUP", ""))
            set_cell(16, result.current_fields.get("DDJ/STUP", ""))
            set_cell(17, result.planned_fields.get("DDM/WAVE_DISPLAY", "missing"))
            set_cell(18, result.current_fields.get("DDM/WAVE_DISPLAY", "missing"))
            warning_text = "; ".join(result.warnings + ([result.error] if result.error else []))
            set_cell(19, ", ".join(result.differences))
            set_cell(20, warning_text)
            set_cell(21, str(result.track.path))

            highlight_pair(5, 6, "DDJ/CUET")
            highlight_pair(7, 8, "DDJ/H1PT")
            highlight_pair(9, 10, "DDJ/H2PT")
            highlight_pair(11, 12, "DDJ/H3PT")
            highlight_pair(13, 14, "DDJ/L1AT")
            highlight_pair(13, 14, "DDJ/L1BT")
            highlight_pair(15, 16, "DDJ/STUP")
            if any(key in result.differences for key in ("DDM/WAVE", "DDM/WAVE regenerate", "DDM/WAVE missing/invalid")):
                engine_wave = self.table.item(row, 17)
                id3_wave = self.table.item(row, 18)
                if engine_wave:
                    engine_wave.setBackground(self.CHANGED_CELL_COLOR)
                if id3_wave:
                    id3_wave.setBackground(self.CHANGED_CELL_COLOR)

    def _selected_result_for_position(self, position: QPoint) -> ScanResult | None:
        item = self.table.itemAt(position)
        if not item:
            return None
        row = item.row()
        if row < 0 or row >= len(self.scan_results):
            return None
        return self.scan_results[row]

    def _selected_result(self) -> ScanResult | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.scan_results):
            return None
        return self.scan_results[row]

    def _update_selected_track_details(self):
        result = self._selected_result()
        if not result:
            self.selected_track_title.setText("Select a track to inspect EngineDJ and DDJMMAN data")
            self.selected_track_meta.setText("")
            self.selected_track_waveform_status.setText("EngineDJ overview waveform: unavailable")
            self.selected_track_waveform.set_waveform([], [])
            self.selected_track_ddj_waveform_status.setText("DDJMMAN waveform: unavailable")
            self.selected_track_ddj_waveform.set_waveform([], [])
            self.selected_track_cues.clear()
            return

        track = result.track
        self.selected_track_title.setText(f"{track.artist or 'Unknown artist'} — {track.title or track.path.name}")
        self.selected_track_meta.setText(
            f"Path: {track.path}\n"
            f"BPM: {track.bpm or '-'}    Key: {track.key or '-'}    Sample rate: {track.sample_rate or '-'}"
        )
        waveform_size = len(track.overview_waveform) if track.overview_waveform else 0
        self.selected_track_waveform_status.setText(
            f"EngineDJ overview waveform: {'available' if waveform_size else 'unavailable'}"
            + (f" ({waveform_size} bytes)" if waveform_size else "")
        )
        waveform = decode_engine_overview_waveform(track.overview_waveform)
        total_samples = waveform.samples_per_point * len(waveform.points)
        sample_offsets: list[float] = []
        if track.main_cue_sample_offset is not None:
            sample_offsets.append(track.main_cue_sample_offset)
        sample_offsets.extend(cue.sample_offset for cue in track.quick_cues)
        markers = waveform_markers_from_sample_offsets(sample_offsets, total_samples)
        self.selected_track_waveform.set_waveform(waveform.points, markers, waveform.maximum_point)
        current_wave_value = result.current_fields.get("DDM/WAVE", "")
        planned_wave_value = result.planned_fields.get("DDM/WAVE", "")
        ddj_fields = result.planned_fields if result.needs_update else result.current_fields
        ddj_bytes = []
        if result.needs_update and planned_wave_value not in {"", "missing"} and not planned_wave_value.startswith("invalid"):
            ddj_bytes = decode_ddm_waveform(planned_wave_value)
        elif current_wave_value not in {"", "missing"} and not current_wave_value.startswith("invalid"):
            ddj_bytes = decode_ddm_waveform(current_wave_value)
        ddj_markers = ddj_markers_from_positions(
            [
                ddj_fields.get("DDJ/CUET", ""),
                ddj_fields.get("DDJ/H1PT", ""),
                ddj_fields.get("DDJ/H2PT", ""),
                ddj_fields.get("DDJ/H3PT", ""),
            ],
            ddj_duration=int(ddj_fields.get("DDJ/DUR", "0") or 0),
        )
        self.selected_track_ddj_waveform_status.setText(
            "DDJMMAN waveform: "
            + (
                f"available ({len(ddj_bytes)} bytes)"
                if ddj_bytes else result.planned_fields.get("DDM/WAVE_DISPLAY", result.current_fields.get("DDM/WAVE_DISPLAY", "missing"))
            )
        )
        self.selected_track_ddj_waveform.set_waveform(ddj_bytes, ddj_markers)
        self.selected_track_cues.clear()
        if track.main_cue_sample_offset is not None:
            self.selected_track_cues.addItem(f"Main cue: sample {track.main_cue_sample_offset:.0f}")
        for cue in sorted(track.quick_cues, key=lambda item: item.slot):
            self.selected_track_cues.addItem(
                f"Hot Cue {cue.slot}: sample {cue.sample_offset:.0f}" + (f" — {cue.label}" if cue.label else "")
            )

    def _show_table_context_menu(self, position: QPoint):
        result = self._selected_result_for_position(position)
        if not result:
            return
        menu = QMenu(self)
        reveal_action = menu.addAction("Reveal in Explorer")
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is reveal_action:
            self._reveal_in_explorer(result.track.path)

    def _reveal_in_explorer(self, path: Path):
        if not path.exists():
            QMessageBox.warning(self, "Reveal in Explorer", f"File not found:\n{path}")
            return
        try:
            subprocess.run(["explorer", "/select,", str(path)], check=False)
        except OSError as exc:
            QMessageBox.critical(self, "Reveal in Explorer", str(exc))


def run_gui() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
