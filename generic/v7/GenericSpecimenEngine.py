"""
GenericSpecimenEngine
======================

Shared, JSON-config-driven engine. Not a Slicer module on its own.
Config handling lives in ConfigModel.py (StudyConfig) - consumed here via
attribute access, not raw dict.get().
"""

import os
import re
import csv
from dataclasses import replace

import qt
import vtk
import ctk

from qt import QFileDialog

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from Resources.ConfigModel import (
    StudyConfig, ImageConfig, SegmentConfig, SegmentationConfig,
    LandmarksConfig, VolumeRenderingConfig, load_config,
    merge_image_overrides, merge_segment_overrides,
)
from Resources.ConfigEditor import ConfigEditorDialog


# ---------------------------------------------------------------------------
# GenericSpecimen
# ---------------------------------------------------------------------------

class GenericSpecimen:
    def __init__(self, key_values, cfg: StudyConfig, db_row, preseg_row, study_dir):
        self.cfg = cfg
        self.key_columns = cfg.key_columns
        self.key_values = tuple(key_values)
        self.context = dict(zip(self.key_columns, self.key_values))
        self.db_info = dict(db_row or {})
        self.preseg_info = dict(preseg_row or {})
        self.study_dir = study_dir

        self.node_dict = {}
        self.writeable = {}
        self.segmentation_node = None
        self.markups_node = None
        self.volume_rendering_node = None
        self.volume_rendering_roi = []

        self.row_index = None
        self.done_col_index = None

    @property
    def key(self):
        return self.key_values

    @property
    def label(self):
        return "-".join(str(v) for v in self.key_values)

    @property
    def out_dir(self):
        parts = [str(self.context.get(k, self.db_info.get(k, k))) for k in self.cfg.output_dir_pattern]
        return os.path.join(self.study_dir, *parts)

    def batch_value(self):
        col = self.cfg.batch_mode.column
        return self.db_info.get(col, "") if col else None

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

    def markups_out_path(self):
        lm_cfg = self.cfg.landmarks
        rel = self.preseg_info.get(lm_cfg.csv_column) if lm_cfg.csv_column else None
        if not rel:
            pattern = lm_cfg.path_pattern or "{label}-markups.mrk.json"
            rel = pattern.format(**self._context({"label": self.label}))
        return self._to_abs(rel)

    def segmentation_out_path(self):
        seg_cfg = self.cfg.segmentation
        return os.path.join(self.out_dir, seg_cfg.output_filename or "segment.seg.nrrd")

    def update_done(self, table):
        if self.row_index is None or self.done_col_index is None:
            return
        try:
            self.db_info[self.cfg.done_column] = table.GetCellText(self.row_index, self.done_col_index)
        except Exception as e:
            slicer.util.errorDisplay("Failed to update done state: " + str(e))

    def _expand_image_entries(self):
        jobs = []
        for img_cfg in self.cfg.images:
            if not img_cfg.pattern:
                jobs.append(img_cfg)
                continue
            regex = re.compile(img_cfg.pattern)
            for col, val in self.preseg_info.items():
                if col in self.key_columns or not val or not regex.match(col):
                    continue
                name = col
                if img_cfg.strip_prefix and name.startswith(img_cfg.strip_prefix):
                    name = name[len(img_cfg.strip_prefix):]
                if img_cfg.strip_suffix and name.endswith(img_cfg.strip_suffix):
                    name = name[:-len(img_cfg.strip_suffix)]
                jobs.append(replace(img_cfg, name=name, csv_column=col,
                                     pattern=None, strip_prefix=None, strip_suffix=None))
        return jobs

    def _resolve_image_cfg(self, img_cfg: ImageConfig) -> ImageConfig:
        preset = self.cfg.presets.get(img_cfg.preset) if img_cfg.preset else None
        return merge_image_overrides(self.cfg.defaults.image, preset, img_cfg)

    def resolve_image_path(self, img_cfg: ImageConfig):
        if img_cfg.csv_column and self.preseg_info.get(img_cfg.csv_column):
            rel = self.preseg_info[img_cfg.csv_column]
        elif img_cfg.path_pattern:
            rel = img_cfg.path_pattern.format(**self._context({"name": img_cfg.name}))
        else:
            raise ValueError(f"Cannot resolve path for image '{img_cfg.name}': no csv_column value and no path_pattern given")
        return self._to_abs(rel)

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

    def _apply_visual_props(self, node, props: ImageConfig):
        disp = node.GetDisplayNode()
        if disp is None:
            return
        wl = props.window_level
        if wl:
            if wl.auto:
                disp.SetAutoWindowLevel(1)
            elif wl.window is not None or wl.level is not None:
                disp.SetAutoWindowLevel(0)
                disp.SetWindowLevel(wl.window if wl.window is not None else 1, wl.level if wl.level is not None else 0)
            else:
                disp.SetAutoWindowLevel(0)
                disp.SetWindowLevelMinMax(wl.min if wl.min is not None else -150, wl.max if wl.max is not None else 700)
        if props.interpolate is not None:
            disp.SetInterpolate(1 if props.interpolate else 0)
        if props.color_table:
            color_node = self._resolve_color_node(props.color_table)
            if color_node:
                disp.SetAndObserveColorNodeID(color_node.GetID())
        th = props.threshold
        if th:
            disp.SetThreshold(th.min if th.min is not None else 0, th.max if th.max is not None else 0)
            (disp.ApplyThresholdOn() if (th.apply if th.apply is not None else True) else disp.ApplyThresholdOff())

    def _resolve_segment_cfg(self, seg_def: SegmentConfig) -> SegmentConfig:
        return merge_segment_overrides(self.cfg.defaults.segment, seg_def)

    def resolve_segment_path(self, seg_cfg: SegmentationConfig, seg_def: SegmentConfig):
        if seg_def.csv_column and self.preseg_info.get(seg_def.csv_column):
            return self._to_abs(self.preseg_info[seg_def.csv_column])
        pattern = seg_def.path_pattern or seg_cfg.path_pattern
        if pattern:
            return self._to_abs(pattern.format(**self._context({"segment_name": seg_def.name})))
        return None

    def _add_empty_segment(self, segmentation_node, name, reference_volume_node, color=None):
        if reference_volume_node is None:
            print(f"[GenericSpecimen] no reference volume, skipping empty segment '{name}'")
            return
        dummy = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        slicer.modules.volumes.logic().CreateLabelVolumeFromVolume(slicer.mrmlScene, dummy, reference_volume_node)
        dummy.GetImageData().GetPointData().GetScalars().Fill(0)
        img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(dummy)
        if color:
            segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(img, name, color)
        else:
            segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(img, name)
        slicer.mrmlScene.RemoveNode(dummy)

    def _build_segment(self, seg_def: SegmentConfig, segmentation_node, reference_volume_node):
        seg_def = self._resolve_segment_cfg(seg_def)
        name, color, source = seg_def.name, seg_def.color, (seg_def.source or "file")

        if source == "empty":
            self._add_empty_segment(segmentation_node, name, reference_volume_node, color)
            return
        try:
            path = self.resolve_segment_path(self.cfg.segmentation, seg_def)
        except Exception:
            path = None
        if path is None:
            print(f"[GenericSpecimen] segment '{name}': no path resolvable, creating empty segment instead")
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

    def _load_segmentation(self, seg_cfg: SegmentationConfig):
        out_path = self.segmentation_out_path()
        ref_node = self.node_dict.get(seg_cfg.reference_image) if seg_cfg.reference_image else None

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
            for seg_def in seg_cfg.segments:
                self._build_segment(seg_def, seg_node, ref_node)
            seg_node.SetName("Segmentation")

        self.segmentation_node = seg_node
        self.writeable["__segmentation__"] = out_path

    def _load_landmarks(self, lm_cfg: LandmarksConfig):
        m_path = self.markups_out_path()
        try:
            m_node = slicer.util.loadMarkups(m_path)
        except Exception:
            if lm_cfg.template_path and os.path.exists(lm_cfg.template_path):
                m_node = slicer.util.loadMarkups(lm_cfg.template_path)
                m_node.SetName(f"{self.label}-markups")
            else:
                m_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", f"{self.label}-markups")
        if lm_cfg.color and m_node.GetDisplayNode():
            m_node.GetDisplayNode().SetColor(*lm_cfg.color)
        self.markups_node = m_node
        self.node_dict["__markups__"] = m_node
        if lm_cfg.writable if lm_cfg.writable is not None else True:
            self.writeable["__markups__"] = m_path

    def load(self):
        print(f"[GenericSpecimen] loading {self.label}")
        background_node = None
        label_node, label_opacity = None, None
        foreground_node, foreground_opacity = None, None

        for raw_img_cfg in self._expand_image_entries():
            img_cfg = self._resolve_image_cfg(raw_img_cfg)
            name = img_cfg.name
            required = img_cfg.required or False
            itype = img_cfg.type or "volume"
            try:
                path = self.resolve_image_path(img_cfg)
                node = slicer.util.loadLabelVolume(path) if itype == "labelmap" else slicer.util.loadVolume(path)
                node.SetName(name)
            except Exception as e:
                if required:
                    raise
                print(f"[GenericSpecimen] optional image '{name}' not loaded: {e}")
                continue

            self.node_dict[name] = node
            self.writeable[name] = path
            self._apply_visual_props(node, img_cfg)
            opacity = img_cfg.opacity
            role = img_cfg.role
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
            slice_kwargs["labelOpacity"] = label_opacity if label_opacity is not None else 0.15
        if foreground_node is not None:
            slice_kwargs["foreground"] = foreground_node
            slice_kwargs["foregroundOpacity"] = foreground_opacity if foreground_opacity is not None else 0.5
        if slice_kwargs:
            slicer.util.setSliceViewerLayers(**slice_kwargs)

        seg_cfg = self.cfg.segmentation
        if seg_cfg.enabled:
            self._load_segmentation(seg_cfg)

        lm_cfg = self.cfg.landmarks
        if lm_cfg.enabled:
            self._load_landmarks(lm_cfg)

        self._customize_workplace()

        vr_cfg = self.cfg.volume_rendering
        if vr_cfg.enabled:
            self._start_volume_rendering(vr_cfg)

        if seg_cfg.enabled and self.cfg.segment_editor.is_configured():
            self._activate_segment_editor()

    def _activate_segment_editor(self):
        """Switch to the Segment Editor module with THIS specimen's segmentation
        already selected and configured. Safe (unlike touching a bare template
        node) because we explicitly attach a real segmentation/source volume
        to the widget's node BEFORE activating any effect on it - activating
        an effect with no segmentation/volume context is what crashed before.
        """
        if self.segmentation_node is None:
            return

        try:
            segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
        except Exception as e:
            print(f"[GenericSpecimen] could not access the Segment Editor widget: {e}")
            return

        segmentEditorWidget.setSegmentationNode(self.segmentation_node)

        ref_name = self.cfg.segmentation.reference_image
        ref_node = self.node_dict.get(ref_name) if ref_name else None
        if ref_node is not None:
            try:
                segmentEditorWidget.setSourceVolumeNode(ref_node)      # Slicer 5.2+
            except AttributeError:
                segmentEditorWidget.setMasterVolumeNode(ref_node)      # older Slicer

        editorNode = segmentEditorWidget.mrmlSegmentEditorNode()
        if editorNode is None:
            print("[GenericSpecimen] Segment Editor widget produced no live node, skipping")
            return

        se_cfg = self.cfg.segment_editor
        overwrite_map = {
            "none": slicer.vtkMRMLSegmentEditorNode.OverwriteNone,
            "all_segments": slicer.vtkMRMLSegmentEditorNode.OverwriteAllSegments,
            "visible_segments": slicer.vtkMRMLSegmentEditorNode.OverwriteVisibleSegments,
        }
        editorNode.SetOverwriteMode(overwrite_map.get(se_cfg.overwrite_mode or "none", slicer.vtkMRMLSegmentEditorNode.OverwriteNone))

        brush_cfg = se_cfg.brush
        if brush_cfg:
            if brush_cfg.shape == "sphere":
                editorNode.SetAttribute("BrushSphere", "1")
            elif brush_cfg.shape == "circle":
                editorNode.SetAttribute("BrushSphere", "0")
            if brush_cfg.diameter_mm is not None:
                if brush_cfg.relative:
                    editorNode.SetAttribute("BrushDiameterIsRelative", "1")
                    editorNode.SetAttribute("BrushRelativeDiameter", str(brush_cfg.diameter_mm))
                else:
                    editorNode.SetAttribute("BrushDiameterIsRelative", "0")
                    editorNode.SetAttribute("BrushAbsoluteDiameter", str(brush_cfg.diameter_mm))

        for k, v in se_cfg.attributes.items():
            editorNode.SetAttribute(k, str(v))

        # Safe now: editorNode has a real segmentation (and source volume, if
        # resolved) attached above - NOT a bare template. Deliberately not
        # touching the live effect object (no effect.setParameter(), no
        # manual updateGUIFromMRML()) - SetAttribute()/SetActiveEffectName()
        # already trigger the widget's own automatic MRML->GUI sync; calling
        # into the effect object again on top of that is what caused the
        # signal-blocking GUI freeze in an earlier version.
        if se_cfg.active_effect:
            editorNode.SetActiveEffectName(se_cfg.active_effect)

        # Bring the module into view LAST, once everything above is already
        # configured, so the user never sees an unconfigured flash of it.
        slicer.util.selectModule("SegmentEditor")

    def _customize_workplace(self):
        defaultSegmentEditorNode = slicer.mrmlScene.GetDefaultNodeByClass("vtkMRMLSegmentEditorNode")
        if defaultSegmentEditorNode is None:
            defaultSegmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
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

        wl_cfg = self.cfg.window_level
        if wl_cfg.enabled:
            for v in slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeDisplayNode"):
                v.InterpolateOff()
                v.SetAutoWindowLevel(0)
                v.SetWindowLevelMinMax(wl_cfg.min if wl_cfg.min is not None else -150, wl_cfg.max if wl_cfg.max is not None else 700)

        if self.segmentation_node is not None:
            seg = self.segmentation_node.GetSegmentation()
            for seg_id in list(seg.GetSegmentIDs()):
                self.segmentation_node.GetDisplayNode().SetSegmentOpacity2DFill(seg_id, 0.85)
                self.segmentation_node.GetDisplayNode().SetSegmentOpacity2DOutline(seg_id, 1)

    def _start_volume_rendering(self, vr_cfg: VolumeRenderingConfig):
        src_node = self.node_dict.get(vr_cfg.source_image)
        if src_node is None:
            print(f"[GenericSpecimen] volume rendering source '{vr_cfg.source_image}' not loaded, skipping")
            return
        logic = slicer.modules.volumerendering.logic()
        displayNode = logic.CreateVolumeRenderingDisplayNode()
        displayNode.UnRegister(logic)
        slicer.mrmlScene.AddNode(displayNode)
        src_node.AddAndObserveDisplayNodeID(displayNode.GetID())
        logic.UpdateDisplayNodeFromVolumeNode(displayNode, src_node)
        if vr_cfg.preset:
            preset = logic.GetPresetByName(vr_cfg.preset)
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
            slicer.modules.markups.logic().SetActiveListID(self.markups_node)

    def save(self):
        print(f"[GenericSpecimen] saving {self.label}")
        if not os.path.isdir(self.out_dir):
            os.makedirs(self.out_dir, exist_ok=True)
        for logical_name, path in self.writeable.items():
            out_dir = os.path.dirname(path)
            if out_dir and not os.path.isdir(out_dir):
                os.makedirs(out_dir, exist_ok=True)
            node = (self.segmentation_node if logical_name == "__segmentation__" else
                    self.markups_node if logical_name == "__markups__" else
                    self.node_dict.get(logical_name))
            if node is None:
                continue
            storage = node.CreateDefaultStorageNode()
            storage.SetFileName(path)
            storage.WriteData(node)

    def close(self):
        if slicer.mrmlScene.IsClosing():
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
# GenericSpecimenManagerLogic
# ---------------------------------------------------------------------------

class GenericSpecimenManagerLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.cfg: StudyConfig = None
        self.study_dir = None
        self.dbTable = None
        self.presegTable = None
        self.dbDictList = []
        self.presegDictList = []
        self.dbColumnNames = []
        self.specimens = {}
        self.active_specimen = None
        self.default_config_path = None

    def load_config(self, config_path):
        self.cfg = load_config(config_path)
        self.study_dir = self.cfg.study_dir
        return self.cfg

    def _abs_path(self, rel):
        if not rel:
            return rel
        return rel if os.path.isabs(rel) else os.path.join(self.study_dir, rel)

    def setDefaultParameters(self, parameterNode):
        if not parameterNode.GetParameter("ConfigPath"):
            parameterNode.SetParameter("ConfigPath", self.default_config_path or "")
        if self.cfg is None:
            config_path = parameterNode.GetParameter("ConfigPath") or self.default_config_path
            if config_path and os.path.exists(config_path):
                try:
                    self.load_config(config_path)
                except Exception as e:
                    print(f"[GenericSpecimenManager] failed to load config '{config_path}': {e}")
        if self.cfg:
            if not parameterNode.GetParameter("DatabaseCSVPath"):
                parameterNode.SetParameter("DatabaseCSVPath", self._abs_path(self.cfg.database_csv_path))
            if not parameterNode.GetParameter("PresegCSVPath"):
                parameterNode.SetParameter("PresegCSVPath", self._abs_path(self.cfg.preseg_csv_path))

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

        key_columns = self.cfg.key_columns
        done_col = self.cfg.done_column
        db_keys = [tuple(row.get(c, "") for c in key_columns) for row in self.dbDictList]
        preseg_keys = [tuple(row.get(c, "") for c in key_columns) for row in self.presegDictList]
        common_keys = sorted(set(db_keys).intersection(set(preseg_keys)))

        self.specimens = {}
        for key in common_keys:
            db_idx = db_keys.index(key)
            db_row = self.dbDictList[db_idx]
            preseg_row = next((r for r in self.presegDictList if tuple(r.get(c, "") for c in key_columns) == key), {})
            specimen = GenericSpecimen(key, self.cfg, db_row, preseg_row, self.study_dir)
            specimen.row_index = db_idx
            specimen.done_col_index = self.dbColumnNames.index(done_col) if done_col in self.dbColumnNames else None
            self.specimens[key] = specimen

        print(f"[GenericSpecimenManager] initialized {len(self.specimens)} specimens")
        self._configure_segment_editor_defaults()

    def _configure_segment_editor_defaults(self):
        """Apply segment_editor config ONCE, at study init, instead of on every
        specimen load. Brush/overwrite settings are study-level preferences,
        not per-specimen state, so there's no need to re-touch them on every
        load() - and doing it here avoids the whole class of timing/singleton
        problems from poking a live, possibly-not-yet-constructed Segment
        Editor widget mid specimen-load.

        IMPORTANT: BrushSphere / BrushAbsoluteDiameter / BrushRelativeDiameter /
        BrushDiameterIsRelative are COMMON parameters shared by Paint/Erase -
        they are stored as BARE attribute keys on vtkMRMLSegmentEditorNode,
        with NO effect-name prefix (confirmed against a real node's printed
        Attributes on the Slicer forum). Only EFFECT-SPECIFIC parameters use
        the "EffectName.ParamName" form (e.g. "Paint.ColorSmudge"). Earlier
        versions of this code prefixed brush keys with "Paint," / "Paint." -
        that attribute never existed, so nothing ever applied.

        Two scenarios, both handled:
          1. Fresh scene, Segment Editor never opened yet: configure the
             DEFAULT/template node (AddDefaultNode) - any node Slicer creates
             later when the module first opens inherits these values via
             its normal node-Copy-from-default mechanism.
          2. A live vtkMRMLSegmentEditorNode already exists (Segment Editor
             was already opened this session): default-node changes don't
             retroactively affect it, so patch that instance directly too.

        active_effect is intentionally NEVER set on the default/template node
        - only on an already-in-use existing node (one with a segmentation
        attached). Setting it on a bare template makes the real widget try to
        activate that effect the instant it clones the template, before any
        segmentation/volume exists - several effects crash the whole app
        natively (no Python traceback) when that context is missing.
        """
        se_cfg = self.cfg.segment_editor
        if not se_cfg.is_configured():
            return

        overwrite_map = {
            "none": slicer.vtkMRMLSegmentEditorNode.OverwriteNone,
            "all_segments": slicer.vtkMRMLSegmentEditorNode.OverwriteAllSegments,
            "visible_segments": slicer.vtkMRMLSegmentEditorNode.OverwriteVisibleSegments,
        }
        overwrite_value = overwrite_map.get(se_cfg.overwrite_mode or "none", slicer.vtkMRMLSegmentEditorNode.OverwriteNone)

        attrs = {}
        brush_cfg = se_cfg.brush
        if brush_cfg:
            if brush_cfg.shape == "sphere":
                attrs["BrushSphere"] = "1"
            elif brush_cfg.shape == "circle":
                attrs["BrushSphere"] = "0"
            if brush_cfg.diameter_mm is not None:
                if brush_cfg.relative:
                    attrs["BrushDiameterIsRelative"] = "1"
                    attrs["BrushRelativeDiameter"] = str(brush_cfg.diameter_mm)
                else:
                    attrs["BrushDiameterIsRelative"] = "0"
                    attrs["BrushAbsoluteDiameter"] = str(brush_cfg.diameter_mm)
        attrs.update({k: str(v) for k, v in se_cfg.attributes.items()})

        def _apply_common(node):
            """Safe on ANY node, including a bare template with no context:
            overwrite mode and plain data attributes never trigger live
            widget/effect behaviour by themselves."""
            node.SetOverwriteMode(overwrite_value)
            for k, v in attrs.items():
                node.SetAttribute(k, v)

        def _has_segmentation(node):
            try:
                return node.GetSegmentationNode() is not None
            except Exception:
                return False

        default_node = slicer.mrmlScene.GetDefaultNodeByClass("vtkMRMLSegmentEditorNode")
        if default_node is None:
            default_node = slicer.vtkMRMLSegmentEditorNode()
            slicer.mrmlScene.AddDefaultNode(default_node)
        # NEVER SetActiveEffectName on this node: it's a template with no
        # segmentation/source-volume attached. Forcing an effect active on it
        # makes the real Segment Editor widget try to activate that effect the
        # instant it clones the template - before anything is selected - and
        # several effects crash natively (whole-app crash, no traceback) when
        # that context is missing. This is exactly what regressed here.
        _apply_common(default_node)

        existing_node = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentEditorNode")
        if existing_node is not None and existing_node is not default_node:
            _apply_common(existing_node)
            if se_cfg.active_effect and _has_segmentation(existing_node):
                # Only safe here because this node is already genuinely in use
                # (has a segmentation attached) - not a bare/template node.
                existing_node.SetActiveEffectName(se_cfg.active_effect)

        print(f"[GenericSpecimenManager] segment editor defaults applied: overwrite={overwrite_value}, attrs={attrs}, "
              f"active_effect_requested={se_cfg.active_effect}, patched_existing_node={existing_node is not None}")

    def batch_values(self):
        """Unique, sorted values of cfg.batch_mode.column across all specimens."""
        col = self.cfg.batch_mode.column
        if not col:
            return []
        return sorted({s.db_info.get(col, "") for s in self.specimens.values()} - {""})

    def _table_to_dicts(self, table, return_columns=False):
        dict_list = []
        _t = table.GetTable()
        ncol, nrow = _t.GetNumberOfColumns(), _t.GetNumberOfRows()
        colnames = [_t.GetColumnName(j) for j in range(ncol)]
        for i in range(nrow):
            row = _t.GetRow(i)
            dict_list.append({colnames[j]: row.GetValue(j).ToString() for j in range(ncol)})
        return (dict_list, colnames) if return_columns else dict_list

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

    def save_active_specimen(self, inform_user=True):
        if not isinstance(self.active_specimen, GenericSpecimen):
            self.info("There is no active specimen to save.")
            return
        self.active_specimen.save()
        if inform_user:
            self.info(f"Specimen '{self.active_specimen.key_values}' saved.")

    def save_db(self):
        db_path = self.getParameterNode().GetParameter("DatabaseCSVPath")
        storage = self.dbTable.CreateDefaultStorageNode()
        storage.SetFileName(db_path)
        storage.WriteData(self.dbTable)

    @property
    def hasActiveSpecimen(self):
        return isinstance(self.active_specimen, GenericSpecimen)


