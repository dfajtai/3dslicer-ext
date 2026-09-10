"""
ConfigEditor
=============

Standalone Qt window for building/editing a study config.json without hand
JSON editing. Covers nearly the whole schema:

  General:        paths, key/table/output-dir columns, batch_mode
  Images:         table (name, csv_column, pattern/strip, type, role,
                   required, preset, opacity, color_table) + per-selected-row
                   "advanced" popup for window_level/threshold/interpolate
  Segmentation:   enabled, reference_image, path_pattern, output_filename,
                   segments table (name, source, csv_column, path_pattern,
                   color via per-selected-row popup)
  Landmarks, Volume rendering, global Window/level, Batch export,
  Segment editor: structured fields
  Defaults / Presets: raw JSON (open-ended, rarely hand-tuned per field)

Opens pre-loaded with whatever config is currently active in the main
module widget (pass initial_path=...). "Load from file..." and "New" both
ask to save first if the form has unsaved edits.
"""

import os
import csv
import json

import qt


DEFAULT_SEGMENT_COLOR = (0.9, 0.9, 0.2)
ROLE_CHOICES = ["(none)", "background", "label", "foreground"]
TYPE_CHOICES = ["volume", "labelmap"]
SOURCE_CHOICES = ["file", "empty"]
OVERWRITE_CHOICES = ["none", "all_segments", "visible_segments"]
BRUSH_SHAPE_CHOICES = ["(unset)", "sphere", "circle"]
COLOR_TABLE_CHOICES = [
    "", "Grey", "Rainbow", "Random", "Labels", "GenericAnatomyColors",
    "Warm1", "Warm2", "Warm3", "Cool1", "Cool2", "Cool3",
    "PET-Heat", "PET-Rainbow", "PET-MaximumIntensityProjection", "PET-DICOM",
    "vtkMRMLColorTableNodeRed", "vtkMRMLColorTableNodeGreen", "vtkMRMLColorTableNodeBlue",
    "vtkMRMLColorTableNodeYellow", "vtkMRMLColorTableNodeCyan", "vtkMRMLColorTableNodeMagenta",
]


