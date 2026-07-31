"""
GenericSpecimenEngine
======================

Shared, JSON-config-driven engine behind every "specimen viewer" style Slicer
module in this extension (PigChunker, RabbitVertCount, DeerSegmentor, ...).

This file is a plain importable library, NOT a Slicer module on its own
(there is no top-level class named `GenericSpecimenEngine` that subclasses
ScriptedLoadableModule, so Slicer's module factory will not register it as
a separate module in the module selector).

Each species gets its own *thin* wrapper module (its own .py + .ui + icon,
in its own folder) that:
  - sets its own title / category / icon in ScriptedLoadableModule.__init__
    (this is the only place Slicer lets a module have its own identity)
  - points CONFIG_PATH at its own config.json
  - subclasses GenericSpecimenModuleWidgetBase / GenericSpecimenModuleLogic
    from this file, so all the actual behaviour is shared and only lives
    here.

See DeerSegmentor.py for a complete, minimal example wrapper, and
README.md for the full config.json schema.
"""

import os
import re
import json

import qt
import vtk
import ctk

from qt import QFileDialog

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin


PRESET_KEYS = {"window_level", "color_table", "threshold", "opacity", "interpolate", "auto_window_level"}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config(path):
    """Load and normalize a study config json. See README.md for the schema."""
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("study_dir", os.path.dirname(path))
    cfg.setdefault("key_columns", ["ID"])
    cfg.setdefault("done_column", "done")
    cfg.setdefault("table_columns", list(cfg["key_columns"]) + [cfg["done_column"]])
    cfg.setdefault("images", [])
    cfg.setdefault("presets", {})
    cfg.setdefault("visual_presets", [])
    cfg.setdefault("segmentation", {"enabled": False})
    cfg.setdefault("landmarks", {"enabled": False})
    cfg.setdefault("volume_rendering", {"enabled": False})
    cfg.setdefault("window_level", {"enabled": False})
    cfg.setdefault("output_dir_pattern", list(cfg["key_columns"]))
    cfg.setdefault("batch_export", {"enabled": False})
    cfg.setdefault("label_opacity", 0.15)
    cfg.setdefault("foreground_opacity", 0.5)
    return cfg


# ---------------------------------------------------------------------------
# GenericSpecimen: one row (one "specimen") worth of data + Slicer nodes
# ---------------------------------------------------------------------------