# ---------------------------------------------------------------------------
# GenericSpecimenManagerWidgetBase
# ---------------------------------------------------------------------------

class GenericSpecimenManagerWidgetBase(ScriptedLoadableModuleWidget, VTKObservationMixin):

    CONFIG_PATH = None
    UI_RESOURCE = "UI/GenericSpecimenManager.ui"

    import os as _os
    from pathlib import Path as _Path
    BASE_DIR = _Path(_os.path.abspath(__file__)).resolve().parent
    DEFAULT_CONFIG_FOLDER = str(BASE_DIR.parent / "Config")

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self.tbl_selected_key = None
        self.table_lock = False
        self._displayed_keys = []
        self._batch_filter = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        uiWidget = slicer.util.loadUI(self.resourcePath(self.UI_RESOURCE))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        uiWidget.setMRMLScene(slicer.mrmlScene)

        self.logic = GenericSpecimenManagerLogic()
        self.logic.default_config_path = self.CONFIG_PATH

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.ui.tbConfigPath.textChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.tbDBPath.textChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.tbPresegPath.textChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.tbConfigPath.textChanged.connect(lambda: self._validatePathField(self.ui.tbConfigPath))
        self.ui.tbDBPath.textChanged.connect(lambda: self._validatePathField(self.ui.tbDBPath))
        self.ui.tbPresegPath.textChanged.connect(lambda: self._validatePathField(self.ui.tbPresegPath))
        self.ui.tblSpecimens.selectionModel().selectionChanged.connect(self.selected_specimen_changed)
        self.ui.tblSpecimens.itemChanged.connect(self.specimen_tbl_changed)

        self.ui.btnSelectConfig.connect('clicked(bool)', self.onBtnSelectConfig)
        self.ui.btnInitializeStudy.connect('clicked(bool)', self.onBtnInitializeStudy)
        self.ui.btnSelectDB.connect('clicked(bool)', self.onBtnSelectDB)
        self.ui.btnSelectPreseg.connect('clicked(bool)', self.onBtnSelectPreseg)
        self.ui.btnBatchExport.connect('clicked(bool)', self.onBtnBatchExport)
        self.ui.btnConfigEditor.connect('clicked(bool)', self.onBtnConfigEditor)
        self.ui.btnLoadSelected.connect('clicked(bool)', self.onBtnLoadSelected)
        self.ui.btnSaveActiveSpecimen.connect('clicked(bool)', self.onBtnSaveActiveSpecimen)
        self.ui.btnCloseActiveSpecimen.connect('clicked(bool)', self.onBtnCloseActiveSpecimen)
        self.ui.btnSaveDB.connect('clicked(bool)', self.onBtnSaveDB)
        self.ui.cmbBatch.currentTextChanged.connect(self.onBatchChanged)
        self.ui.wBatch.visible = False

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
        if os.path.exists(self.DEFAULT_CONFIG_FOLDER) and str(self._parameterNode.GetParameter("ConfigPath")) == "":
            self.ui.tbConfigPath.text = str(self.DEFAULT_CONFIG_FOLDER)
        else:
            self.ui.tbConfigPath.text = str(self._parameterNode.GetParameter("ConfigPath"))
        self.ui.tbDBPath.text = str(self._parameterNode.GetParameter("DatabaseCSVPath"))
        self.ui.tbPresegPath.text = str(self._parameterNode.GetParameter("PresegCSVPath"))
        for edit in (self.ui.tbConfigPath, self.ui.tbDBPath, self.ui.tbPresegPath):
            self._validatePathField(edit)
        self._updatingGUIFromParameterNode = False

    def _validatePathField(self, edit):
        """Live, passive feedback (border color + tooltip) on whether a path
        field currently points at a real file - instead of only finding out
        via a popup error after clicking Initialize Study."""
        path = str(edit.text).strip()
        if not path:
            edit.setStyleSheet("")
            edit.setToolTip("")
        elif not os.path.exists(path):
            edit.setStyleSheet("border: 1px solid #cc3333; background-color: #fff0f0;")
            edit.setToolTip("Not found: " + path)
        elif os.path.isdir(path):
            edit.setStyleSheet("border: 1px solid #cc8800; background-color: #fff8e8;")
            edit.setToolTip("This is a folder, not a file: " + path)
        else:
            edit.setStyleSheet("border: 1px solid #33aa33;")
            edit.setToolTip(path)

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
            self._parameterNode.SetParameter("DatabaseCSVPath", self.logic._abs_path(self.logic.cfg.database_csv_path))
            self._parameterNode.SetParameter("PresegCSVPath", self.logic._abs_path(self.logic.cfg.preseg_csv_path))
        except Exception as e:
            slicer.util.errorDisplay(f"Failed to load config: {e}")

    def onBtnConfigEditor(self):
        current_path = str(self.ui.tbConfigPath.text).strip() or None
        self._configEditorDialog = ConfigEditorDialog(slicer.util.mainWindow(), initial_path=current_path)
        self._configEditorDialog.setWindowModality(qt.Qt.NonModal)
        self._configEditorDialog.show()
        self._configEditorDialog.raise_()

    def onBtnSelectDB(self):
        fname = QFileDialog.getOpenFileName(None, 'Open file', str(self.ui.tbDBPath.text), "CSV files (*.csv)")
        if fname:
            self._parameterNode.SetParameter("DatabaseCSVPath", fname)

    def onBtnSelectPreseg(self):
        fname = QFileDialog.getOpenFileName(None, 'Open file', str(self.ui.tbPresegPath.text), "CSV files (*.csv)")
        if fname:
            self._parameterNode.SetParameter("PresegCSVPath", fname)

    def _preflight_check(self, db_path, preseg_path):
        """Pure-Python (no Slicer/VTK calls) sanity check, run before ever
        calling slicer.util.loadTable()/self.logic.initializeStudy(). Catches
        the most common real-world mistakes - a typo'd key column, an empty
        or malformed CSV - with a plain-language message, instead of letting
        them surface as a native VTK/Slicer error dialog that's confusing for
        non-technical users. Returns None if everything looks fine, otherwise
        a ready-to-show message string."""

        key_columns = None
        if self.logic.cfg is not None:
            key_columns = self.logic.cfg.key_columns
        else:
            config_path = str(self.ui.tbConfigPath.text).strip() or self.CONFIG_PATH
            try:
                import json
                with open(config_path, "r", encoding="utf-8") as f:
                    raw_cfg = json.load(f)
                key_columns = raw_cfg.get("key_columns") or ["ID"]
            except Exception as e:
                return f"The config file couldn't be read as JSON:\n{e}\n\nOpen it in the Config Editor to fix it."

        def _read_header(path, label):
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as f:
                    header = next(csv.reader(f), None)
            except Exception as e:
                return None, f"{label} couldn't be read as a CSV file:\n{path}\n\n{e}"
            if not header or not any(h.strip() for h in header):
                return None, f"{label} appears to be empty (no header row):\n{path}"
            return header, None

        db_header, err = _read_header(db_path, "The database CSV")
        if err:
            return err
        preseg_header, err = _read_header(preseg_path, "The preseg CSV")
        if err:
            return err

        missing_db = [c for c in key_columns if c not in db_header]
        missing_preseg = [c for c in key_columns if c not in preseg_header]
        if missing_db or missing_preseg:
            lines = ["The key column(s) from the config don't match the actual CSV columns:"]
            if missing_db:
                lines.append(f"  - missing from database CSV: {missing_db}")
            if missing_preseg:
                lines.append(f"  - missing from preseg CSV: {missing_preseg}")
            lines.append("")
            lines.append(f"Database CSV columns:  {db_header}")
            lines.append(f"Preseg CSV columns:    {preseg_header}")
            lines.append("")
            lines.append("Fix 'Key columns' in the Config Editor's General tab (or use 'Show CSV columns...' there to check the exact names).")
            return "\n".join(lines)

        return None

    def onBtnInitializeStudy(self):
        if self.logic.hasActiveSpecimen:
            ret = qt.QMessageBox.warning(
                slicer.util.mainWindow(), "Re-initialize study",
                "A specimen is currently open. Re-initializing the study reloads the "
                "database/preseg tables and rebuilds the specimen list - any unsaved "
                "work on the open specimen (and unsaved database table edits) can be "
                "lost or end up misattributed if you continue without saving first.\n\n"
                "Save the active specimen and the database CSV before continuing?",
                qt.QMessageBox.Save | qt.QMessageBox.Discard | qt.QMessageBox.Cancel)
            if ret == qt.QMessageBox.Cancel:
                return
            if ret == qt.QMessageBox.Save:
                try:
                    self.logic.save_active_specimen(inform_user=False)
                    self.logic.save_db()
                except Exception as e:
                    slicer.util.errorDisplay("Failed to save before re-initializing: " + str(e))
                    return
            self.logic.close_active_specimen(no_question=True)
            self.ui.btnLoadSelected.enabled = True
            self.ui.lblActiveSpecimen.text = ""

        try:
            if self.logic.cfg is None:
                config_path = str(self.ui.tbConfigPath.text).strip() or self.CONFIG_PATH
                if not config_path:
                    slicer.util.warningDisplay("No study config selected yet. Choose a config.json first (or use the Config Editor to build one).")
                    return
                if not os.path.exists(config_path):
                    slicer.util.warningDisplay(f"Config file not found:\n{config_path}")
                    return
                if os.path.isdir(config_path):
                    # This is the Config/ folder pre-filled as a Browse starting
                    # point (see updateGUIFromParameterNode) - it was never
                    # actually picked as a file. Opening a directory as a config
                    # raises IsADirectoryError, which used to surface as a
                    # confusing generic "Failed to load config" message.
                    slicer.util.warningDisplay(
                        "That's a folder, not a config file yet:\n"
                        f"{config_path}\n\n"
                        "Click 'Select .json file' and pick a specific config.json inside it.")
                    return
                self.logic.load_config(config_path)
        except Exception as e:
            slicer.util.errorDisplay("Failed to load config: " + str(e))
            return

        db_path = str(self.ui.tbDBPath.text).strip()
        preseg_path = str(self.ui.tbPresegPath.text).strip()
        if not db_path or not preseg_path:
            slicer.util.warningDisplay(
                "Database CSV and Preseg CSV paths must both be set. They're normally filled in "
                "automatically from the config - if they're empty, the loaded config may be missing "
                "database_csv_path/preseg_csv_path, or you cleared the fields by hand.")
            return
        if not os.path.exists(db_path):
            slicer.util.warningDisplay(f"Database CSV not found:\n{db_path}")
            return
        if not os.path.exists(preseg_path):
            slicer.util.warningDisplay(f"Preseg CSV not found:\n{preseg_path}")
            return

        problem = self._preflight_check(db_path, preseg_path)
        if problem:
            slicer.util.warningDisplay(problem)
            return

        try:
            self.logic.initializeStudy()
            self._batch_filter = None
            self._setup_batch_combo()
            self.show_specimen_table()
        except Exception as e:
            slicer.util.errorDisplay("Failed to initialize study: " + str(e))
            import traceback
            traceback.print_exc()

    def _setup_batch_combo(self):
        bm_cfg = self.logic.cfg.batch_mode
        self.ui.wBatch.visible = bool(bm_cfg.enabled)
        if not bm_cfg.enabled:
            return
        values = self.logic.batch_values()
        self.ui.cmbBatch.blockSignals(True)
        self.ui.cmbBatch.clear()
        self.ui.cmbBatch.addItem("(all)")
        for v in values:
            self.ui.cmbBatch.addItem(v)
        self.ui.cmbBatch.blockSignals(False)

    def onBatchChanged(self, text):
        if self.logic.hasActiveSpecimen:
            slicer.util.errorDisplay("Close the active specimen before switching batch.")
            self.ui.cmbBatch.blockSignals(True)
            self.ui.cmbBatch.currentText = self._batch_filter or "(all)"
            self.ui.cmbBatch.blockSignals(False)
            return
        self._batch_filter = None if text == "(all)" else text
        self.show_specimen_table()

    def show_specimen_table(self):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return
        wasModified = self._parameterNode.StartModify()

        cfg = self.logic.cfg
        columns = cfg.table_columns
        keys = sorted(self.logic.specimens.keys())
        if self._batch_filter is not None and cfg.batch_mode.enabled:
            col = cfg.batch_mode.column
            keys = [k for k in keys if self.logic.specimens[k].db_info.get(col, "") == self._batch_filter]
        self._displayed_keys = keys

        tbl = self.ui.tblSpecimens
        tbl.clear()
        tbl.clearContents()
        tbl.setColumnCount(len(columns))
        tbl.setRowCount(len(keys))

        done_col = cfg.done_column
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
        key_columns = self.logic.cfg.key_columns
        columns = self.logic.cfg.table_columns
        key = tuple(self.ui.tblSpecimens.item(row, columns.index(c)).text() for c in key_columns)
        self.tbl_selected_key = key
        self.ui.lblSelectedSpecimen.text = "-".join(key)

    def specimen_tbl_changed(self):
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
            columns = cfg.table_columns
            done_col_display_idx = columns.index(cfg.done_column) if cfg.done_column in columns else tbl.columnCount - 1

            current_done = tbl.item(row, done_col_display_idx).text()
            for j in range(tbl.columnCount):
                tbl.item(row, j).setBackground(qt.QColor(0, 127, 0) if str(current_done) == "1" else qt.QColor("transparent"))

            key = self._displayed_keys[row]
            specimen = self.logic.specimens.get(key)
            if specimen is None or specimen.row_index is None:
                return
            col_name = columns[col]
            if col_name not in self.logic.dbColumnNames:
                print(f"[GenericSpecimenManager] column '{col_name}' not present in database.csv, not writing back")
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
# Generic batch export
# ---------------------------------------------------------------------------