def _read_csv_header(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return [h.strip() for h in next(csv.reader(f)) if h.strip()]
    except Exception:
        return []


def _guess_key_columns(header):
    guesses = [h for h in header if h.strip().lower() in ("id", "sid", "specimen", "specimenid")]
    return guesses or (header[:1] if header else [])


def _csv_list(text):
    return [c.strip() for c in text.split(",") if c.strip()]


def _f(text):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class _ImageAdvancedPopup(qt.QDialog):
    """Structured popup for an image row's advanced fields: window_level,
    threshold, interpolate. Replaces free-form JSON with actual fields."""

    WL_MODES = ["(none)", "Auto", "Min / Max", "Window / Level"]

    def __init__(self, parent, data):
        qt.QDialog.__init__(self, parent)
        self.setWindowTitle("Advanced image fields")
        self.resize(460, 380)
        data = dict(data or {})
        layout = qt.QVBoxLayout(self)
        form = qt.QFormLayout()
        layout.addWidget(qt.QLabel("These only apply to THIS image row (on top of defaults/preset)."))
        layout.addLayout(form)

        wl = data.get("window_level") or {}
        self.wlModeCombo = qt.QComboBox()
        self.wlModeCombo.addItems(self.WL_MODES)
        if wl.get("auto"):
            self.wlModeCombo.currentText = "Auto"
        elif "window" in wl or "level" in wl:
            self.wlModeCombo.currentText = "Window / Level"
        elif "min" in wl or "max" in wl:
            self.wlModeCombo.currentText = "Min / Max"
        self.wlModeCombo.setToolTip(
            "Auto: let Slicer auto-window. Min/Max: display range (e.g. CT -150..700).\n"
            "Window/Level: width+center form (e.g. a ratio map with SetWindowLevel(1,2)) -\n"
            "NOT the same numbers as Min/Max, see README.")
        form.addRow("Window/level mode:", self.wlModeCombo)

        self.wlAEdit = qt.QLineEdit("" if wl.get("min", wl.get("window")) is None else str(wl.get("min", wl.get("window"))))
        self.wlALabel = qt.QLabel("Min / Window:")
        form.addRow(self.wlALabel, self.wlAEdit)
        self.wlBEdit = qt.QLineEdit("" if wl.get("max", wl.get("level")) is None else str(wl.get("max", wl.get("level"))))
        self.wlBLabel = qt.QLabel("Max / Level:")
        form.addRow(self.wlBLabel, self.wlBEdit)

        sep1 = qt.QFrame()
        sep1.setFrameShape(qt.QFrame.HLine)
        form.addRow(sep1)

        th = data.get("threshold") or {}
        self.chkThreshold = qt.QCheckBox("Enable threshold")
        self.chkThreshold.checked = bool(th)
        form.addRow(self.chkThreshold)
        self.thMinEdit = qt.QLineEdit("" if th.get("min") is None else str(th["min"]))
        form.addRow("Threshold min:", self.thMinEdit)
        self.thMaxEdit = qt.QLineEdit("" if th.get("max") is None else str(th["max"]))
        form.addRow("Threshold max:", self.thMaxEdit)
        self.chkThresholdApply = qt.QCheckBox("Apply (hide values outside range)")
        self.chkThresholdApply.checked = th.get("apply", True)
        form.addRow(self.chkThresholdApply)

        sep2 = qt.QFrame()
        sep2.setFrameShape(qt.QFrame.HLine)
        form.addRow(sep2)

        self.interpolateCombo = qt.QComboBox()
        self.interpolateCombo.addItems(["(unset)", "on", "off"])
        if "interpolate" in data:
            self.interpolateCombo.currentText = "on" if data["interpolate"] else "off"
        form.addRow("Interpolate:", self.interpolateCombo)

        btnRow = qt.QHBoxLayout()
        btnRow.addStretch(1)
        okBtn = qt.QPushButton("OK")
        okBtn.connect('clicked(bool)', lambda checked=False: self.accept())
        cancelBtn = qt.QPushButton("Cancel")
        cancelBtn.connect('clicked(bool)', lambda checked=False: self.reject())
        btnRow.addWidget(okBtn)
        btnRow.addWidget(cancelBtn)
        layout.addLayout(btnRow)

    def result_dict(self):
        out = {}
        mode = self.wlModeCombo.currentText
        a, b = _f(self.wlAEdit.text), _f(self.wlBEdit.text)
        if mode == "Auto":
            out["window_level"] = {"auto": True}
        elif mode == "Min / Max" and (a is not None or b is not None):
            out["window_level"] = {k: v for k, v in (("min", a), ("max", b)) if v is not None}
        elif mode == "Window / Level" and (a is not None or b is not None):
            out["window_level"] = {k: v for k, v in (("window", a), ("level", b)) if v is not None}

        if self.chkThreshold.checked:
            th = {"apply": self.chkThresholdApply.checked}
            mn, mx = _f(self.thMinEdit.text), _f(self.thMaxEdit.text)
            if mn is not None:
                th["min"] = mn
            if mx is not None:
                th["max"] = mx
            out["threshold"] = th

        if self.interpolateCombo.currentText != "(unset)":
            out["interpolate"] = self.interpolateCombo.currentText == "on"

        return out


class _TextPopup(qt.QDialog):
    """Read-only, scrollable, copyable text popup (help text, examples, CSV columns)."""

    def __init__(self, parent, title, text):
        qt.QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        self.resize(560, 480)
        layout = qt.QVBoxLayout(self)
        edit = qt.QPlainTextEdit()
        edit.plainText = text
        edit.setReadOnly(True)
        layout.addWidget(edit)
        closeBtn = qt.QPushButton("Close")
        closeBtn.connect('clicked(bool)', lambda checked=False: self.close())
        layout.addWidget(closeBtn)


class ConfigEditorDialog(qt.QDialog):

    def __init__(self, parent=None, initial_path=None):
        qt.QDialog.__init__(self, parent)
        self.setWindowTitle("Config Editor")
        self.resize(1180, 720)

        self._current_path = None
        self._preseg_abs_path = ""    # true absolute preseg path, tracked separately from its (possibly relative) display text
        self._dirty = False
        self._image_advanced = []    # per-row extra dict: window_level/threshold/interpolate
        self._segment_colors = []    # per-row [r,g,b] or None

        self._build_ui()

        if initial_path and os.path.exists(initial_path):
            self._load_from_file(initial_path, ask_confirm=False)
        self._dirty = False
        self._updateTitle()

    # ---- top-level UI ----

    def _build_ui(self):
        outer = qt.QVBoxLayout(self)

        topRow = qt.QHBoxLayout()
        newBtn = qt.QPushButton("New")
        newBtn.connect('clicked(bool)', lambda checked=False: self._onNew())
        loadBtn = qt.QPushButton("Load from file...")
        loadBtn.connect('clicked(bool)', lambda checked=False: self._onLoadFromFile())
        helpBtn = qt.QPushButton("Help")
        helpBtn.connect('clicked(bool)', lambda checked=False: self._onShowHelp())
        topRow.addWidget(newBtn)
        topRow.addWidget(loadBtn)
        topRow.addStretch(1)
        topRow.addWidget(helpBtn)
        outer.addLayout(topRow)

        tabs = qt.QTabWidget()
        outer.addWidget(tabs)
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_images_tab(), "Images")
        tabs.addTab(self._build_segmentation_tab(), "Segmentation")
        tabs.addTab(self._build_landmarks_tab(), "Landmarks")
        tabs.addTab(self._build_vr_tab(), "Volume rendering")
        tabs.addTab(self._build_wl_tab(), "Window/level")
        tabs.addTab(self._build_batch_export_tab(), "Batch export")
        tabs.addTab(self._build_segment_editor_tab(), "Segment editor")
        tabs.addTab(self._build_advanced_tab(), "Defaults / Presets (JSON)")
        tabs.addTab(self._build_manual_tab(), "Manual edit config")

        self.outputEdit, outputRow = self._file_row(filter_="JSON files (*.json)", save=True, default_name="config.json")
        form = qt.QFormLayout()
        form.addRow("Output config.json:", outputRow)
        outer.addLayout(form)

        btnRow = qt.QHBoxLayout()
        btnRow.addStretch(1)
        saveBtn = qt.QPushButton("Save config")
        saveBtn.connect('clicked(bool)', lambda checked=False: self._onSave())
        closeBtn = qt.QPushButton("Close")
        closeBtn.connect('clicked(bool)', lambda checked=False: self.close())
        btnRow.addWidget(saveBtn)
        btnRow.addWidget(closeBtn)
        outer.addLayout(btnRow)

        self._connect_dirty_tracking()

    def _connect_dirty_tracking(self):
        for w in self.findChildren(qt.QLineEdit):
            w.textChanged.connect(self._mark_dirty)
        for w in self.findChildren(qt.QCheckBox):
            w.stateChanged.connect(self._mark_dirty)
        for w in self.findChildren(qt.QComboBox):
            w.currentIndexChanged.connect(self._mark_dirty)
        for w in self.findChildren(qt.QPlainTextEdit):
            w.textChanged.connect(self._mark_dirty)
        self.imgTable.itemChanged.connect(self._mark_dirty)
        self.segTable.itemChanged.connect(self._mark_dirty)

    def _mark_dirty(self, *_a):
        self._dirty = True
        self._updateTitle()

    def _updateTitle(self):
        name = os.path.basename(self._current_path) if self._current_path else "(new)"
        self.setWindowTitle(f"Config Editor - {name}{' *' if self._dirty else ''}")

    # ---- helpers ----

    def _file_row(self, on_change=None, filter_="CSV files (*.csv);;All files (*)",
                  save=False, default_name="", directory=False, relative_to=None):
        container = qt.QWidget()
        rowLayout = qt.QHBoxLayout(container)
        rowLayout.setContentsMargins(0, 0, 0, 0)
        edit = qt.QLineEdit()
        browse = qt.QPushButton("Browse...")
        rowLayout.addWidget(edit)
        rowLayout.addWidget(browse)

        def _starting_path():
            current = edit.text.strip()
            if current and not os.path.isabs(current) and relative_to:
                root = relative_to()
                if root:
                    return os.path.join(root, current)
            return current

        def _browse():
            start = _starting_path()
            if directory:
                fname = qt.QFileDialog.getExistingDirectory(self, "Select folder", start)
            elif save:
                fname = qt.QFileDialog.getSaveFileName(self, "Save as", start or default_name, filter_)
            else:
                fname = qt.QFileDialog.getOpenFileName(self, "Select file", start, filter_)
            if not fname:
                return

            display = fname
            if relative_to and not directory:
                root = relative_to()
                if root:
                    try:
                        rel = os.path.relpath(fname, root)
                        if not rel.startswith(".."):
                            display = rel
                    except ValueError:
                        pass  # e.g. different drive on Windows - keep absolute

            edit.text = display
            edit.setToolTip(f"Full path: {fname}")
            if on_change:
                on_change(fname)   # callbacks (e.g. CSV header reading) always get the real absolute path

        browse.connect('clicked(bool)', lambda checked=False: _browse())
        return edit, container

    # ---- General tab ----

    def _build_general_tab(self):
        w = qt.QWidget()
        form = qt.QFormLayout(w)

        self.presegEdit, presegRow = self._file_row(
            on_change=self._onPresegChanged,
            relative_to=lambda: self.studyDirEdit.text.strip())
        self.presegEdit.setToolTip("Shown relative to Study dir below if that's set - hover for the full path.")
        self.presegEdit.editingFinished.connect(
            lambda: self._onPresegChanged(self._resolve_csv_path(self.presegEdit.text)))
        form.addRow("Images / preseg CSV:", presegRow)
        self.dbEdit, dbRow = self._file_row(
            relative_to=lambda: self.studyDirEdit.text.strip() or os.path.dirname(self._preseg_abs_path or ""))
        self.dbEdit.setToolTip("Shown relative to Study dir below (or to the preseg CSV's folder if Study dir is empty) - hover for the full path.")
        form.addRow("Database CSV:", dbRow)

        showColsBtn = qt.QPushButton("Show CSV columns (copyable)...")
        showColsBtn.setToolTip("Reads the header row of both CSVs above and lists all columns - copy names from here into the fields below/Images tab.")
        showColsBtn.connect('clicked(bool)', lambda checked=False: self._onShowCsvColumns())
        form.addRow(showColsBtn)

        self.studyDirEdit, studyDirRow = self._file_row(directory=True)
        self.studyDirEdit.setPlaceholderText("default: preseg CSV's folder")
        self.studyDirEdit.setToolTip("Base folder every relative path in the config resolves against. Leave empty to default to the preseg CSV's own folder.")
        form.addRow("Study dir (optional override):", studyDirRow)

        self.keyColumnsEdit = qt.QLineEdit()
        self.keyColumnsEdit.setPlaceholderText("comma-separated, e.g. ID,measurement")
        self.keyColumnsEdit.setToolTip(
            "The composite specimen ID. MUST exist, with matching values, in BOTH CSVs above - "
            "use 'Show CSV columns...' to see which column names are common to both (likely candidates).")
        form.addRow("Key columns:", self.keyColumnsEdit)
        self.doneColumnEdit = qt.QLineEdit("done")
        self.doneColumnEdit.setToolTip("database.csv column (0/1) marking a specimen as finished - drives table row highlighting and batch export filtering.")
        form.addRow("Done column:", self.doneColumnEdit)
        self.tableColumnsEdit = qt.QLineEdit()
        self.tableColumnsEdit.setPlaceholderText("comma-separated database.csv columns shown in the table")
        self.tableColumnsEdit.setToolTip("Which database.csv columns appear (and are editable) in the main module's specimen table. Any column works, not just done.")
        form.addRow("Table columns:", self.tableColumnsEdit)
        self.outputDirPatternEdit = qt.QLineEdit()
        self.outputDirPatternEdit.setPlaceholderText("comma-separated, e.g. ID,measurement")
        self.outputDirPatternEdit.setToolTip("Key column names joined to build each specimen's output folder under study_dir, e.g. ID,measurement -> study_dir/<ID>/<measurement>/")
        form.addRow("Output dir pattern:", self.outputDirPatternEdit)

        sep = qt.QFrame()
        sep.setFrameShape(qt.QFrame.HLine)
        form.addRow(sep)

        self.chkBatchMode = qt.QCheckBox("Enable batch mode")
        self.chkBatchMode.setToolTip("Shows a batch-select combo in the main module after Initialize Study, filtering specimens by the column below.")
        form.addRow(self.chkBatchMode)
        self.batchColumnEdit = qt.QLineEdit()
        self.batchColumnEdit.setPlaceholderText("database.csv column to group/filter by, e.g. batch")
        form.addRow("Batch column:", self.batchColumnEdit)

        return w

    def _resolve_csv_path(self, text):
        """Resolve a (possibly study-dir-relative) path field to a real
        filesystem path for reading - works whether the value got there via
        Browse (already handled in _file_row) or manual typing/pasting,
        which never went through that relative-path logic."""
        text = (text or "").strip()
        if not text or os.path.isabs(text):
            return text
        study_dir = self.studyDirEdit.text.strip()
        return os.path.join(study_dir, text) if study_dir else text

    def _onShowCsvColumns(self):
        preseg_text = self.presegEdit.text.strip()
        db_text = self.dbEdit.text.strip()
        if not preseg_text and not db_text:
            qt.QMessageBox.information(self, "Config Editor", "Set the preseg and/or database CSV path first.")
            return

        preseg_path = self._resolve_csv_path(preseg_text)
        db_path = self._resolve_csv_path(db_text)
        preseg_header = _read_csv_header(preseg_path) if preseg_path else []
        db_header = _read_csv_header(db_path) if db_path else []
        common = [c for c in preseg_header if c in db_header]

        lines = []
        lines.append(f"PRESEG CSV: {preseg_text or '(not set)'}" + (f"  ->  {preseg_path}" if preseg_path != preseg_text else ""))
        lines.append("  " + (", ".join(preseg_header) if preseg_header else "(could not read - check Study dir / the path above)"))
        lines.append("")
        lines.append(f"DATABASE CSV: {db_text or '(not set)'}" + (f"  ->  {db_path}" if db_path != db_text else ""))
        lines.append("  " + (", ".join(db_header) if db_header else "(could not read - check Study dir / the path above)"))
        lines.append("")
        lines.append("COMMON TO BOTH (likely Key columns candidates):")
        lines.append("  " + (", ".join(common) if common else "(none found - check the paths above)"))
        lines.append("")
        lines.append("Tip: select all (Ctrl+A) and copy (Ctrl+C) any of the lists above to paste")
        lines.append("into Key columns / Table columns / an Images row's CSV column, etc.")

        popup = _TextPopup(self, "CSV columns", "\n".join(lines))
        popup.exec_()

        if not self.keyColumnsEdit.text.strip() and common:
            self.keyColumnsEdit.text = ",".join(_guess_key_columns(common) or common[:1])

    def _onPresegChanged(self, path):
        self._preseg_abs_path = path
        header = _read_csv_header(path)
        if hasattr(self, "quickColumnsTable"):
            self.quickColumnsTable.setRowCount(0)
            key_cols = set(_csv_list(self.keyColumnsEdit.text))
            for col in header:
                if col in key_cols:
                    continue
                row = self.quickColumnsTable.rowCount
                self.quickColumnsTable.insertRow(row)
                nameItem = qt.QTableWidgetItem(col)
                nameItem.setFlags(nameItem.flags() & ~qt.Qt.ItemIsEditable)
                self.quickColumnsTable.setItem(row, 0, nameItem)

                addItem = qt.QTableWidgetItem()
                addItem.setFlags(qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)
                addItem.setCheckState(qt.Qt.Unchecked)
                self.quickColumnsTable.setItem(row, 1, addItem)

                lmItem = qt.QTableWidgetItem()
                lmItem.setFlags(qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)
                lmItem.setCheckState(qt.Qt.Checked if "mask" in col.lower() or "label" in col.lower() else qt.Qt.Unchecked)
                self.quickColumnsTable.setItem(row, 2, lmItem)
        if not self.keyColumnsEdit.text.strip():
            guessed = _guess_key_columns(header)
            if guessed:
                self.keyColumnsEdit.text = ",".join(guessed)

    # ---- Images tab ----

    def _build_images_tab(self):
        w = qt.QWidget()
        layout = qt.QVBoxLayout(w)

        quickGroup = qt.QGroupBox("Quick-add from preseg CSV columns")
        quickLayout = qt.QVBoxLayout(quickGroup)
        quickHint = qt.QLabel("From the preseg CSV header. Check 'Add' for columns to add as image rows; check 'Labelmap' if that column is a mask/label image.")
        quickHint.setWordWrap(True)
        quickLayout.addWidget(quickHint)
        self.quickColumnsTable = qt.QTableWidget(0, 3)
        self.quickColumnsTable.setHorizontalHeaderLabels(["Column", "Add", "Labelmap"])
        self.quickColumnsTable.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.quickColumnsTable.setMaximumHeight(140)
        quickLayout.addWidget(self.quickColumnsTable)
        quickBtn = qt.QPushButton("Add checked columns as image rows")
        quickBtn.connect('clicked(bool)', lambda checked=False: self._onQuickAddImages())
        quickLayout.addWidget(quickBtn)
        layout.addWidget(quickGroup)

        imgHint = qt.QLabel(
            "'Pattern' (regex, e.g. ^seq_.*$) opens ONE image per matching, non-empty preseg.csv "
            "column for a given specimen - 'Strip prefix/suffix' trims that column name into the "
            "image's display name. Leave Pattern empty for a normal single, explicit image. The "
            "'Advanced' column summarizes window/level/threshold/interpolate for that row, if set.")
        imgHint.setWordWrap(True)
        layout.addWidget(imgHint)

        self.imgTable = qt.QTableWidget(0, 12)
        headers = ["Name", "CSV column", "Pattern (regex)", "Strip prefix", "Strip suffix",
                   "Type", "Role", "Required", "Preset", "Opacity", "Color table", "Advanced"]
        header_tips = [
            "Logical name used elsewhere (reference_image, presets, roles).",
            "preseg.csv column holding this image's relative path.",
            "Regex: open one image per matching preseg.csv column instead of a fixed one.",
            "Trim this from the start of the matched column name (Pattern mode only).",
            "Trim this from the end of the matched column name (Pattern mode only).",
            "'volume' (default) or 'labelmap'.",
            "background/label/foreground control slice-view layers; (none) = loaded but not shown as a layer.",
            "If missing/unloadable, initializing the specimen raises an error instead of skipping.",
            "Name of a presets[] entry (Defaults / Presets tab) to inherit visual properties from.",
            "0-1, used when Role is label or foreground.",
            "Slicer color node ID or name, e.g. Grey, Rainbow, vtkMRMLColorTableNodeRed.",
            "Read-only summary of window_level/threshold/interpolate set via 'Edit advanced...' below.",
        ]
        self.imgTable.setHorizontalHeaderLabels(headers)
        for col, tip in enumerate(header_tips):
            hitem = self.imgTable.horizontalHeaderItem(col)
            if hitem:
                hitem.setToolTip(tip)
        self.imgTable.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.imgTable.itemSelectionChanged.connect(self._onImageRowSelected)
        layout.addWidget(self.imgTable)

        btnRow = qt.QHBoxLayout()
        addBtn = qt.QPushButton("Add image")
        addBtn.connect('clicked(bool)', lambda checked=False: self._onAddImage())
        removeBtn = qt.QPushButton("Remove selected")
        removeBtn.connect('clicked(bool)', lambda checked=False: self._onRemoveImage())
        advBtn = qt.QPushButton("Edit advanced (window/level, threshold, interpolate)...")
        advBtn.setToolTip("Opens a form for the SELECTED row's window/level, threshold, and interpolate settings.")
        advBtn.connect('clicked(bool)', lambda checked=False: self._onEditImageAdvanced())
        btnRow.addWidget(addBtn)
        btnRow.addWidget(removeBtn)
        btnRow.addWidget(advBtn)
        btnRow.addStretch(1)
        layout.addLayout(btnRow)

        previewGroup = qt.QGroupBox("Effective settings for the selected row (defaults.image -> preset -> this row, last wins)")
        previewLayout = qt.QVBoxLayout(previewGroup)
        self.imgPreviewEdit = qt.QPlainTextEdit()
        self.imgPreviewEdit.setReadOnly(True)
        self.imgPreviewEdit.setMaximumHeight(110)
        self.imgPreviewEdit.setPlaceholderText("Select a row above to see exactly what settings actually apply to it, after merging.")
        previewLayout.addWidget(self.imgPreviewEdit)
        layout.addWidget(previewGroup)

        return w

    def _onImageRowSelected(self):
        row = self.imgTable.currentRow()
        if row < 0:
            self.imgPreviewEdit.plainText = ""
            return
        self._refresh_image_preview(row)

    def _refresh_preview_if_selected(self):
        row = self.imgTable.currentRow()
        if row >= 0:
            self._refresh_image_preview(row)

    def _refresh_image_preview(self, row):
        own, defaults, preset, preset_name, effective = self._compute_effective_image(row)
        lines = []
        lines.append(f"1) defaults.image:        {json.dumps(defaults) if defaults else '(empty)'}")
        if preset_name:
            lines.append(f"2) preset '{preset_name}':  {json.dumps(preset) if preset else '(not found in presets JSON)'}")
        else:
            lines.append("2) preset:                 (none selected on this row)")
        lines.append(f"3) this row's own fields:  {json.dumps(own)}")
        lines.append("")
        lines.append(f"= EFFECTIVE (what actually applies): {json.dumps(effective)}")
        self.imgPreviewEdit.plainText = "\n".join(lines)

    def _compute_effective_image(self, row):
        """Merge defaults.image -> preset (if the row names one) -> the row's
        own fields, exactly like the engine does at runtime. Returns
        (own, defaults, preset, preset_name, effective)."""
        own = self._read_image_row(row) or {}
        try:
            defaults = json.loads(self.defaultsImageEdit.plainText or "{}")
        except Exception:
            defaults = {}
        preset_name = own.get("preset")
        preset = {}
        if preset_name:
            try:
                presets = json.loads(self.presetsEdit.plainText or "{}")
                preset = presets.get(preset_name) or {}
            except Exception:
                preset = {}
        effective = {}
        effective.update(defaults)
        effective.update(preset)
        effective.update(own)
        return own, defaults, preset, preset_name, effective

    def _onQuickAddImages(self):
        added = 0
        for row in range(self.quickColumnsTable.rowCount):
            addItem = self.quickColumnsTable.item(row, 1)
            if addItem.checkState() == qt.Qt.Checked:
                col = self.quickColumnsTable.item(row, 0).text()
                lmItem = self.quickColumnsTable.item(row, 2)
                d = {"name": col, "csv_column": col}
                if lmItem.checkState() == qt.Qt.Checked:
                    d["type"] = "labelmap"
                self._add_image_row(d)
                addItem.setCheckState(qt.Qt.Unchecked)
                added += 1
        if added == 0:
            qt.QMessageBox.information(self, "Config Editor", "Check 'Add' for at least one column above first.")

    def _add_image_row(self, d):
        row = self.imgTable.rowCount
        self.imgTable.insertRow(row)
        self.imgTable.setItem(row, 0, qt.QTableWidgetItem(d.get("name", "")))
        self.imgTable.setItem(row, 1, qt.QTableWidgetItem(d.get("csv_column", "")))
        self.imgTable.setItem(row, 2, qt.QTableWidgetItem(d.get("pattern", "")))
        self.imgTable.setItem(row, 3, qt.QTableWidgetItem(d.get("strip_prefix", "")))
        self.imgTable.setItem(row, 4, qt.QTableWidgetItem(d.get("strip_suffix", "")))

        typeCombo = qt.QComboBox()
        typeCombo.addItems(TYPE_CHOICES)
        typeCombo.currentText = d.get("type", "volume")
        typeCombo.currentIndexChanged.connect(self._mark_dirty)
        self.imgTable.setCellWidget(row, 5, typeCombo)

        roleCombo = qt.QComboBox()
        roleCombo.addItems(ROLE_CHOICES)
        roleCombo.currentText = d.get("role") or "(none)"
        roleCombo.currentIndexChanged.connect(self._mark_dirty)
        self.imgTable.setCellWidget(row, 6, roleCombo)

        reqItem = qt.QTableWidgetItem()
        reqItem.setFlags(qt.Qt.ItemIsUserCheckable | qt.Qt.ItemIsEnabled | qt.Qt.ItemIsSelectable)
        reqItem.setCheckState(qt.Qt.Checked if d.get("required") else qt.Qt.Unchecked)
        self.imgTable.setItem(row, 7, reqItem)

        presetCombo = qt.QComboBox()
        presetCombo.addItem("")
        presetCombo.addItems(self._get_preset_names())
        wanted_preset = d.get("preset", "")
        if wanted_preset and wanted_preset not in self._get_preset_names():
            presetCombo.addItem(wanted_preset)  # keep an unknown/not-yet-defined preset name visible rather than losing it
        presetCombo.currentText = wanted_preset
        presetCombo.currentIndexChanged.connect(self._mark_dirty)
        self.imgTable.setCellWidget(row, 8, presetCombo)

        self.imgTable.setItem(row, 9, qt.QTableWidgetItem("" if d.get("opacity") is None else str(d.get("opacity"))))

        colorCombo = qt.QComboBox()
        colorCombo.setEditable(True)
        colorCombo.addItems(COLOR_TABLE_CHOICES)
        wanted_color = d.get("color_table", "")
        if wanted_color and wanted_color not in COLOR_TABLE_CHOICES:
            colorCombo.addItem(wanted_color)
        colorCombo.currentText = wanted_color
        colorCombo.currentIndexChanged.connect(self._mark_dirty)
        self.imgTable.setCellWidget(row, 10, colorCombo)

        advItem = qt.QTableWidgetItem("")
        advItem.setFlags(advItem.flags() & ~qt.Qt.ItemIsEditable)
        self.imgTable.setItem(row, 11, advItem)

        adv = {k: d[k] for k in ("window_level", "threshold", "interpolate") if k in d}
        self._image_advanced.insert(row, adv)
        self._update_advanced_indicator(row)
        self._mark_dirty()

    def _get_preset_names(self):
        try:
            return sorted(json.loads(self.presetsEdit.plainText or "{}").keys())
        except Exception:
            return []

    def _refresh_all_preset_combos(self):
        """Re-populate every row's Preset dropdown when presets JSON changes,
        preserving each row's current selection if it's still a valid name."""
        if not hasattr(self, "imgTable"):
            return
        names = self._get_preset_names()
        for row in range(self.imgTable.rowCount):
            combo = self.imgTable.cellWidget(row, 8)
            if combo is None:
                continue
            current = combo.currentText
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            combo.addItems(names)
            if current and current not in names:
                combo.addItem(current)
            combo.currentText = current
            combo.blockSignals(False)

    def _summarize_advanced(self, adv):
        if not adv:
            return ""
        parts = []
        wl = adv.get("window_level")
        if wl:
            if wl.get("auto"):
                parts.append("WL:auto")
            elif "window" in wl or "level" in wl:
                parts.append(f"WL:{wl.get('window','?')}/{wl.get('level','?')}(w/l)")
            else:
                parts.append(f"WL:{wl.get('min','?')}/{wl.get('max','?')}")
        th = adv.get("threshold")
        if th:
            parts.append(f"thr:{th.get('min','?')}-{th.get('max','?')}")
        if "interpolate" in adv:
            parts.append("interp:" + ("on" if adv["interpolate"] else "off"))
        return ", ".join(parts)

    def _update_advanced_indicator(self, row):
        nameItem = self.imgTable.item(row, 0)
        advItem = self.imgTable.item(row, 11)
        adv = self._image_advanced[row] if row < len(self._image_advanced) else {}
        summary = self._summarize_advanced(adv)
        if advItem:
            advItem.setText(summary)
        if nameItem:
            if adv:
                nameItem.setToolTip("Advanced: " + json.dumps(adv))
                nameItem.setBackground(qt.QColor(230, 245, 255))
            else:
                nameItem.setToolTip("")
                nameItem.setBackground(qt.QColor(255, 255, 255))

    def _onAddImage(self):
        self._add_image_row({})

    def _onRemoveImage(self):
        rows = sorted(set(i.row() for i in self.imgTable.selectedIndexes()), reverse=True)
        for r in rows:
            self.imgTable.removeRow(r)
            if 0 <= r < len(self._image_advanced):
                del self._image_advanced[r]
        self._mark_dirty()

    def _onEditImageAdvanced(self):
        row = self.imgTable.currentRow()
        if row < 0:
            qt.QMessageBox.information(self, "Config Editor", "Select an image row first.")
            return
        popup = _ImageAdvancedPopup(self, self._image_advanced[row])
        if popup.exec_():
            self._image_advanced[row] = popup.result_dict()
            self._update_advanced_indicator(row)
            self._refresh_image_preview(row)
            self._mark_dirty()

    # ---- Segmentation tab ----

    def _build_segmentation_tab(self):
        w = qt.QWidget()
        layout = qt.QVBoxLayout(w)
        form = qt.QFormLayout()
        self.chkSegEnabled = qt.QCheckBox("Enabled")
        form.addRow(self.chkSegEnabled)
        self.segReferenceImageEdit = qt.QLineEdit()
        self.segReferenceImageEdit.setToolTip(
            "The 'name' of one of your images[] entries (Images tab) - used as the "
            "geometry reference for the segmentation, e.g. 'mask' or 't1'.")
        form.addRow("Reference image (name):", self.segReferenceImageEdit)
        self.segPathPatternEdit = qt.QLineEdit()
        self.segPathPatternEdit.setPlaceholderText("e.g. {ID}/{segment_name}.nii.gz - default naming for segments without their own path")
        self.segPathPatternEdit.setToolTip(
            "Fallback file-naming template used for any segment row that has no CSV column "
            "and no path pattern of its own. Placeholders: {segment_name} and any key_column "
            "or database/preseg CSV column name, e.g. {ID}, {measurement}.\n"
            "Example: {ID}/{measurement}/{ID}-{segment_name}.nii.gz\n"
            "Leave empty if every segment is 'empty' (manual) or has its own csv_column.")
        form.addRow("Path pattern (default):", self.segPathPatternEdit)
        self.segOutputFilenameEdit = qt.QLineEdit("segment.seg.nrrd")
        self.segOutputFilenameEdit.setToolTip("Filename (inside each specimen's output folder) the segmentation is saved to/loaded from.")
        form.addRow("Output filename:", self.segOutputFilenameEdit)
        layout.addLayout(form)

        self.segTable = qt.QTableWidget(0, 5)
        seg_headers = ["Name", "Source", "CSV column", "Path pattern", "Color"]
        seg_tips = [
            "Segment name as it appears in the segmentation.",
            "'file': try csv_column / path pattern, falling back to empty if unresolved. 'empty': never try a file - always a manual placeholder.",
            "preseg.csv column holding this segment's label image path (Source=file).",
            "Overrides the segmentation-level default path pattern for just this segment.",
            "Click 'Set color for selected...' below to pick.",
        ]
        self.segTable.setHorizontalHeaderLabels(seg_headers)
        for col, tip in enumerate(seg_tips):
            hitem = self.segTable.horizontalHeaderItem(col)
            if hitem:
                hitem.setToolTip(tip)
        self.segTable.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        layout.addWidget(self.segTable)

        btnRow = qt.QHBoxLayout()
        addBtn = qt.QPushButton("Add segment")
        addBtn.connect('clicked(bool)', lambda checked=False: self._onAddSegment())
        removeBtn = qt.QPushButton("Remove selected")
        removeBtn.connect('clicked(bool)', lambda checked=False: self._onRemoveSegment())
        colorBtn = qt.QPushButton("Set color for selected...")
        colorBtn.connect('clicked(bool)', lambda checked=False: self._onPickSegmentColor())
        btnRow.addWidget(addBtn)
        btnRow.addWidget(removeBtn)
        btnRow.addWidget(colorBtn)
        btnRow.addStretch(1)
        layout.addLayout(btnRow)

        return w

    def _add_segment_row(self, d):
        row = self.segTable.rowCount
        self.segTable.insertRow(row)
        self.segTable.setItem(row, 0, qt.QTableWidgetItem(d.get("name", f"segment_{row + 1}")))
        srcCombo = qt.QComboBox()
        srcCombo.addItems(SOURCE_CHOICES)
        srcCombo.currentText = d.get("source", "file")
        srcCombo.currentIndexChanged.connect(self._mark_dirty)
        self.segTable.setCellWidget(row, 1, srcCombo)
        self.segTable.setItem(row, 2, qt.QTableWidgetItem(d.get("csv_column", "")))
        self.segTable.setItem(row, 3, qt.QTableWidgetItem(d.get("path_pattern", "")))
        colorItem = qt.QTableWidgetItem(str(d.get("color", "")) or "")
        colorItem.setFlags(colorItem.flags() & ~qt.Qt.ItemIsEditable)
        self.segTable.setItem(row, 4, colorItem)
        color = d.get("color")
        self._segment_colors.insert(row, list(color) if color else list(DEFAULT_SEGMENT_COLOR))
        self._apply_segment_color_display(row)
        self._mark_dirty()

    def _apply_segment_color_display(self, row):
        rgb = self._segment_colors[row]
        r, g, b = (int(round(c * 255)) for c in rgb)
        item = self.segTable.item(row, 4)
        item.setBackground(qt.QColor(r, g, b))
        item.setText(f"{rgb[0]:.2f},{rgb[1]:.2f},{rgb[2]:.2f}")

    def _onAddSegment(self):
        self._add_segment_row({})

    def _onRemoveSegment(self):
        rows = sorted(set(i.row() for i in self.segTable.selectedIndexes()), reverse=True)
        for r in rows:
            self.segTable.removeRow(r)
            if 0 <= r < len(self._segment_colors):
                del self._segment_colors[r]
        self._mark_dirty()

    def _onPickSegmentColor(self):
        row = self.segTable.currentRow()
        if row < 0:
            qt.QMessageBox.information(self, "Config Editor", "Select a segment row first.")
            return
        rgb = self._segment_colors[row]
        current = qt.QColor(*(int(round(c * 255)) for c in rgb))
        color = qt.QColorDialog.getColor(current, self, "Pick segment color")
        if color.isValid():
            self._segment_colors[row] = [color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0]
            self._apply_segment_color_display(row)
            self._mark_dirty()

    # ---- Landmarks tab ----

    def _build_landmarks_tab(self):
        w = qt.QWidget()
        form = qt.QFormLayout(w)
        self.chkLmEnabled = qt.QCheckBox("Enabled")
        form.addRow(self.chkLmEnabled)
        self.lmCsvColumnEdit = qt.QLineEdit()
        self.lmCsvColumnEdit.setToolTip("preseg.csv column holding an existing markups file path for this specimen (optional - falls back to Path pattern).")
        form.addRow("CSV column:", self.lmCsvColumnEdit)
        self.lmPathPatternEdit = qt.QLineEdit()
        self.lmPathPatternEdit.setPlaceholderText("default: {label}-markups.mrk.json")
        self.lmPathPatternEdit.setToolTip("Fallback naming when CSV column is empty/unset. {label} = the specimen's key joined with '-', e.g. 'D001'.")
        form.addRow("Path pattern:", self.lmPathPatternEdit)
        self.lmTemplateEdit, lmTemplateRow = self._file_row(filter_="Markups (*.mrk.json *.json);;All files (*)")
        self.lmTemplateEdit.setToolTip("If a specimen has no markups file yet, load THIS file as the starting point (renamed to that specimen) instead of an empty fiducial list.")
        form.addRow("Template file (optional):", lmTemplateRow)
        self.chkLmWritable = qt.QCheckBox("Writable")
        self.chkLmWritable.checked = True
        form.addRow(self.chkLmWritable)
        self.lmColorEdit = qt.QLineEdit()
        self.lmColorEdit.setPlaceholderText("r,g,b (0-1), e.g. 1,1,0")
        form.addRow("Color:", self.lmColorEdit)
        return w

    # ---- Volume rendering tab ----

    def _build_vr_tab(self):
        w = qt.QWidget()
        form = qt.QFormLayout(w)
        self.chkVrEnabled = qt.QCheckBox("Enabled")
        form.addRow(self.chkVrEnabled)
        self.vrSourceImageEdit = qt.QLineEdit()
        self.vrSourceImageEdit.setToolTip("The 'name' of one of your Images-tab entries to render, e.g. 'background' or 't1'.")
        form.addRow("Source image (name):", self.vrSourceImageEdit)
        self.vrPresetEdit = qt.QLineEdit()
        self.vrPresetEdit.setPlaceholderText("e.g. CT-Chest-Contrast-Enhanced")
        self.vrPresetEdit.setToolTip("A built-in Slicer Volume Rendering preset name.")
        form.addRow("Preset:", self.vrPresetEdit)
        return w

    # ---- Window/level (global) tab ----

    def _build_wl_tab(self):
        w = qt.QWidget()
        form = qt.QFormLayout(w)
        self.chkWlEnabled = qt.QCheckBox("Enabled (applies to EVERY loaded volume)")
        self.chkWlEnabled.setToolTip("Blanket min/max window applied to ALL loaded scalar volumes after a specimen loads - different from an Images-tab row's own per-image window_level.")
        form.addRow(self.chkWlEnabled)
        self.wlMinEdit = qt.QLineEdit()
        self.wlMinEdit.setToolTip("Lower display value, e.g. -150 for a typical CT soft-tissue window.")
        form.addRow("Min:", self.wlMinEdit)
        self.wlMaxEdit = qt.QLineEdit()
        self.wlMaxEdit.setToolTip("Upper display value, e.g. 700 for a typical CT soft-tissue window.")
        form.addRow("Max:", self.wlMaxEdit)
        return w

    # ---- Batch export tab ----

    def _build_batch_export_tab(self):
        w = qt.QWidget()
        form = qt.QFormLayout(w)
        self.chkBeEnabled = qt.QCheckBox("Enabled")
        form.addRow(self.chkBeEnabled)
        self.chkBeExportSegments = qt.QCheckBox("Export segments")
        form.addRow(self.chkBeExportSegments)
        self.chkBeExportMarkups = qt.QCheckBox("Export markups")
        form.addRow(self.chkBeExportMarkups)
        self.beReferenceImageEdit = qt.QLineEdit()
        self.beReferenceImageEdit.setToolTip("Reference volume for exporting segments to labelmaps. If empty, falls back to segmentation.reference_image.")
        form.addRow("Reference image (name):", self.beReferenceImageEdit)
        self.beSegmentsFilterEdit = qt.QLineEdit()
        self.beSegmentsFilterEdit.setPlaceholderText("comma-separated segment names, empty = all")
        form.addRow("Segments filter:", self.beSegmentsFilterEdit)
        self.beOutputDirEdit, beOutputDirRow = self._file_row(directory=True)
        self.beOutputDirEdit.setToolTip("Optional shared export folder for ALL specimens. If empty, each specimen exports into its own out_dir (General tab's Output dir pattern).")
        form.addRow("Output dir (optional):", beOutputDirRow)
        self.chkBePerBatchSubfolder = qt.QCheckBox("Per-batch subfolder (requires batch mode)")
        self.chkBePerBatchSubfolder.setToolTip("Exports into <output_dir>/<batch value>/... instead of one flat folder. Needs 'Enable batch mode' on the General tab.")
        form.addRow(self.chkBePerBatchSubfolder)
        return w

    # ---- Segment editor tab ----

    def _build_segment_editor_tab(self):
        w = qt.QWidget()
        form = qt.QFormLayout(w)
        self.overwriteModeCombo = qt.QComboBox()
        self.overwriteModeCombo.addItems(OVERWRITE_CHOICES)
        self.overwriteModeCombo.setToolTip("'none' = the Segment Editor's 'Allow overlap' checkbox is ON. 'all_segments'/'visible_segments' restrict painting to not overwrite other segments.")
        form.addRow("Overwrite mode:", self.overwriteModeCombo)
        self.brushShapeCombo = qt.QComboBox()
        self.brushShapeCombo.addItems(BRUSH_SHAPE_CHOICES)
        self.brushShapeCombo.setToolTip("sphere = 3D brush (also paints in the 3D view). circle = Slicer's normal 2D slice brush.")
        form.addRow("Brush shape:", self.brushShapeCombo)
        self.brushDiameterEdit = qt.QLineEdit()
        self.brushDiameterEdit.setToolTip("Fixed brush size - in mm if 'Use absolute size' below is checked, in % of the slice view otherwise.")
        form.addRow("Brush diameter (mm or %):", self.brushDiameterEdit)
        self.chkBrushAbsolute = qt.QCheckBox("Use absolute size (mm)")
        self.chkBrushAbsolute.setToolTip("Checked: fixed size in millimeters, regardless of zoom. Unchecked: size as a percentage of the slice view instead.")
        self.chkBrushAbsolute.checked = True
        form.addRow(self.chkBrushAbsolute)
        self.activeEffectEdit = qt.QLineEdit()
        self.activeEffectEdit.setPlaceholderText("e.g. Paint")
        self.activeEffectEdit.setToolTip("Pre-select this effect whenever a live/default Segment Editor node picks up these settings (best-effort, not forced).")
        form.addRow("Active effect on load:", self.activeEffectEdit)
        self.seAttributesEdit = qt.QPlainTextEdit()
        self.seAttributesEdit.setPlaceholderText('{"BrushSphere": "1"}')
        self.seAttributesEdit.setMaximumHeight(100)
        self.seAttributesEdit.setToolTip(
            "Escape hatch: raw attribute-name -> value pairs, applied last (overrides overwrite_mode/"
            "brush above). Brush params (BrushSphere, BrushAbsoluteDiameter, BrushRelativeDiameter, "
            "BrushDiameterIsRelative) are COMMON parameters with NO effect-name prefix - just the bare "
            "name, e.g. \"BrushSphere\": \"1\" (NOT \"Paint,BrushSphere\"). Only effect-SPECIFIC settings "
            "use an \"EffectName.ParamName\" form, e.g. \"Paint.ColorSmudge\".")
        form.addRow("Raw attributes (JSON):", self.seAttributesEdit)
        return w

    # ---- Defaults / Presets tab ----

    def _build_advanced_tab(self):
        w = qt.QWidget()
        layout = qt.QVBoxLayout(w)

        intro = qt.QLabel(
            "Fills in visual properties (window/level, color, threshold, ...) without repeating "
            "them on every row. Rule: defaults.image -> preset (if the row names one) -> the row's "
            "own fields - last one wins, per field. See the live \"Effective settings\" box on the "
            "Images tab for exactly what a given row ends up with.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        defaultsGroup = qt.QGroupBox("1) Defaults - apply to every row")
        defaultsForm = qt.QFormLayout(defaultsGroup)
        layout.addWidget(defaultsGroup)

        self.defaultsImageEdit = qt.QPlainTextEdit()
        self.defaultsImageEdit.setPlaceholderText('{"required": true, "window_level": {"min": -150, "max": 700}}')
        self.defaultsImageEdit.setMaximumHeight(80)
        self.defaultsImageEdit.setToolTip(
            "Fields applied to EVERY image (Images tab), before its own 'preset' and inline "
            "values override them. Any ImageConfig field works here: type, role, required, "
            "opacity, window_level, color_table, threshold, interpolate, path_pattern.")
        defaultsForm.addRow("defaults.image (JSON):", self.defaultsImageEdit)
        self.defaultsImageEdit.textChanged.connect(self._refresh_preview_if_selected)
        defaultsImgExampleBtn = qt.QPushButton("Insert example...")
        defaultsImgExampleBtn.setToolTip("Fills defaults.image above with a starter example (only if it's currently empty).")
        defaultsImgExampleBtn.connect('clicked(bool)', lambda checked=False: self._onInsertDefaultsImageExample())
        defaultsForm.addRow(defaultsImgExampleBtn)

        self.defaultsSegmentEdit = qt.QPlainTextEdit()
        self.defaultsSegmentEdit.setPlaceholderText('{"color": [1, 1, 1]}')
        self.defaultsSegmentEdit.setMaximumHeight(70)
        self.defaultsSegmentEdit.setToolTip("Same idea as defaults.image, but for every segment row (Segmentation tab): e.g. {\"color\": [1,1,1]}.")
        defaultsForm.addRow("defaults.segment (JSON):", self.defaultsSegmentEdit)

        presetsGroup = qt.QGroupBox("2) Presets - named looks, opt-in per image row")
        presetsForm = qt.QFormLayout(presetsGroup)
        layout.addWidget(presetsGroup)

        self.presetsEdit = qt.QPlainTextEdit()
        self.presetsEdit.plainText = json.dumps(
            {"ct_soft_tissue": self.EXAMPLE_PRESETS["ct_soft_tissue"],
             "ct_bone": self.EXAMPLE_PRESETS["ct_bone"]}, indent=2)
        self.presetsEdit.setToolTip(
            "Named, reusable bags of image visual properties. Reference one by name in an "
            "image row's 'Preset' column (Images tab) - merge order is defaults.image -> "
            "this preset -> the image row's own inline values.")
        self.presetsEdit.setMinimumHeight(120)
        presetsForm.addRow("presets (JSON):", self.presetsEdit)
        self.presetsEdit.textChanged.connect(self._refresh_preview_if_selected)
        self.presetsEdit.textChanged.connect(self._refresh_all_preset_combos)
        examplesBtn = qt.QPushButton("Show example presets (copyable)...")
        examplesBtn.setToolTip("Opens a read-only, copyable list of ready-made presets you can paste in above and tweak.")
        examplesBtn.connect('clicked(bool)', lambda checked=False: self._onShowExamplePresets())
        presetsForm.addRow(examplesBtn)

        return w

    def _onInsertDefaultsImageExample(self):
        if self.defaultsImageEdit.plainText.strip():
            ret = qt.QMessageBox.question(
                self, "Config Editor", "defaults.image is not empty - overwrite it with the example?",
                qt.QMessageBox.Yes | qt.QMessageBox.No)
            if ret != qt.QMessageBox.Yes:
                return
        self.defaultsImageEdit.plainText = json.dumps(
            {"required": False, "type": "volume", "window_level": {"min": -150, "max": 700}}, indent=2)
        self._mark_dirty()

    # ---- Manual edit config tab ----

    def _build_manual_tab(self):
        w = qt.QWidget()
        layout = qt.QVBoxLayout(w)
        hint = qt.QLabel(
            "This is the actual config.json that 'Save config' would write, built from every tab above. "
            "Click Refresh any time to see the current state. You can also edit the JSON directly here and "
            "click 'Apply to form' to push your edits back into all the other tabs - Save always saves "
            "from the tabs, so Apply first if you hand-edited something here.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.manualEditor = qt.QPlainTextEdit()
        layout.addWidget(self.manualEditor)

        btnRow = qt.QHBoxLayout()
        refreshBtn = qt.QPushButton("Refresh from form")
        refreshBtn.setToolTip("Regenerate the JSON below from the current state of every tab.")
        refreshBtn.connect('clicked(bool)', lambda checked=False: self._onRefreshManualEdit())
        applyBtn = qt.QPushButton("Apply to form")
        applyBtn.setToolTip("Parse the JSON below and load it into all the other tabs (like Load from file, but from this text).")
        applyBtn.connect('clicked(bool)', lambda checked=False: self._onApplyManualEdit())
        btnRow.addWidget(refreshBtn)
        btnRow.addWidget(applyBtn)
        btnRow.addStretch(1)
        layout.addLayout(btnRow)

        return w

    def _onRefreshManualEdit(self):
        try:
            cfg = self._build_config()
        except Exception:
            return  # _build_config already showed a JSON error from a field, if any
        self.manualEditor.plainText = json.dumps(cfg, indent=2, ensure_ascii=False)

    def _onApplyManualEdit(self):
        text = self.manualEditor.plainText.strip()
        if not text:
            qt.QMessageBox.information(self, "Config Editor", "Nothing to apply - the box is empty.")
            return
        try:
            cfg = json.loads(text)
        except Exception as e:
            qt.QMessageBox.critical(self, "Config Editor", f"Invalid JSON: {e}")
            return
        self._populate_form(cfg)
        self._mark_dirty()
        qt.QMessageBox.information(self, "Config Editor", "Applied to the other tabs.")

    # ---- example presets / help ----

    EXAMPLE_PRESETS = {
        "ct_soft_tissue": {"window_level": {"min": -150, "max": 700}, "color_table": "Grey"},
        "ct_bone": {"window_level": {"min": -200, "max": 1500}, "color_table": "Grey"},
        "ct_lung": {"window_level": {"min": -1400, "max": 200}, "color_table": "Grey"},
        "ct_brain": {"window_level": {"min": 0, "max": 80}, "color_table": "Grey"},
        "ct_abdomen": {"window_level": {"min": -135, "max": 215}, "color_table": "Grey"},
        "ct_angio": {"window_level": {"min": 100, "max": 700}, "color_table": "Grey"},
        "mri_auto": {"window_level": {"auto": True}, "interpolate": True},
        "mri_t1": {"window_level": {"auto": True}, "interpolate": True, "color_table": "Grey"},
        "mri_t2_flair": {"window_level": {"auto": True}, "interpolate": True, "color_table": "Grey"},
        "pet_hot_metal": {"window_level": {"auto": True}, "color_table": "PET-Heat", "opacity": 0.6},
        "label_overlay": {"color_table": "GenericColors"},
        "red_overlay": {
            "color_table": "vtkMRMLColorTableNodeRed",
            "threshold": {"min": 1, "max": 300},
            "window_level": {"window": 1, "level": 2},
            "opacity": 0.45,
        },
        "green_overlay": {
            "color_table": "vtkMRMLColorTableNodeGreen",
            "opacity": 0.5,
        },
    }

    PRESET_DESCRIPTIONS = {
        "ct_soft_tissue": "Typical CT soft-tissue window (abdomen/pelvis general use).",
        "ct_bone": "Wide CT window for bone detail.",
        "ct_lung": "Very wide, low-center CT window for lung parenchyma.",
        "ct_brain": "Narrow CT window for brain parenchyma.",
        "ct_abdomen": "Slightly narrower alternative abdomen window.",
        "ct_angio": "CT window tuned for contrast-enhanced vessels.",
        "mri_auto": "Let Slicer auto-window any MRI sequence; also smooths (interpolate).",
        "mri_t1": "Auto window + interpolation + grayscale, for T1-weighted MRI.",
        "mri_t2_flair": "Auto window + interpolation + grayscale, for T2/FLAIR MRI.",
        "pet_hot_metal": "Hot-metal PET colormap at partial opacity, meant as an overlay.",
        "label_overlay": "Generic distinguishable colors for a label/segmentation-style overlay.",
        "red_overlay": "Deer-study 'rel' example: red colormap + threshold + a narrow width/level window, semi-transparent.",
        "green_overlay": "Simple green, half-opacity overlay - handy for a second label image.",
    }

    HELP_HTML = """
<style>
  body { font-family: sans-serif; font-size: 13px; }
  h2 { font-size: 15px; margin: 14px 0 4px 0; padding: 2px 6px;
       background-color: #2c5f8a; color: white; border-radius: 3px; }
  h2:first-child { margin-top: 0; }
  ul { margin: 2px 0 10px 0; padding-left: 18px; }
  li { margin-bottom: 4px; }
  code { background-color: #eef2f6; color: #b3405a; padding: 1px 4px; border-radius: 3px; }
  .note { color: #555; font-style: italic; }
  table.merge { border-collapse: collapse; margin: 4px 0 10px 0; }
  table.merge td { border: 1px solid #ccc; padding: 3px 8px; }
  table.merge td.step { background-color: #eef2f6; font-weight: bold; text-align: center; }
</style>

<h2>&#128736; General</h2>
<ul>
<li><code>study_dir</code> - base folder every relative path resolves against. Empty = the preseg CSV's own folder.</li>
<li><b>Key columns</b> - the composite specimen ID, e.g. <code>ID</code> or <code>ID,measurement</code> - must exist, with matching values, in <b>both</b> CSVs. Use <b>"Show CSV columns..."</b> to check.</li>
<li><b>Table columns</b> - which database.csv columns appear (and are editable) in the main module's table. Any column works, not just <code>done</code>.</li>
<li><b>Batch mode</b> - shows a batch-select combo after Initialize Study, filtering by the chosen database.csv column (e.g. <code>batch</code>).</li>
</ul>

<h2>&#128444; Images</h2>
<ul>
<li><b>Quick-add table</b> - one row per preseg CSV column (key columns excluded). Check <b>Add</b> to include it as an image row; check <b>Labelmap</b> if it's a mask/label image instead of a regular volume.</li>
<li><code>Pattern</code> (regex) - instead of one fixed image, opens <b>one image per matching, non-empty</b> preseg.csv column for a given specimen. Name = that column's name (Strip prefix/suffix trims it). Different specimens can end up with different numbers of images.</li>
<li><b>Role</b> - background/label/foreground control slice-view layers (label/foreground also use Opacity). <code>(none)</code> = loaded but not shown as a layer.</li>
<li><b>Preset</b> - pulls window/level/color/threshold/interpolate from a named entry on the Defaults/Presets tab.</li>
<li><b>Edit advanced...</b> - window/level, threshold, interpolate for just that row. The <b>Effective settings</b> box below the table always shows the actual merged result for the selected row.</li>
</ul>
<table class="merge">
<tr><td class="step">1</td><td><code>defaults.image</code> - applies to every row</td></tr>
<tr><td class="step">2</td><td>named <code>preset</code> - only if that row's Preset column names one</td></tr>
<tr><td class="step">3</td><td>the row's own fields - always wins</td></tr>
</table>

<h2>&#129504; Segmentation</h2>
<ul>
<li><b>Reference image</b> - an Images-tab <code>name</code> used as the geometry reference for the whole segmentation.</li>
<li><b>Path pattern</b> - fallback naming for segment rows with no CSV column/path of their own, e.g. <code>{ID}/{measurement}/{ID}-{segment_name}.nii.gz</code>.</li>
<li><b>Source = file</b> - tries CSV column / path pattern, falls back to an empty placeholder if nothing resolves. <b>Source = empty</b> - never tries a file, always a manual placeholder.</li>
</ul>

<h2>&#128204; Landmarks</h2>
<ul>
<li><b>Template file</b> - if a specimen has no markups yet, this file loads as the starting point (renamed to that specimen) instead of an empty fiducial list.</li>
</ul>

<h2>&#128190; Batch export</h2>
<ul>
<li><b>Per-batch subfolder</b> - only works with Batch mode also enabled; exports to <code>&lt;output_dir&gt;/&lt;batch value&gt;/...</code> instead of one flat folder.</li>
</ul>

<h2>&#128394; Segment editor</h2>
<ul>
<li><b>Overwrite mode = none</b> - same as the Segment Editor's "Allow overlap" checkbox. <code>all_segments</code>/<code>visible_segments</code> restrict painting so it doesn't eat into other segments.</li>
<li><b>Use absolute size (mm)</b> checked + shape <code>sphere</code> - fixed-size 3D brush in millimeters, regardless of zoom (e.g. always exactly 5&nbsp;mm). Unchecked - size as a % of the slice view instead (grows/shrinks as you zoom).</li>
<li>Applied <b>once</b>, at Study Init - not re-applied per specimen. It's set on two places so it works whether or not Segment Editor was already opened this session:
  <ul>
  <li>the <b>default/template</b> node - used when Segment Editor is opened for the <i>first</i> time this session;</li>
  <li>an already-<b>live</b> Segment Editor node, if one already exists (you opened the module earlier).</li>
  </ul>
</li>
<li><b>Active effect on load</b> - which effect (e.g. <code>Paint</code>) should already be selected. Left empty, the user just picks an effect manually - the brush size/shape above still applies whenever they pick Paint.</li>
</ul>
<p><b>Raw attributes - what it's for and how to use it.</b> Slicer stores each effect's settings as plain key/value
pairs on the segment editor node. <b>Common</b> parameters shared by multiple effects (brush size/shape) have
<u>no prefix</u> - just the bare name. <b>Effect-specific</b> parameters are prefixed <code>EffectName.ParamName</code>
(a literal dot). Example dump of a real node's attributes:</p>
<pre>BrushAbsoluteDiameter: 25
BrushDiameterIsRelative: 1
BrushSphere: 0
Paint.ColorSmudge: 0
Threshold.MinimumThreshold: 69.75
Threshold.AutoThresholdMethod: OTSU</pre>
<p>So <code>"attributes": {"BrushSphere": "1"}</code> is correct; <code>"Paint,BrushSphere"</code> or
<code>"Paint.BrushSphere"</code> is <b>not</b> a real key and silently does nothing. If a setting you configured
through the structured fields above doesn't seem to stick, the fastest way to find the real key on <i>your</i>
Slicer version:</p>
<ol>
<li>Open Segment Editor by hand, change the setting you want (e.g. tick "Sphere brush").</li>
<li>Open the Python console and run: <code>print(slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentEditorNode"))</code></li>
<li>Read the exact attribute name + value from the printed list, and add it under <b>Raw attributes</b> here
(it's applied last, so it overrides the structured fields above if there's any conflict).</li>
</ol>

<h2>&#127912; Defaults / Presets</h2>
<p>Three layers, merged in this order for every image (last one wins, per field):</p>
<table class="merge">
<tr><td class="step">1</td><td><code>defaults.image</code> &ndash; applies to <b>every</b> image row automatically</td></tr>
<tr><td class="step">2</td><td>the named <code>presets[&lt;name&gt;]</code> entry &ndash; only if that row's <b>Preset</b> column names one</td></tr>
<tr><td class="step">3</td><td>the row's own columns / <b>Edit advanced...</b> popup &ndash; always wins</td></tr>
</table>
<p><b>Worked example.</b> Say you're setting up a multi-sequence MRI study:</p>
<pre>"defaults": {
  "image": { "type": "volume", "required": false, "interpolate": true }
},
"presets": {
  "mri_t1":  { "window_level": {"auto": true}, "color_table": "Grey" },
  "mri_flair": { "window_level": {"min": 0, "max": 400}, "color_table": "Grey" }
}</pre>
<p>Now three image rows:</p>
<ul>
<li><code>t1</code> &rarr; Preset = <code>mri_t1</code>, nothing else set.
  Effective: <code>interpolate:true</code> (from defaults) + <code>window_level:auto, color_table:Grey</code> (from the preset).</li>
<li><code>flair</code> &rarr; Preset = <code>mri_flair</code>, but its own Advanced popup sets <code>window_level: {min:0, max:600}</code>.
  Effective: the row's own 0-600 wins over the preset's 0-400 - everything else from the preset still applies.</li>
<li><code>dwi</code> &rarr; no Preset at all. Effective: just <code>type:volume, required:false, interpolate:true</code> from defaults - nothing else.</li>
</ul>
<p><code>defaults.segment</code> works the same way but one level only (<code>defaults.segment</code> &rarr; the segment
row's own fields - segments don't have named presets).</p>
<p class="note">A new config already starts with two starter presets (<code>ct_soft_tissue</code>, <code>ct_bone</code>) -
edit or delete them freely. "Show example presets..." has a much bigger catalogue (CT/MRI/PET windows, colored
overlays) to copy from, plus an "Insert ALL" button.</p>
<p class="note">Tip: select any text above (Ctrl+A / Ctrl+C) to copy it.</p>
"""

    def _onShowHelp(self):
        popup = qt.QDialog(self)
        popup.setWindowTitle("Config Editor - Cheat Sheet")
        popup.resize(700, 620)
        layout = qt.QVBoxLayout(popup)
        browser = qt.QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(self.HELP_HTML)
        layout.addWidget(browser)
        closeBtn = qt.QPushButton("Close")
        closeBtn.connect('clicked(bool)', lambda checked=False: popup.close())
        layout.addWidget(closeBtn)
        popup.exec_()

    def _build_example_presets_html(self):
        rows = []
        for name, data in self.EXAMPLE_PRESETS.items():
            desc = self.PRESET_DESCRIPTIONS.get(name, "")
            rows.append(
                f'<h3>{name}</h3>'
                f'<p class="desc">{desc}</p>'
                f'<pre>{json.dumps({name: data}, indent=2)}</pre>')
        return f"""
<style>
  body {{ font-family: sans-serif; font-size: 13px; }}
  h3 {{ font-size: 13px; margin: 14px 0 2px 0; color: #2c5f8a; }}
  h3:first-child {{ margin-top: 0; }}
  p.desc {{ margin: 0 0 4px 0; color: #555; }}
  pre {{ background-color: #f4f6f8; border: 1px solid #ddd; border-radius: 4px;
         padding: 6px 8px; margin: 0 0 4px 0; font-family: monospace; font-size: 12px; }}
</style>
<p>Each block is a complete <code>presets</code> entry - select one (click inside, Ctrl+A, Ctrl+C) and
paste it into the presets JSON field, merging with whatever's already there.</p>
{"".join(rows)}
"""

    def _onShowExamplePresets(self):
        popup = qt.QDialog(self)
        popup.setWindowTitle("Example presets")
        popup.resize(560, 620)
        layout = qt.QVBoxLayout(popup)
        browser = qt.QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(self._build_example_presets_html())
        layout.addWidget(browser)

        btnRow = qt.QHBoxLayout()
        insertAllBtn = qt.QPushButton("Insert ALL into presets field")
        insertAllBtn.setToolTip("Merges every example above into the presets JSON field (existing entries with the same name are overwritten).")
        insertAllBtn.connect('clicked(bool)', lambda checked=False: self._onInsertAllExamplePresets(popup))
        closeBtn = qt.QPushButton("Close")
        closeBtn.connect('clicked(bool)', lambda checked=False: popup.close())
        btnRow.addWidget(insertAllBtn)
        btnRow.addStretch(1)
        btnRow.addWidget(closeBtn)
        layout.addLayout(btnRow)
        popup.exec_()

    def _onInsertAllExamplePresets(self, popup):
        try:
            current = json.loads(self.presetsEdit.plainText or "{}")
        except Exception:
            current = {}
        current.update(self.EXAMPLE_PRESETS)
        self.presetsEdit.plainText = json.dumps(current, indent=2)
        self._mark_dirty()
        popup.close()

    def _confirm_discard(self):
        if not self._dirty:
            return True
        ret = qt.QMessageBox.question(
            self, "Config Editor", "Save changes to the current config first?",
            qt.QMessageBox.Save | qt.QMessageBox.Discard | qt.QMessageBox.Cancel)
        if ret == qt.QMessageBox.Cancel:
            return False
        if ret == qt.QMessageBox.Save:
            return self._onSave()
        return True

    def _clear_form(self):
        self._preseg_abs_path = ""
        self.quickColumnsTable.setRowCount(0)
        for edit in (self.presegEdit, self.dbEdit, self.studyDirEdit, self.keyColumnsEdit,
                     self.tableColumnsEdit, self.outputDirPatternEdit, self.batchColumnEdit,
                     self.segReferenceImageEdit, self.segPathPatternEdit,
                     self.lmCsvColumnEdit, self.lmPathPatternEdit, self.lmTemplateEdit, self.lmColorEdit,
                     self.vrSourceImageEdit, self.vrPresetEdit, self.wlMinEdit, self.wlMaxEdit,
                     self.beReferenceImageEdit, self.beSegmentsFilterEdit, self.beOutputDirEdit,
                     self.brushDiameterEdit, self.activeEffectEdit):
            edit.text = ""
        self.doneColumnEdit.text = "done"
        self.segOutputFilenameEdit.text = "segment.seg.nrrd"
        for chk in (self.chkBatchMode, self.chkSegEnabled, self.chkLmEnabled, self.chkVrEnabled,
                    self.chkWlEnabled, self.chkBeEnabled, self.chkBeExportSegments,
                    self.chkBeExportMarkups, self.chkBePerBatchSubfolder):
            chk.checked = False
        self.chkLmWritable.checked = True
        self.chkBrushAbsolute.checked = True
        self.overwriteModeCombo.currentText = "none"
        self.brushShapeCombo.currentText = "(unset)"
        self.seAttributesEdit.plainText = ""
        self.defaultsImageEdit.plainText = ""
        self.defaultsSegmentEdit.plainText = ""
        self.presetsEdit.plainText = json.dumps(
            {"ct_soft_tissue": self.EXAMPLE_PRESETS["ct_soft_tissue"],
             "ct_bone": self.EXAMPLE_PRESETS["ct_bone"]}, indent=2)
        self.imgTable.setRowCount(0)
        self._image_advanced = []
        self.segTable.setRowCount(0)
        self._segment_colors = []

    def _onNew(self):
        if not self._confirm_discard():
            return
        self._clear_form()
        self._current_path = None
        self.outputEdit.text = ""
        self._dirty = False
        self._updateTitle()

    def _onLoadFromFile(self):
        if not self._confirm_discard():
            return
        fname = qt.QFileDialog.getOpenFileName(self, "Load config", "", "JSON files (*.json)")
        if fname:
            self._load_from_file(fname)

    def _load_from_file(self, path, ask_confirm=True):
        if ask_confirm and not self._confirm_discard():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            qt.QMessageBox.critical(self, "Config Editor", f"Failed to load: {e}")
            return
        self._populate_form(cfg)
        self._current_path = path
        self.outputEdit.text = path
        self._dirty = False
        self._updateTitle()

    # ---- populate from dict ----

    def _populate_form(self, cfg):
        self._clear_form()

        self.presegEdit.text = cfg.get("preseg_csv_path", "")
        self.dbEdit.text = cfg.get("database_csv_path", "")
        self.studyDirEdit.text = cfg.get("study_dir", "")
        self.keyColumnsEdit.text = ",".join(cfg.get("key_columns", []))
        preseg_val = self.presegEdit.text.strip()
        if preseg_val:
            self._preseg_abs_path = preseg_val if os.path.isabs(preseg_val) else os.path.join(self.studyDirEdit.text.strip() or ".", preseg_val)
            # Setting .text programmatically does NOT fire editingFinished/the
            # Browse-picked callback - without this explicit call, the
            # quick-add column list (and key-column guessing) never runs when
            # a config is loaded (only when the user browses/types by hand),
            # leaving the Images tab's checklist empty after Load/on open.
            # key_columns is set above FIRST so it's already excluded from
            # the quick-add list this call builds.
            self._onPresegChanged(self._preseg_abs_path)
        self.doneColumnEdit.text = cfg.get("done_column", "done")
        self.tableColumnsEdit.text = ",".join(cfg.get("table_columns", []))
        self.outputDirPatternEdit.text = ",".join(cfg.get("output_dir_pattern", []))

        bm = cfg.get("batch_mode", {}) or {}
        self.chkBatchMode.checked = bool(bm.get("enabled"))
        self.batchColumnEdit.text = bm.get("column", "") or ""

        # defaults/presets loaded BEFORE the images loop below, so each row's
        # Preset dropdown is populated with the right choices as it's created
        # (rather than showing an empty list until something else refreshes it).
        defaults = cfg.get("defaults", {}) or {}
        if defaults.get("image"):
            self.defaultsImageEdit.plainText = json.dumps(defaults["image"], indent=2)
        if defaults.get("segment"):
            self.defaultsSegmentEdit.plainText = json.dumps(defaults["segment"], indent=2)
        if cfg.get("presets"):
            self.presetsEdit.plainText = json.dumps(cfg["presets"], indent=2)

        for img in cfg.get("images", []):
            self._add_image_row(img)

        seg = cfg.get("segmentation", {}) or {}
        self.chkSegEnabled.checked = bool(seg.get("enabled"))
        self.segReferenceImageEdit.text = seg.get("reference_image", "") or ""
        self.segPathPatternEdit.text = seg.get("path_pattern", "") or ""
        self.segOutputFilenameEdit.text = seg.get("output_filename", "segment.seg.nrrd")
        for s in seg.get("segments", []):
            self._add_segment_row(s)

        lm = cfg.get("landmarks", {}) or {}
        self.chkLmEnabled.checked = bool(lm.get("enabled"))
        self.lmCsvColumnEdit.text = lm.get("csv_column", "") or ""
        self.lmPathPatternEdit.text = lm.get("path_pattern", "") or ""
        self.lmTemplateEdit.text = lm.get("template_path", "") or ""
        self.chkLmWritable.checked = lm.get("writable", True)
        if lm.get("color"):
            self.lmColorEdit.text = ",".join(str(c) for c in lm["color"])

        vr = cfg.get("volume_rendering", {}) or {}
        self.chkVrEnabled.checked = bool(vr.get("enabled"))
        self.vrSourceImageEdit.text = vr.get("source_image", "") or ""
        self.vrPresetEdit.text = vr.get("preset", "") or ""

        wl = cfg.get("window_level", {}) or {}
        self.chkWlEnabled.checked = bool(wl.get("enabled"))
        self.wlMinEdit.text = "" if wl.get("min") is None else str(wl["min"])
        self.wlMaxEdit.text = "" if wl.get("max") is None else str(wl["max"])

        be = cfg.get("batch_export", {}) or {}
        self.chkBeEnabled.checked = bool(be.get("enabled"))
        self.chkBeExportSegments.checked = bool(be.get("export_segments"))
        self.chkBeExportMarkups.checked = bool(be.get("export_markups"))
        self.beReferenceImageEdit.text = be.get("reference_image", "") or ""
        self.beSegmentsFilterEdit.text = ",".join(be.get("segments_filter") or [])
        self.beOutputDirEdit.text = be.get("output_dir", "") or ""
        self.chkBePerBatchSubfolder.checked = bool(be.get("per_batch_subfolder"))

        se = cfg.get("segment_editor", {}) or {}
        self.overwriteModeCombo.currentText = se.get("overwrite_mode", "none") or "none"
        brush = se.get("brush") or {}
        self.brushShapeCombo.currentText = brush.get("shape") or "(unset)"
        self.brushDiameterEdit.text = "" if brush.get("diameter_mm") is None else str(brush["diameter_mm"])
        self.chkBrushAbsolute.checked = not bool(brush.get("relative"))
        self.activeEffectEdit.text = se.get("active_effect", "") or ""
        if se.get("attributes"):
            self.seAttributesEdit.plainText = json.dumps(se["attributes"], indent=2)

    # ---- build config dict ----

    def _read_image_row(self, row):
        """Return the raw (unmerged) dict for one image row, or None if it has no name."""
        d = {}
        name = self.imgTable.item(row, 0).text().strip()
        if not name:
            return None
        d["name"] = name
        for col, key in ((1, "csv_column"), (2, "pattern"), (3, "strip_prefix"), (4, "strip_suffix")):
            val = self.imgTable.item(row, col).text().strip()
            if val:
                d[key] = val
        d["type"] = self.imgTable.cellWidget(row, 5).currentText
        role = self.imgTable.cellWidget(row, 6).currentText
        if role != "(none)":
            d["role"] = role
        if self.imgTable.item(row, 7).checkState() == qt.Qt.Checked:
            d["required"] = True
        preset = (self.imgTable.cellWidget(row, 8).currentText or "").strip()
        if preset:
            d["preset"] = preset
        opacity = _f(self.imgTable.item(row, 9).text())
        if opacity is not None:
            d["opacity"] = opacity
        color_table = (self.imgTable.cellWidget(row, 10).currentText or "").strip()
        if color_table:
            d["color_table"] = color_table
        if row < len(self._image_advanced):
            d.update(self._image_advanced[row])
        return d

    def _read_image_rows(self):
        images = []
        for row in range(self.imgTable.rowCount):
            d = self._read_image_row(row)
            if d is not None:
                images.append(d)
        return images

    def _read_segment_rows(self):
        segments = []
        for row in range(self.segTable.rowCount):
            name = self.segTable.item(row, 0).text().strip()
            if not name:
                continue
            d = {"name": name, "source": self.segTable.cellWidget(row, 1).currentText}
            csv_col = self.segTable.item(row, 2).text().strip()
            if csv_col:
                d["csv_column"] = csv_col
            pattern = self.segTable.item(row, 3).text().strip()
            if pattern:
                d["path_pattern"] = pattern
            if row < len(self._segment_colors):
                d["color"] = [round(c, 3) for c in self._segment_colors[row]]
            segments.append(d)
        return segments

    def _parse_json_field(self, edit, label):
        text = (edit.plainText or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception as e:
            qt.QMessageBox.critical(self, "Config Editor", f"Invalid JSON in '{label}': {e}")
            raise

    def _build_config(self):
        cfg = {
            "study_dir": self.studyDirEdit.text.strip() or os.path.dirname(self.presegEdit.text.strip()) or ".",
            "database_csv_path": self.dbEdit.text.strip(),
            "preseg_csv_path": self.presegEdit.text.strip(),
            "key_columns": _csv_list(self.keyColumnsEdit.text) or ["ID"],
            "done_column": self.doneColumnEdit.text.strip() or "done",
        }
        table_cols = _csv_list(self.tableColumnsEdit.text)
        cfg["table_columns"] = table_cols or (cfg["key_columns"] + [cfg["done_column"]])
        out_pattern = _csv_list(self.outputDirPatternEdit.text)
        if out_pattern:
            cfg["output_dir_pattern"] = out_pattern

        if self.chkBatchMode.checked:
            cfg["batch_mode"] = {"enabled": True, "column": self.batchColumnEdit.text.strip()}

        images = self._read_image_rows()
        if images:
            cfg["images"] = images

        seg_enabled = self.chkSegEnabled.checked
        segments = self._read_segment_rows()
        if seg_enabled or segments:
            seg = {"enabled": seg_enabled}
            if self.segReferenceImageEdit.text.strip():
                seg["reference_image"] = self.segReferenceImageEdit.text.strip()
            if self.segPathPatternEdit.text.strip():
                seg["path_pattern"] = self.segPathPatternEdit.text.strip()
            seg["output_filename"] = self.segOutputFilenameEdit.text.strip() or "segment.seg.nrrd"
            seg["segments"] = segments
            cfg["segmentation"] = seg

        if self.chkLmEnabled.checked:
            lm = {"enabled": True, "writable": self.chkLmWritable.checked}
            if self.lmCsvColumnEdit.text.strip():
                lm["csv_column"] = self.lmCsvColumnEdit.text.strip()
            if self.lmPathPatternEdit.text.strip():
                lm["path_pattern"] = self.lmPathPatternEdit.text.strip()
            if self.lmTemplateEdit.text.strip():
                lm["template_path"] = self.lmTemplateEdit.text.strip()
            if self.lmColorEdit.text.strip():
                lm["color"] = [_f(c) for c in self.lmColorEdit.text.split(",")]
            cfg["landmarks"] = lm

        if self.chkVrEnabled.checked:
            vr = {"enabled": True}
            if self.vrSourceImageEdit.text.strip():
                vr["source_image"] = self.vrSourceImageEdit.text.strip()
            if self.vrPresetEdit.text.strip():
                vr["preset"] = self.vrPresetEdit.text.strip()
            cfg["volume_rendering"] = vr

        if self.chkWlEnabled.checked:
            wl = {"enabled": True}
            mn, mx = _f(self.wlMinEdit.text), _f(self.wlMaxEdit.text)
            if mn is not None:
                wl["min"] = mn
            if mx is not None:
                wl["max"] = mx
            cfg["window_level"] = wl

        if self.chkBeEnabled.checked:
            be = {
                "enabled": True,
                "export_segments": self.chkBeExportSegments.checked,
                "export_markups": self.chkBeExportMarkups.checked,
                "per_batch_subfolder": self.chkBePerBatchSubfolder.checked,
            }
            if self.beReferenceImageEdit.text.strip():
                be["reference_image"] = self.beReferenceImageEdit.text.strip()
            filt = _csv_list(self.beSegmentsFilterEdit.text)
            if filt:
                be["segments_filter"] = filt
            if self.beOutputDirEdit.text.strip():
                be["output_dir"] = self.beOutputDirEdit.text.strip()
            cfg["batch_export"] = be

        overwrite = self.overwriteModeCombo.currentText
        brush_shape = self.brushShapeCombo.currentText
        diameter = _f(self.brushDiameterEdit.text)
        active_effect = self.activeEffectEdit.text.strip()
        se_attrs = self._parse_json_field(self.seAttributesEdit, "segment_editor attributes") or {}
        if overwrite != "none" or brush_shape != "(unset)" or diameter is not None or active_effect or se_attrs:
            se = {"overwrite_mode": overwrite}
            if brush_shape != "(unset)" or diameter is not None:
                brush = {}
                if brush_shape != "(unset)":
                    brush["shape"] = brush_shape
                if diameter is not None:
                    brush["diameter_mm"] = diameter
                brush["relative"] = not self.chkBrushAbsolute.checked
                se["brush"] = brush
            if active_effect:
                se["active_effect"] = active_effect
            if se_attrs:
                se["attributes"] = se_attrs
            cfg["segment_editor"] = se

        defaults = {}
        di = self._parse_json_field(self.defaultsImageEdit, "defaults.image")
        if di:
            defaults["image"] = di
        ds = self._parse_json_field(self.defaultsSegmentEdit, "defaults.segment")
        if ds:
            defaults["segment"] = ds
        if defaults:
            cfg["defaults"] = defaults

        presets = self._parse_json_field(self.presetsEdit, "presets")
        if presets:
            cfg["presets"] = presets

        return cfg

    def _onSave(self):
        if not self.presegEdit.text.strip():
            qt.QMessageBox.warning(self, "Config Editor", "Select an images/preseg CSV first.")
            return False
        if not self.outputEdit.text.strip():
            fname = qt.QFileDialog.getSaveFileName(self, "Save config as", self._current_path or "config.json", "JSON files (*.json)")
            if not fname:
                return False
            self.outputEdit.text = fname

        try:
            cfg = self._build_config()
        except Exception:
            return False   # _parse_json_field already showed the error

        out_path = self.outputEdit.text.strip()
        try:
            out_dir = os.path.dirname(out_path)
            if out_dir and not os.path.isdir(out_dir):
                os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            qt.QMessageBox.critical(self, "Config Editor", f"Failed to save: {e}")
            return False

        self._current_path = out_path
        self._dirty = False
        self._updateTitle()
        qt.QMessageBox.information(self, "Config Editor", f"Saved: {out_path}")
        return True

    def closeEvent(self, event):
        try:
            if self._dirty and not self._confirm_discard():
                event.ignore()
                return
        except Exception as e:
            print(f"[ConfigEditor] closeEvent check failed, closing anyway: {e}")
        event.accept()
