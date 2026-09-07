"""
ConfigBuilderDialog
====================

A standalone Qt window that helps hand-build a study config.json for
GenericSpecimenEngine without touching raw JSON:
  - browse the images/preseg CSV and the database CSV
  - optionally browse a markups TEMPLATE file (used as the starting point
    for a specimen's landmarks the first time it's loaded, instead of an
    empty fiducial list - see GenericSpecimenEngine._load_landmarks)
  - pick which preseg.csv column is the background image / the mask image
  - define an arbitrary list of segments by name + color
  - save the result to a config.json

This intentionally covers a practical subset of the full schema - background
+ mask images and empty-source, colored segments. For anything beyond that
(dynamic images, presets, volume rendering, window/level, batch export,
segment_editor brush settings, ...) open the saved file and extend it by
hand.
"""

import os
import csv
import json

import qt


DEFAULT_SEGMENT_COLOR = (0.9, 0.9, 0.2)


def _read_csv_header(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
        return [h.strip() for h in header if h.strip()]
    except Exception:
        return []


def _guess_key_columns(header):
    guesses = [h for h in header if h.strip().lower() in ("id", "sid", "specimen", "specimenid")]
    return guesses or (header[:1] if header else [])


class ConfigBuilderDialog(qt.QDialog):

    def __init__(self, parent=None):
        qt.QDialog.__init__(self, parent)
        self.setWindowTitle("Config Builder")
        self.resize(680, 600)
        self._preseg_header = []
        self._build_ui()

    # ---- UI ----

    def _build_ui(self):
        layout = qt.QVBoxLayout(self)

        form = qt.QFormLayout()
        layout.addLayout(form)

        self.presegEdit, presegRow = self._file_row(on_change=self._onPresegChanged)
        form.addRow("Images / preseg CSV:", presegRow)

        self.dbEdit, dbRow = self._file_row()
        form.addRow("Database CSV:", dbRow)

        self.markupsEdit, markupsRow = self._file_row(
            filter_="Markups (*.mrk.json *.json);;All files (*)")
        form.addRow("Markups template (optional):", markupsRow)

        self.studyDirEdit = qt.QLineEdit()
        self.studyDirEdit.setPlaceholderText("default: preseg CSV's folder")
        form.addRow("Study dir (optional override):", self.studyDirEdit)

        self.keyColumnsEdit = qt.QLineEdit()
        self.keyColumnsEdit.setPlaceholderText("comma-separated, e.g. ID,measurement")
        form.addRow("Key columns:", self.keyColumnsEdit)

        self.backgroundCombo = qt.QComboBox()
        form.addRow("Background image column:", self.backgroundCombo)

        self.maskCombo = qt.QComboBox()
        form.addRow("Mask image column (optional):", self.maskCombo)

        segGroup = qt.QGroupBox("Segments")
        segLayout = qt.QVBoxLayout(segGroup)
        layout.addWidget(segGroup)

        self.segTable = qt.QTableWidget(0, 2)
        self.segTable.setHorizontalHeaderLabels(["Name", "Color"])
        self.segTable.horizontalHeader().setSectionResizeMode(0, qt.QHeaderView.Stretch)
        self.segTable.horizontalHeader().setSectionResizeMode(1, qt.QHeaderView.Fixed)
        self.segTable.setColumnWidth(1, 90)
        segLayout.addWidget(self.segTable)

        segBtnRow = qt.QHBoxLayout()
        addSegBtn = qt.QPushButton("Add segment")
        addSegBtn.connect('clicked(bool)', self._onAddSegment)
        removeSegBtn = qt.QPushButton("Remove selected")
        removeSegBtn.connect('clicked(bool)', self._onRemoveSegment)
        segBtnRow.addWidget(addSegBtn)
        segBtnRow.addWidget(removeSegBtn)
        segBtnRow.addStretch(1)
        segLayout.addLayout(segBtnRow)

        self.outputEdit, outputRow = self._file_row(
            filter_="JSON files (*.json)", save=True, default_name="config.json")
        form.addRow("Output config.json:", outputRow)

        btnRow = qt.QHBoxLayout()
        btnRow.addStretch(1)
        saveBtn = qt.QPushButton("Save config")
        saveBtn.connect('clicked(bool)', self._onSave)
        closeBtn = qt.QPushButton("Close")
        closeBtn.connect('clicked(bool)', self.close)
        btnRow.addWidget(saveBtn)
        btnRow.addWidget(closeBtn)
        layout.addLayout(btnRow)

        self._onAddSegment()   # start with one example row so the table isn't empty

    def _file_row(self, on_change=None, filter_="CSV files (*.csv);;All files (*)",
                  save=False, default_name=""):
        container = qt.QWidget()
        rowLayout = qt.QHBoxLayout(container)
        rowLayout.setContentsMargins(0, 0, 0, 0)
        edit = qt.QLineEdit()
        browse = qt.QPushButton("Browse...")
        rowLayout.addWidget(edit)
        rowLayout.addWidget(browse)

        def _browse():
            if save:
                fname = qt.QFileDialog.getSaveFileName(self, "Save as", edit.text or default_name, filter_)
            else:
                fname = qt.QFileDialog.getOpenFileName(self, "Select file", edit.text, filter_)
            if fname:
                edit.text = fname
                if on_change:
                    on_change(fname)

        browse.connect('clicked(bool)', _browse)
        return edit, container

    def _onPresegChanged(self, path):
        self._preseg_header = _read_csv_header(path)

        self.backgroundCombo.clear()
        self.maskCombo.clear()
        self.maskCombo.addItem("(none)")
        for col in self._preseg_header:
            self.backgroundCombo.addItem(col)
            self.maskCombo.addItem(col)

        if not self.keyColumnsEdit.text.strip():
            guessed = _guess_key_columns(self._preseg_header)
            if guessed:
                self.keyColumnsEdit.text = ",".join(guessed)

    def _onAddSegment(self):
        row = self.segTable.rowCount
        self.segTable.insertRow(row)
        self.segTable.setItem(row, 0, qt.QTableWidgetItem(f"segment_{row + 1}"))
        self._set_color_cell(row, DEFAULT_SEGMENT_COLOR)

    def _onRemoveSegment(self):
        rows = sorted(set(idx.row() for idx in self.segTable.selectedIndexes()), reverse=True)
        for r in rows:
            self.segTable.removeRow(r)

    def _set_color_cell(self, row, rgb):
        btn = qt.QPushButton()
        btn.setProperty("rgb", list(rgb))
        self._update_color_button(btn, rgb)
        btn.connect('clicked(bool)', lambda checked=False, b=btn: self._onPickColor(b))
        self.segTable.setCellWidget(row, 1, btn)

    def _update_color_button(self, btn, rgb):
        r, g, b = (int(round(c * 255)) for c in rgb)
        btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #444;")
        btn.setProperty("rgb", list(rgb))

    def _onPickColor(self, btn):
        rgb = btn.property("rgb")
        current = qt.QColor(*(int(round(c * 255)) for c in rgb))
        color = qt.QColorDialog.getColor(current, self, "Pick segment color")
        if color.isValid():
            new_rgb = [color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0]
            self._update_color_button(btn, new_rgb)

    # ---- build + save ----

    def _collect_segments(self):
        segments = []
        for row in range(self.segTable.rowCount):
            name_item = self.segTable.item(row, 0)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            btn = self.segTable.cellWidget(row, 1)
            rgb = btn.property("rgb") if btn else list(DEFAULT_SEGMENT_COLOR)
            segments.append({"name": name, "source": "empty", "color": [round(c, 3) for c in rgb]})
        return segments

    def _build_config(self):
        preseg_path = self.presegEdit.text.strip()
        db_path = self.dbEdit.text.strip()
        markups_path = self.markupsEdit.text.strip()
        study_dir = self.studyDirEdit.text.strip() or os.path.dirname(preseg_path) or "."

        key_columns = [c.strip() for c in self.keyColumnsEdit.text.split(",") if c.strip()]
        if not key_columns:
            key_columns = ["ID"]

        background_col = self.backgroundCombo.currentText
        mask_col = self.maskCombo.currentText

        images = []
        if background_col:
            images.append({"name": "background", "csv_column": background_col,
                            "role": "background", "required": True})
        if mask_col and mask_col != "(none)":
            images.append({"name": "mask", "csv_column": mask_col,
                            "role": "label", "required": True})

        cfg = {
            "study_dir": study_dir,
            "database_csv_path": db_path,
            "preseg_csv_path": preseg_path,
            "key_columns": key_columns,
            "table_columns": key_columns + ["done"],
            "images": images,
        }

        segments = self._collect_segments()
        if segments:
            cfg["segmentation"] = {
                "enabled": True,
                "reference_image": "mask" if any(i["name"] == "mask" for i in images)
                                    else (images[0]["name"] if images else None),
                "segments": segments,
                "output_filename": "segment.seg.nrrd",
            }
            cfg["segment_editor"] = {
                "overwrite_mode": "none",
                "brush": {"shape": "sphere", "diameter_mm": 5, "relative": False},
            }

        if markups_path:
            cfg["landmarks"] = {
                "enabled": True,
                "template_path": markups_path,
                "writable": True,
            }

        return cfg

    def _onSave(self):
        if not self.presegEdit.text.strip():
            qt.QMessageBox.warning(self, "Config Builder", "Select an images/preseg CSV first.")
            return
        if not self.outputEdit.text.strip():
            fname = qt.QFileDialog.getSaveFileName(self, "Save config as", "config.json", "JSON files (*.json)")
            if not fname:
                return
            self.outputEdit.text = fname

        cfg = self._build_config()
        out_path = self.outputEdit.text.strip()
        try:
            out_dir = os.path.dirname(out_path)
            if out_dir and not os.path.isdir(out_dir):
                os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            qt.QMessageBox.critical(self, "Config Builder", f"Failed to save: {e}")
            return

        qt.QMessageBox.information(self, "Config Builder", f"Saved: {out_path}")
