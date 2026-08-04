"""
GenericSpecimenManager
======================

Thin wrapper around SpecimenViewerCommon/GenericSpecimenEngine.py.

Unlike the per-species wrappers (DeerSegmentor, PigChunker, RabbitVertCount),
this one does NOT lock a CONFIG_PATH - the "Select .json file" row stays
visible so you can point it at any study config.json at runtime. Good for
trying out a new config before "graduating" it into its own thin wrapper
module with its own name/icon.
"""

import os
import sys

# --- bootstrap import of the shared engine (sibling folder, not on sys.path by default) ---
_THIS_DIR = os.path.dirname(__file__)
_COMMON_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "SpecimenViewerCommon"))
if _COMMON_DIR not in sys.path:
    sys.path.append(_COMMON_DIR)

from GenericSpecimenEngine import GenericSpecimenManagerWidgetBase  # noqa: E402

import slicer
from slicer.ScriptedLoadableModule import *


class GenericSpecimenManager(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Generic Specimen Viewer"
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["Daniel Fajtai"]
        self.parent.helpText = """
A generic, JSON-configurable specimen loader / segmenter / landmarker.
Point it at a study config.json (see README.md for the schema) instead of
writing a new scripted module for every species / study.
"""
        self.parent.acknowledgementText = ""


class GenericSpecimenManagerWidget(GenericSpecimenManagerWidgetBase):
    CONFIG_PATH = None   # no fixed config -> config picker stays visible
    UI_RESOURCE = "UI/GenericSpecimenManager.ui"


class GenericSpecimenManagerTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        # Config-driven module: no fixed self-test data set.
        pass