class GenericSpecimen:
    def __init__(self, key_values, cfg, db_row, preseg_row, study_dir):
        self.cfg = cfg
        self.key_columns = cfg["key_columns"]
        self.key_values = tuple(key_values)
        self.context = dict(zip(self.key_columns, self.key_values))
        self.db_info = dict(db_row or {})
        self.preseg_info = dict(preseg_row or {})
        self.study_dir = study_dir

        self.node_dict = {}          # logical image name -> volume/labelmap/markups node
        self.writeable = {}          # logical name ("__segmentation__", "__markups__", or image name) -> abs path
        self.segmentation_node = None
        self.markups_node = None
        self.volume_rendering_node = None
        self.volume_rendering_roi = []

        self.row_index = None        # row index in the raw database table
        self.done_col_index = None   # column index in the raw database table

    # ---- identity / paths ----

    @property
    def key(self):
        return self.key_values

    @property
    def label(self):
        return "-".join(str(v) for v in self.key_values)

    @property
    def out_dir(self):
        parts = []
        for k in self.cfg["output_dir_pattern"]:
            parts.append(str(self.context.get(k, self.db_info.get(k, k))))
        return os.path.join(self.study_dir, *parts)

    def _context(self, extra=None):
        ctx = dict(self.context)
        ctx.update(self.db_info)
        ctx.update(self.preseg_info)
        if extra:
            ctx.update(extra)
        return ctx

    def _to_abs(self, rel):
        rel = str(rel).replace(2 * os.sep, os.sep)
        if os.path.isabs(rel):
            return rel
        return os.path.join(self.study_dir, rel)

    def resolve_image_path(self, img_cfg):
        col = img_cfg.get("csv_column")
        if col and self.preseg_info.get(col):
            rel = self.preseg_info[col]
        elif img_cfg.get("path_pattern"):
            rel = img_cfg["path_pattern"].format(**self._context({"name": img_cfg.get("name")}))
        else:
            raise ValueError(f"Cannot resolve path for image '{img_cfg.get('name')}': "
                              f"no csv_column value and no path_pattern given")
        return self._to_abs(rel)

    def resolve_segment_path(self, seg_cfg, seg_name, seg_def=None):
        seg_def = seg_def or {}
        col = seg_def.get("csv_column")
        if col is None:
            cols = seg_cfg.get("segment_name_csv_columns") or {}
            col = cols.get(seg_name)
        if col and self.preseg_info.get(col):
            rel = self.preseg_info[col]
        else:
            pattern = seg_def.get("path_pattern") or seg_cfg.get("path_pattern")
            if not pattern:
                raise ValueError(f"no path_pattern/csv_column for segment '{seg_name}'")
            rel = pattern.format(**self._context({"segment_name": seg_name}))
        return self._to_abs(rel)

    def segmentation_out_path(self):
        seg_cfg = self.cfg["segmentation"]
        return os.path.join(self.out_dir, seg_cfg.get("output_filename", "segment.seg.nrrd"))

    def markups_out_path(self):
        lm_cfg = self.cfg["landmarks"]
        col = lm_cfg.get("csv_column")
        rel = self.preseg_info.get(col) if col else None
        if not rel:
            rel = lm_cfg.get("path_pattern", "{label}-markups.mrk.json").format(
                **self._context({"label": self.label}))
        return self._to_abs(rel)

    # ---- db table sync ----

    def update_done(self, table):
        if self.row_index is None or self.done_col_index is None:
            return
        try:
            self.db_info[self.cfg["done_column"]] = table.GetCellText(self.row_index, self.done_col_index)
        except Exception as e:
            slicer.util.errorDisplay("Failed to update done state: " + str(e))

    # ---- images: dynamic expansion + presets ----

    def _expand_image_entries(self):
        """Turn cfg["images"] into a concrete list of per-specimen image jobs.

        A normal entry (with "csv_column" or "path_pattern") becomes exactly
        one job. An entry with "csv_column_pattern" (a regex) becomes ZERO OR
        MORE jobs: one for every non-key preseg.csv column whose name matches
        the pattern AND that has a non-empty value for THIS specimen. That
        job's image name is the column name (optionally stripped of a prefix
        / suffix). This is how "open as many images as this specimen has,
        named after their column" is implemented.
        """
        jobs = []
        for img_cfg in self.cfg["images"]:
            pattern = img_cfg.get("csv_column_pattern")
            if not pattern:
                jobs.append(img_cfg)
                continue

            regex = re.compile(pattern)
            for col, val in self.preseg_info.items():
                if col in self.key_columns or not val:
                    continue
                if not regex.match(col):
                    continue

                name = col
                strip_prefix = img_cfg.get("name_strip_prefix")
                if strip_prefix and name.startswith(strip_prefix):
                    name = name[len(strip_prefix):]
                strip_suffix = img_cfg.get("name_strip_suffix")
                if strip_suffix and name.endswith(strip_suffix):
                    name = name[:-len(strip_suffix)]

                virtual_cfg = dict(img_cfg)
                virtual_cfg.pop("csv_column_pattern", None)
                virtual_cfg.pop("name_strip_prefix", None)
                virtual_cfg.pop("name_strip_suffix", None)
                virtual_cfg["name"] = name
                virtual_cfg["csv_column"] = col
                virtual_cfg.setdefault("required", False)
                jobs.append(virtual_cfg)
        return jobs

    def _collect_preset(self, img_cfg, resolved_name):
        """Merge: named preset(s) -> inline preset keys on the image entry
        -> matching global visual_presets rules (cascade, in list order)."""
        result = {}

        preset_refs = img_cfg.get("presets")
        if preset_refs is None and img_cfg.get("preset"):
            preset_refs = [img_cfg["preset"]]
        for pname in (preset_refs or []):
            result.update(self.cfg.get("presets", {}).get(pname, {}))

        for k in PRESET_KEYS:
            if k in img_cfg:
                result[k] = img_cfg[k]

        for rule in self.cfg.get("visual_presets", []):
            matches = False
            if "apply_to" in rule and resolved_name in rule["apply_to"]:
                matches = True
            if "apply_to_pattern" in rule and re.match(rule["apply_to_pattern"], resolved_name):
                matches = True
            if matches:
                for k in PRESET_KEYS:
                    if k in rule:
                        result[k] = rule[k]

        return result

    def _resolve_color_node(self, name_or_id):
        try:
            node = slicer.mrmlScene.GetNodeByID(name_or_id)
            if node:
                return node
        except Exception:
            pass
        try:
            return slicer.util.getNode(name_or_id)
        except Exception:
            return None

    def _apply_preset(self, node, preset):
        disp = node.GetDisplayNode()
        if disp is None:
            return

        wl = preset.get("window_level")
        if wl:
            if wl.get("auto"):
                disp.SetAutoWindowLevel(1)
            else:
                disp.SetAutoWindowLevel(0)
                disp.SetWindowLevelMinMax(wl.get("min", -150), wl.get("max", 700))

        if "interpolate" in preset:
            disp.SetInterpolate(1 if preset["interpolate"] else 0)

        color_table = preset.get("color_table")
        if color_table:
            color_node = self._resolve_color_node(color_table)
            if color_node:
                disp.SetAndObserveColorNodeID(color_node.GetID())

        th = preset.get("threshold")
        if th:
            disp.SetThreshold(th.get("min", 0), th.get("max", 0))
            if th.get("apply", True):
                disp.ApplyThresholdOn()
            else:
                disp.ApplyThresholdOff()

    # ---- segmentation ----

    def _normalize_segment_defs(self, seg_cfg):
        """New expressive form: "segments": [{"name":..,"csv_column":..,"color":[r,g,b],"source":"file"|"empty"}, ...]
        Backward-compatible flat form: "segment_names": [...] (+ optional "segment_name_csv_columns")."""
        if "segments" in seg_cfg:
            return seg_cfg["segments"]
        names = seg_cfg.get("segment_names", [])
        cols = seg_cfg.get("segment_name_csv_columns", {}) or {}
        return [{"name": n, "csv_column": cols.get(n)} for n in names]

    def _add_empty_segment(self, segmentation_node, name, reference_volume_node, color=None):
        if reference_volume_node is None:
            print(f"[GenericSpecimen] no reference volume, skipping empty segment '{name}'")
            return
        dummy = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.vtkSlicerVolumesLogic().CreateLabelVolumeFromVolume(slicer.mrmlScene, dummy, reference_volume_node)
        dummy.GetImageData().GetPointData().GetScalars().Fill(0)
        img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(dummy)
        if color:
            segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(img, name, color)
        else:
            segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(img, name)
        slicer.mrmlScene.RemoveNode(dummy)

    def _build_segment(self, seg_def, segmentation_node, reference_volume_node):
        name = seg_def["name"]
        color = seg_def.get("color")
        source = seg_def.get("source", "file")

        if source == "empty":
            self._add_empty_segment(segmentation_node, name, reference_volume_node, color)
            return

        seg_cfg = self.cfg["segmentation"]
        try:
            path = self.resolve_segment_path(seg_cfg, name, seg_def)
        except Exception:
            self._add_empty_segment(segmentation_node, name, reference_volume_node, color)
            return

        try:
            mask_node = slicer.util.loadLabelVolume(path)
            img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(mask_node)
            if color:
                segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(img, name, color)
            else:
                segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(img, name)
            slicer.mrmlScene.RemoveNode(mask_node)
        except Exception:
            print(f"[GenericSpecimen] unable to load segment image '{path}', creating empty segment '{name}'")
            self._add_empty_segment(segmentation_node, name, reference_volume_node, color)

    def _load_segmentation(self, seg_cfg):
        out_path = self.segmentation_out_path()
        ref_name = seg_cfg.get("reference_image")
        ref_node = self.node_dict.get(ref_name) if ref_name else None

        if os.path.exists(out_path):
            print("[GenericSpecimen] loading existing segmentation...")
            seg_node = slicer.util.loadSegmentation(out_path)
            if ref_node is not None:
                seg_node.SetReferenceImageGeometryParameterFromVolumeNode(ref_node)
        else:
            print("[GenericSpecimen] initializing new segmentation...")
            seg_node = slicer.vtkMRMLSegmentationNode()
            slicer.mrmlScene.AddNode(seg_node)
            seg_node.CreateDefaultDisplayNodes()
            if ref_node is not None:
                seg_node.SetReferenceImageGeometryParameterFromVolumeNode(ref_node)

            if seg_cfg.get("mode", "per_label_images") == "per_label_images":
                for seg_def in self._normalize_segment_defs(seg_cfg):
                    self._build_segment(seg_def, seg_node, ref_node)

        seg_node.GetDisplayNode().SetOpacity(seg_cfg.get("opacity", 0.5))
        self.segmentation_node = seg_node
        self.writeable["__segmentation__"] = out_path

    # ---- landmarks ----

    def _load_landmarks(self, lm_cfg):
        m_path = self.markups_out_path()
        try:
            m_node = slicer.util.loadMarkups(m_path)
        except Exception:
            print(f"[GenericSpecimen] markups not found at '{m_path}', creating a new fiducial list")
            m_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", f"{self.label}-markups")
        color = lm_cfg.get("color")
        if color and m_node.GetDisplayNode():
            m_node.GetDisplayNode().SetColor(*color)
        self.markups_node = m_node
        self.node_dict["__markups__"] = m_node
        if lm_cfg.get("writable", True):
            self.writeable["__markups__"] = m_path

    # ---- load / save / close ----

    def load(self):
        print(f"[GenericSpecimen] loading {self.label}")

        background_node = None
        label_node, label_opacity = None, None
        foreground_node, foreground_opacity = None, None

        for img_cfg in self._expand_image_entries():
            name = img_cfg["name"]
            required = img_cfg.get("required", False)
            itype = img_cfg.get("type", "volume")
            try:
                path = self.resolve_image_path(img_cfg)
                if itype == "labelmap":
                    node = slicer.util.loadLabelVolume(path)
                else:
                    node = slicer.util.loadVolume(path)
            except Exception as e:
                if required:
                    raise
                print(f"[GenericSpecimen] optional image '{name}' not loaded: {e}")
                continue

            self.node_dict[name] = node
            self.writeable[name] = path

            preset = self._collect_preset(img_cfg, name)
            self._apply_preset(node, preset)
            opacity = preset.get("opacity", img_cfg.get("opacity"))

            role = img_cfg.get("role")
            if role == "background":
                background_node = node
            elif role == "label":
                label_node = node
                if opacity is not None:
                    label_opacity = opacity
            elif role == "foreground":
                foreground_node = node
                if opacity is not None:
                    foreground_opacity = opacity

        slice_kwargs = {}
        if background_node is not None:
            slice_kwargs["background"] = background_node
        if label_node is not None:
            slice_kwargs["label"] = label_node
            slice_kwargs["labelOpacity"] = label_opacity if label_opacity is not None else self.cfg.get("label_opacity", 0.15)
        if foreground_node is not None:
            slice_kwargs["foreground"] = foreground_node
            slice_kwargs["foregroundOpacity"] = foreground_opacity if foreground_opacity is not None else self.cfg.get("foreground_opacity", 0.5)
        if slice_kwargs:
            slicer.util.setSliceViewerLayers(**slice_kwargs)

        seg_cfg = self.cfg["segmentation"]
        if seg_cfg.get("enabled"):
            self._load_segmentation(seg_cfg)

        lm_cfg = self.cfg["landmarks"]
        if lm_cfg.get("enabled"):
            self._load_landmarks(lm_cfg)

        self._customize_workplace()

        vr_cfg = self.cfg["volume_rendering"]
        if vr_cfg.get("enabled"):
            self._start_volume_rendering(vr_cfg)

    def _customize_workplace(self):
        defaultSegmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
        defaultSegmentEditorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
        slicer.mrmlScene.AddDefaultNode(defaultSegmentEditorNode)

        sliceCompositeNodes = slicer.util.getNodesByClass('vtkMRMLSliceCompositeNode')
        defaultSliceCompositeNode = slicer.mrmlScene.GetDefaultNodeByClass('vtkMRMLSliceCompositeNode')
        if not defaultSliceCompositeNode:
            defaultSliceCompositeNode = slicer.mrmlScene.CreateNodeByClass('vtkMRMLSliceCompositeNode')
            defaultSliceCompositeNode.UnRegister(None)
            slicer.mrmlScene.AddDefaultNode(defaultSliceCompositeNode)
        sliceCompositeNodes.append(defaultSliceCompositeNode)
        for n in sliceCompositeNodes:
            n.SetLinkedControl(True)

        crosshair = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode")
        if crosshair:
            crosshair.SetCrosshairBehavior(crosshair.OffsetJumpSlice)
            crosshair.SetCrosshairToFine()
            crosshair.SetCrosshairMode(crosshair.ShowBasic)

        wl_cfg = self.cfg.get("window_level", {})
        if wl_cfg.get("enabled"):
            for v in slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeDisplayNode"):
                v.InterpolateOff()
                v.SetAutoWindowLevel(0)
                v.SetWindowLevelMinMax(wl_cfg.get("min", -150), wl_cfg.get("max", 700))

        if self.segmentation_node is not None:
            seg = self.segmentation_node.GetSegmentation()
            for seg_id in list(seg.GetSegmentIDs()):
                self.segmentation_node.GetDisplayNode().SetSegmentOpacity2DFill(seg_id, 0.85)
                self.segmentation_node.GetDisplayNode().SetSegmentOpacity2DOutline(seg_id, 1)

    def _start_volume_rendering(self, vr_cfg):
        src_node = self.node_dict.get(vr_cfg.get("source_image"))
        if src_node is None:
            print(f"[GenericSpecimen] volume rendering source '{vr_cfg.get('source_image')}' not loaded, skipping")
            return

        logic = slicer.modules.volumerendering.logic()
        displayNode = logic.CreateVolumeRenderingDisplayNode()
        displayNode.UnRegister(logic)
        slicer.mrmlScene.AddNode(displayNode)
        src_node.AddAndObserveDisplayNodeID(displayNode.GetID())
        logic.UpdateDisplayNodeFromVolumeNode(displayNode, src_node)

        preset_name = vr_cfg.get("preset")
        if preset_name:
            preset = logic.GetPresetByName(preset_name)
            if preset:
                displayNode.GetVolumePropertyNode().Copy(preset)

        self.volume_rendering_node = displayNode
        roiNode = displayNode.GetROINode()
        if not roiNode:
            displayNode.CreateDefaultROI()
            roiNode = displayNode.GetROINode()
        self.volume_rendering_roi = [roiNode]

        slicer.app.processEvents()
        layoutManager = slicer.app.layoutManager()
        threeDWidget = layoutManager.threeDWidget(0)
        if threeDWidget:
            threeDView = threeDWidget.threeDView()
            viewNode = threeDView.mrmlViewNode()
            if viewNode:
                viewNode.SetOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeAxes)
                viewNode.SetOrientationMarkerSize(slicer.vtkMRMLAbstractViewNode.OrientationMarkerSizeLarge)
                viewNode.SetBoxVisible(False)
            threeDView.resetFocalPoint()
            threeDView.resetCamera()

        if self.markups_node is not None:
            selectionNode = slicer.app.applicationLogic().GetSelectionNode()
            selectionNode.SetReferenceActivePlaceNodeID(self.markups_node.GetID())
            markupsLogic = slicer.modules.markups.logic()
            markupsLogic.SetActiveListID(self.markups_node)

    # ---- save / close ----

    def save(self):
        print(f"[GenericSpecimen] saving {self.label}")
        if not os.path.isdir(self.out_dir):
            os.makedirs(self.out_dir, exist_ok=True)

        for logical_name, path in self.writeable.items():
            out_dir = os.path.dirname(path)
            if out_dir and not os.path.isdir(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            if logical_name == "__segmentation__":
                node = self.segmentation_node
            elif logical_name == "__markups__":
                node = self.markups_node
            else:
                node = self.node_dict.get(logical_name)

            if node is None:
                continue

            storage = node.CreateDefaultStorageNode()
            storage.SetFileName(path)
            storage.WriteData(node)

    def close(self):
        if slicer.mrmlScene.IsClosing():
            print("[GenericSpecimen] scene is closing, skip cleanup")
            return

        print(f"[GenericSpecimen] closing {self.label}")

        if self.volume_rendering_node and slicer.mrmlScene.IsNodePresent(self.volume_rendering_node):
            slicer.mrmlScene.RemoveNode(self.volume_rendering_node)
        self.volume_rendering_node = None

        for roi in self.volume_rendering_roi:
            if roi and slicer.mrmlScene.IsNodePresent(roi):
                slicer.mrmlScene.RemoveNode(roi)
        self.volume_rendering_roi = []

        all_nodes = list(self.node_dict.values())
        if self.segmentation_node is not None and self.segmentation_node not in all_nodes:
            all_nodes.append(self.segmentation_node)

        for node in all_nodes:
            try:
                if node and slicer.mrmlScene.IsNodePresent(node):
                    slicer.mrmlScene.RemoveNode(node)
            except Exception:
                pass

        self.node_dict = {}
        self.segmentation_node = None
        self.markups_node = None


# ---------------------------------------------------------------------------
# GenericSpecimenModuleLogic
# ---------------------------------------------------------------------------

class GenericSpecimenModuleLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.cfg = None
        self.study_dir = None
        self.dbTable = None
        self.presegTable = None
        self.dbDictList = []
        self.presegDictList = []
        self.dbColumnNames = []      # raw, ordered database.csv column names (for name-based cell write-back)
        self.specimens = {}
        self.active_specimen = None
        self.default_config_path = None   # set by the wrapper module before use

    def load_config(self, config_path):
        self.cfg = load_config(config_path)
        self.study_dir = self.cfg["study_dir"]
        return self.cfg

    def _abs_path(self, rel):
        if not rel:
            return rel
        if os.path.isabs(rel):
            return rel
        return os.path.join(self.study_dir, rel)

    def setDefaultParameters(self, parameterNode):
        if not parameterNode.GetParameter("ConfigPath"):
            parameterNode.SetParameter("ConfigPath", self.default_config_path or "")

        if self.cfg is None:
            config_path = parameterNode.GetParameter("ConfigPath") or self.default_config_path
            if config_path and os.path.exists(config_path):
                try:
                    self.load_config(config_path)
                except Exception as e:
                    print(f"[GenericSpecimenModule] failed to load config '{config_path}': {e}")

        if self.cfg:
            if not parameterNode.GetParameter("DatabaseCSVPath"):
                parameterNode.SetParameter("DatabaseCSVPath", self._abs_path(self.cfg.get("database_csv_path", "")))
            if not parameterNode.GetParameter("PresegCSVPath"):
                parameterNode.SetParameter("PresegCSVPath", self._abs_path(self.cfg.get("preseg_csv_path", "")))

    def get_node_if_loaded(self, file_path):
        for n in slicer.mrmlScene.GetNodes():
            try:
                if n.GetStorageNode().GetFileName() == file_path:
                    return n.GetName()
            except Exception:
                continue
        return ""

    def initializeStudy(self):
        if self.cfg is None:
            raise RuntimeError("No config loaded. Select a config.json first.")

        db_path = self.getParameterNode().GetParameter("DatabaseCSVPath")
        preseg_path = self.getParameterNode().GetParameter("PresegCSVPath")

        print(f"Database path: {db_path}")
        print(f"Presegmentation path: {preseg_path}")

        try:
            node = slicer.util.getNode(self.get_node_if_loaded(db_path))
            self.dbTable = node
        except slicer.util.MRMLNodeNotFoundException:
            self.dbTable = slicer.util.loadTable(db_path)

        try:
            node = slicer.util.getNode(self.get_node_if_loaded(preseg_path))
            self.presegTable = node
        except slicer.util.MRMLNodeNotFoundException:
            self.presegTable = slicer.util.loadTable(preseg_path)

        self.dbDictList, self.dbColumnNames = self._table_to_dicts(self.dbTable, return_columns=True)
        self.presegDictList = self._table_to_dicts(self.presegTable)

        key_columns = self.cfg["key_columns"]
        done_col = self.cfg["done_column"]

        db_keys = [tuple(row.get(c, "") for c in key_columns) for row in self.dbDictList]
        preseg_keys = [tuple(row.get(c, "") for c in key_columns) for row in self.presegDictList]
        common_keys = sorted(set(db_keys).intersection(set(preseg_keys)))

        self.specimens = {}
        for key in common_keys:
            db_idx = db_keys.index(key)
            db_row = self.dbDictList[db_idx]
            preseg_row = next(
                (r for r in self.presegDictList if tuple(r.get(c, "") for c in key_columns) == key), {})

            specimen = GenericSpecimen(key, self.cfg, db_row, preseg_row, self.study_dir)
            specimen.row_index = db_idx
            specimen.done_col_index = self.dbColumnNames.index(done_col) if done_col in self.dbColumnNames else None
            self.specimens[key] = specimen

        print(f"[GenericSpecimenModule] initialized {len(self.specimens)} specimens")

    def _table_to_dicts(self, table, return_columns=False):
        dict_list = []
        _t = table.GetTable()
        ncol = _t.GetNumberOfColumns()
        nrow = _t.GetNumberOfRows()
        colnames = [_t.GetColumnName(j) for j in range(ncol)]
        for i in range(nrow):
            row = _t.GetRow(i)
            dict_list.append({colnames[j]: row.GetValue(j).ToString() for j in range(ncol)})
        if return_columns:
            return dict_list, colnames
        return dict_list

    def confirm(self, text):
        c = ctk.ctkMessageBox()
        c.setIcon(qt.QMessageBox.Information)
        c.setText(text)
        c.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
        c.setDefaultButton(qt.QMessageBox.Ok)
        return c.exec_() == qt.QMessageBox.Yes

    def info(self, text):
        c = ctk.ctkMessageBox()
        c.setIcon(qt.QMessageBox.Information)
        c.setText(text)
        c.setStandardButtons(qt.QMessageBox.Ok)
        c.setDefaultButton(qt.QMessageBox.Ok)
        c.exec_()

    def load_specimen(self, key):
        target = self.specimens.get(key)
        if isinstance(self.active_specimen, GenericSpecimen):
            self.info("A specimen has already been loaded.")
            return False
        if target is None:
            raise ValueError(f"Specimen {key} not initialized")
        target.load()
        self.active_specimen = target
        return True

    def close_active_specimen(self, no_question=False):
        if no_question:
            if self.active_specimen is not None:
                self.active_specimen.close()
                self.active_specimen = None
            return
        if not isinstance(self.active_specimen, GenericSpecimen):
            self.info("There is no active specimen to close.")
            return
        if not self.confirm("Do you really want to close the active specimen?"):
            return
        self.active_specimen.close()
        self.active_specimen = None

    def save_active_specimen(self):
        if not isinstance(self.active_specimen, GenericSpecimen):
            self.info("There is no active specimen to save.")
            return
        self.active_specimen.save()

    def save_db(self):
        db_path = self.getParameterNode().GetParameter("DatabaseCSVPath")
        storage = self.dbTable.CreateDefaultStorageNode()
        storage.SetFileName(db_path)
        storage.WriteData(self.dbTable)

    @property
    def hasActiveSpecimen(self):
        return isinstance(self.active_specimen, GenericSpecimen)


# ---------------------------------------------------------------------------
# GenericSpecimenModuleWidgetBase
#
# Subclass this per species. The subclass's __init__ must set
# self.logic.default_config_path (or call self.logic.load_config(...)
# directly) before / during initializeParameterNode(). See DeerSegmentor.py.
# ---------------------------------------------------------------------------

class GenericSpecimenModuleWidgetBase(ScriptedLoadableModuleWidget, VTKObservationMixin):

    # Subclasses should override these two:
    CONFIG_PATH = None                              # absolute path to this species' config.json
    UI_RESOURCE = "UI/GenericSpecimenModule.ui"      # resourcePath(...)-relative path to the .ui file

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self.tbl_selected_key = None
        self.table_lock = False

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath(self.UI_RESOURCE))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = GenericSpecimenModuleLogic()
        self.logic.default_config_path = self.CONFIG_PATH

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.ui.tbConfigPath.textChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.tbDBPath.textChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.tbPresegPath.textChanged.connect(self.updateParameterNodeFromGUI)

        self.ui.tblSpecimens.selectionModel().selectionChanged.connect(self.selected_specimen_changed)
        self.ui.tblSpecimens.itemChanged.connect(self.specimen_tbl_changed)

        self.ui.btnSelectConfig.connect('clicked(bool)', self.onBtnSelectConfig)
        self.ui.btnInitializeStudy.connect('clicked(bool)', self.onBtnInitializeStudy)
        self.ui.btnSelectDB.connect('clicked(bool)', self.onBtnSelectDB)
        self.ui.btnSelectPreseg.connect('clicked(bool)', self.onBtnSelectPreseg)
        self.ui.btnBatchExport.connect('clicked(bool)', self.onBtnBatchExport)
        self.ui.btnLoadSelected.connect('clicked(bool)', self.onBtnLoadSelected)
        self.ui.btnSaveActiveSpecimen.connect('clicked(bool)', self.onBtnSaveActiveSpecimen)
        self.ui.btnCloseActiveSpecimen.connect('clicked(bool)', self.onBtnCloseActiveSpecimen)
        self.ui.btnSaveDB.connect('clicked(bool)', self.onBtnSaveDB)

        # If this wrapper module is locked to a single config (CONFIG_PATH set),
        # hide the config picker row - there is nothing to switch between.
        if self.CONFIG_PATH:
            self.ui.lblConfig.visible = False
            self.ui.btnSelectConfig.visible = False
            self.ui.tbConfigPath.visible = False

        self.initializeParameterNode()

    def cleanup(self):
        self.removeObservers()

    def enter(self):
        self.initializeParameterNode()

    def exit(self):
        self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    def onSceneStartClose(self, caller, event):
        if self.logic and self.logic.hasActiveSpecimen:
            self.logic.close_active_specimen(no_question=True)
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event):
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self):
        self.setParameterNode(self.logic.getParameterNode())

    def setParameterNode(self, inputParameterNode):
        if inputParameterNode:
            self.logic.setDefaultParameters(inputParameterNode)
        if self._parameterNode is not None:
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self._parameterNode = inputParameterNode
        if self._parameterNode is not None:
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self.updateGUIFromParameterNode()

    def updateGUIFromParameterNode(self, caller=None, event=None):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return
        self._updatingGUIFromParameterNode = True
        self.ui.tbConfigPath.text = str(self._parameterNode.GetParameter("ConfigPath"))
        self.ui.tbDBPath.text = str(self._parameterNode.GetParameter("DatabaseCSVPath"))
        self.ui.tbPresegPath.text = str(self._parameterNode.GetParameter("PresegCSVPath"))
        self._updatingGUIFromParameterNode = False

    def updateParameterNodeFromGUI(self, caller=None, event=None):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return
        wasModified = self._parameterNode.StartModify()
        self._parameterNode.SetParameter("ConfigPath", str(self.ui.tbConfigPath.text))
        self._parameterNode.SetParameter("DatabaseCSVPath", str(self.ui.tbDBPath.text))
        self._parameterNode.SetParameter("PresegCSVPath", str(self.ui.tbPresegPath.text))
        self._parameterNode.EndModify(wasModified)

    # ---- GUI actions ----

    def onBtnSelectConfig(self):
        fname = QFileDialog.getOpenFileName(None, 'Open config', str(self.ui.tbConfigPath.text), "JSON files (*.json)")
        if not fname:
            return
        self._parameterNode.SetParameter("ConfigPath", fname)
        try:
            self.logic.load_config(fname)
            self._parameterNode.SetParameter("DatabaseCSVPath", self.logic._abs_path(self.logic.cfg.get("database_csv_path", "")))
            self._parameterNode.SetParameter("PresegCSVPath", self.logic._abs_path(self.logic.cfg.get("preseg_csv_path", "")))
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to load config: {e}")

    def onBtnSelectDB(self):
        fname = QFileDialog.getOpenFileName(None, 'Open file', str(self.ui.tbDBPath.text), "CSV files (*.csv)")
        if fname:
            self._parameterNode.SetParameter("DatabaseCSVPath", fname)

    def onBtnSelectPreseg(self):
        fname = QFileDialog.getOpenFileName(None, 'Open file', str(self.ui.tbPresegPath.text), "CSV files (*.csv)")
        if fname:
            self._parameterNode.SetParameter("PresegCSVPath", fname)

    def onBtnInitializeStudy(self):
        try:
            if self.logic.cfg is None:
                self.logic.load_config(str(self.ui.tbConfigPath.text) or self.CONFIG_PATH)
            self.logic.initializeStudy()
            self.show_specimen_table()
        except Exception as e:
            slicer.util.errorDisplay("Failed to initialize study: " + str(e))
            import traceback
            traceback.print_exc()

    def show_specimen_table(self):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return
        wasModified = self._parameterNode.StartModify()

        cfg = self.logic.cfg
        columns = cfg["table_columns"]
        keys = sorted(self.logic.specimens.keys())
        self._displayed_keys = keys   # row -> key, independent of raw csv row order

        tbl = self.ui.tblSpecimens
        tbl.clear()
        tbl.clearContents()
        tbl.setColumnCount(len(columns))
        tbl.setRowCount(len(keys))

        done_col = cfg["done_column"]
        for i, key in enumerate(keys):
            specimen = self.logic.specimens[key]
            specimen.update_done(self.logic.dbTable)
            for j, col in enumerate(columns):
                tbl.setItem(i, j, qt.QTableWidgetItem(specimen.db_info.get(col, "")))
            if specimen.db_info.get(done_col) == str(1):
                for j in range(tbl.columnCount):
                    tbl.item(i, j).setBackground(qt.QColor(0, 127, 0))

        tbl.setHorizontalHeaderLabels(columns)
        tbl.resizeColumnsToContents()
        self._parameterNode.EndModify(wasModified)

    def selected_specimen_changed(self):
        sel = self.ui.tblSpecimens.selectedIndexes()
        if len(sel) == 0:
            return
        row = sel[0].row()
        key_columns = self.logic.cfg["key_columns"]
        columns = self.logic.cfg["table_columns"]
        key = tuple(self.ui.tblSpecimens.item(row, columns.index(c)).text() for c in key_columns)
        self.tbl_selected_key = key
        self.ui.lblSelectedSpecimen.text = "-".join(key)

    def specimen_tbl_changed(self):
        """Any cell the user edits gets written back to the underlying database
        vtkTable by COLUMN NAME + the specimen's real row_index (not by the
        widget's own row/column position), so this is safe regardless of
        table_columns being a subset of database.csv, or of the display order
        (sorted by key) differing from the raw csv row order."""
        if self.table_lock:
            return
        self.table_lock = True
        try:
            tbl = self.ui.tblSpecimens
            sel = tbl.selectedIndexes()
            if len(sel) == 0:
                return
            row, col = sel[0].row(), sel[0].column()

            cfg = self.logic.cfg
            columns = cfg["table_columns"]
            done_col_display_idx = columns.index(cfg["done_column"]) if cfg["done_column"] in columns else tbl.columnCount - 1

            current_done = tbl.item(row, done_col_display_idx).text()
            if str(current_done) == "1":
                for j in range(tbl.columnCount):
                    tbl.item(row, j).setBackground(qt.QColor(0, 127, 0))
            else:
                for j in range(tbl.columnCount):
                    tbl.item(row, j).setBackground(qt.QColor("transparent"))

            key = self._displayed_keys[row]
            specimen = self.logic.specimens.get(key)
            if specimen is None or specimen.row_index is None:
                return

            col_name = columns[col]
            if col_name not in self.logic.dbColumnNames:
                print(f"[GenericSpecimenModule] column '{col_name}' not present in database.csv, not writing back")
                return
            real_col = self.logic.dbColumnNames.index(col_name)

            val = tbl.item(row, col).text()
            self.logic.dbTable.SetCellText(specimen.row_index, real_col, val)
            specimen.db_info[col_name] = val

        except Exception as e:
            slicer.util.errorDisplay("Failed to update table: " + str(e))
            import traceback
            traceback.print_exc()
        finally:
            self.table_lock = False

    def onBtnLoadSelected(self):
        try:
            if not self.tbl_selected_key:
                return
            self.logic.load_specimen(self.tbl_selected_key)
            self.ui.btnLoadSelected.enabled = not self.logic.hasActiveSpecimen
            if self.logic.hasActiveSpecimen:
                self.ui.lblActiveSpecimen.text = self.logic.active_specimen.label
        except Exception as e:
            slicer.util.errorDisplay("Failed to load specimen: " + str(e))
            import traceback
            traceback.print_exc()

    def onBtnSaveActiveSpecimen(self):
        try:
            self.logic.save_active_specimen()
        except Exception as e:
            slicer.util.errorDisplay("Failed to save specimen: " + str(e))
            import traceback
            traceback.print_exc()

    def onBtnCloseActiveSpecimen(self):
        try:
            self.logic.close_active_specimen()
            self.ui.btnLoadSelected.enabled = not self.logic.hasActiveSpecimen
            if not self.logic.hasActiveSpecimen:
                self.ui.lblActiveSpecimen.text = ""
        except Exception as e:
            slicer.util.errorDisplay("Failed to close specimen: " + str(e))
            import traceback
            traceback.print_exc()

    def onBtnSaveDB(self):
        try:
            self.logic.save_db()
        except Exception as e:
            slicer.util.errorDisplay("Failed to save database: " + str(e))
            import traceback
            traceback.print_exc()

    def onBtnBatchExport(self):
        batch_exporter(self.logic)