def batch_exporter(logic: GenericSpecimenManagerLogic):
    if logic.hasActiveSpecimen:
        print("Please close the active specimen before running a batch export.")
        return
    cfg = logic.cfg
    be_cfg = cfg.batch_export
    if not be_cfg.enabled:
        print("[batch_exporter] batch_export is not enabled in the config.")
        return

    logic.initializeStudy()
    done_col = cfg.done_column
    segments_filter = be_cfg.segments_filter
    use_batch_subfolder = cfg.batch_mode.enabled and be_cfg.per_batch_subfolder

    for key, specimen in logic.specimens.items():
        if specimen.db_info.get(done_col) != "1":
            continue

        logic.load_specimen(key)

        base_dir = be_cfg.output_dir if be_cfg.output_dir else None
        if base_dir and not os.path.isabs(base_dir):
            base_dir = os.path.join(logic.study_dir, base_dir)
        out_dir = base_dir if base_dir else specimen.out_dir
        if use_batch_subfolder:
            out_dir = os.path.join(out_dir, str(specimen.batch_value() or "unknown"))
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        if be_cfg.export_segments and specimen.segmentation_node is not None:
            ref_name = be_cfg.reference_image or cfg.segmentation.reference_image
            ref_node = specimen.node_dict.get(ref_name)
            seg = specimen.segmentation_node.GetSegmentation()
            for seg_id in list(seg.GetSegmentIDs()):
                seg_name = seg.GetSegment(seg_id).GetName()
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

        if be_cfg.export_markups and specimen.markups_node is not None:
            out_file = os.path.join(out_dir, f"{specimen.label}-markups.mrk.json")
            storage = specimen.markups_node.CreateDefaultStorageNode()
            storage.SetFileName(out_file)
            storage.WriteData(specimen.markups_node)
            print(f"[batch_exporter] saved {out_file}")
            slicer.mrmlScene.RemoveNode(storage)

        logic.close_active_specimen(no_question=True)
