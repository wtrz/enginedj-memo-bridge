from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
import subprocess

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QDate, QPoint, Signal, Slot
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


class MainWindow(QMainWindow):
    SETTINGS_ORG = "EngineDN3700Sync"
    SETTINGS_APP = "EngineDN-S3700Sync"
    TABLE_HEADER_STATE_VERSION = 2

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Engine DJ → DN-S3700 ID3 Sync")
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

        mapping_group = QGroupBox("DN-S3700 mapping")
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
        self.sync_button = QPushButton("Sync selected ID3 tags")
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
        root.addWidget(self.table, 1)
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
        result += [(f"Engine Saved Loop {i} → Auto Loop", f"saved_loop:{i}") for i in range(1, 9)]
        return result

    def _loop_sources(self):
        return [("None", "none")] + [
            (f"Engine Saved Loop {i}", f"saved_loop:{i}") for i in range(1, 9)
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
            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if result.needs_update else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(result.status))
            edited = result.track.last_edit_time.strftime("%Y-%m-%d %H:%M") if result.track.last_edit_time else ""
            self.table.setItem(row, 2, QTableWidgetItem(edited))
            self.table.setItem(row, 3, QTableWidgetItem(result.track.artist))
            self.table.setItem(row, 4, QTableWidgetItem(result.track.title))
            self.table.setItem(row, 5, QTableWidgetItem(result.planned_fields.get("DDJ/CUET", "")))
            self.table.setItem(row, 6, QTableWidgetItem(result.current_fields.get("DDJ/CUET", "")))
            self.table.setItem(row, 7, QTableWidgetItem(result.planned_fields.get("DDJ/H1PT", "")))
            self.table.setItem(row, 8, QTableWidgetItem(result.current_fields.get("DDJ/H1PT", "")))
            self.table.setItem(row, 9, QTableWidgetItem(result.planned_fields.get("DDJ/H2PT", "")))
            self.table.setItem(row, 10, QTableWidgetItem(result.current_fields.get("DDJ/H2PT", "")))
            self.table.setItem(row, 11, QTableWidgetItem(result.planned_fields.get("DDJ/H3PT", "")))
            self.table.setItem(row, 12, QTableWidgetItem(result.current_fields.get("DDJ/H3PT", "")))
            self.table.setItem(row, 13, QTableWidgetItem(result.planned_fields.get("DDJ/L1AT_L1BT", "")))
            self.table.setItem(row, 14, QTableWidgetItem(result.current_fields.get("DDJ/L1AT_L1BT", "")))
            self.table.setItem(row, 15, QTableWidgetItem(result.planned_fields.get("DDJ/STUP", "")))
            self.table.setItem(row, 16, QTableWidgetItem(result.current_fields.get("DDJ/STUP", "")))
            self.table.setItem(row, 17, QTableWidgetItem(result.planned_fields.get("DDM/WAVE", "missing")))
            self.table.setItem(row, 18, QTableWidgetItem(result.current_fields.get("DDM/WAVE", "missing")))
            warning_text = "; ".join(result.warnings + ([result.error] if result.error else []))
            self.table.setItem(row, 19, QTableWidgetItem(", ".join(result.differences)))
            self.table.setItem(row, 20, QTableWidgetItem(warning_text))
            self.table.setItem(row, 21, QTableWidgetItem(str(result.track.path)))

    def _selected_result_for_position(self, position: QPoint) -> ScanResult | None:
        item = self.table.itemAt(position)
        if not item:
            return None
        row = item.row()
        if row < 0 or row >= len(self.scan_results):
            return None
        return self.scan_results[row]

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