# ---------------------------------------------------------------------------
# Generic batch export (config-driven equivalent of the Pig/Rabbit/Deer
# batch_exporter() functions)
# ---------------------------------------------------------------------------

def batch_exporter(logic):
    if logic.hasActiveSpecimen:
        print("Please close the active specimen before running a batch export.")
        return

    cfg = logic.cfg
    be_cfg = cfg.get("batch_export", {})
    if not be_cfg.get("enabled"):
        print("[batch_exporter] batch_export is not enabled in the config.")
        return

    logic.initializeStudy()
    done_col = cfg["done_column"]
    segments_filter = be_cfg.get("segments_filter")   # optional allow-list of segment names to export

    for key, specimen in logic.specimens.items():
        if specimen.db_info.get(done_col) != "1":
            continue

        logic.load_specimen(key)

        be_out_dir = be_cfg.get("output_dir")
        if be_out_dir:
            out_dir = be_out_dir if os.path.isabs(be_out_dir) else os.path.join(logic.study_dir, be_out_dir)
        else:
            out_dir = specimen.out_dir
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        if be_cfg.get("export_segments") and specimen.segmentation_node is not None:
            ref_name = be_cfg.get("reference_image") or cfg["segmentation"].get("reference_image")
            ref_node = specimen.node_dict.get(ref_name)
            seg = specimen.segmentation_node.GetSegmentation()

            for seg_id in list(seg.GetSegmentIDs()):
                segment = seg.GetSegment(seg_id)
                seg_name = segment.GetName()
                if segments_filter and seg_name not in segments_filter:
                    continue

                labelmap = slicer.vtkMRMLLabelMapVolumeNode()
                slicer.mrmlScene.AddNode(labelmap)
                ids = vtk.vtkStringArray()
                ids.InsertNextValue(seg_id)
                slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(
                    specimen.segmentation_node, ids, labelmap, ref_node)

                storage = labelmap.CreateDefaultStorageNode()
                out_file = os.path.join(out_dir, f"{specimen.label}-{seg_name}.nii.gz")
                storage.SetFileName(out_file)
                storage.WriteData(labelmap)
                print(f"[batch_exporter] saved {out_file}")
                slicer.mrmlScene.RemoveNode(storage)
                slicer.mrmlScene.RemoveNode(labelmap)

        if be_cfg.get("export_markups") and specimen.markups_node is not None:
            out_file = os.path.join(out_dir, f"{specimen.label}-markups.mrk.json")
            storage = specimen.markups_node.CreateDefaultStorageNode()
            storage.SetFileName(out_file)
            storage.WriteData(specimen.markups_node)
            print(f"[batch_exporter] saved {out_file}")
            slicer.mrmlScene.RemoveNode(storage)

        logic.close_active_specimen(no_question=True)
