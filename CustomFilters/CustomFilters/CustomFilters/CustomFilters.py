import logging
import os
from functools import reduce

import vtk
import qt
import ctk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from glob import glob
import json
from collections import OrderedDict
import re
import threading
import time

try:
  import queue
except ImportError:
  import Queue as queue

from time import sleep

import my_filters

sitk = None
sitkUtils = None

#
# CustomFilters
#

class CustomFilters(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "CustomFilters"  # TODO: make this more human readable by adding spaces
    self.parent.categories = ["Filtering"]  # TODO: set categories (folders where the module shows up in the module selector)
    self.parent.dependencies = []  # TODO: add here list of module names that this module requires
    self.parent.contributors = ["Daniel Fajtai"]  # TODO: replace with "Firstname Lastname (Organization)"
    # TODO: update with short description of the module and a link to online module documentation
    self.parent.helpText = """No help needed to use this simple extension."""
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """All acknowledgements ot the creators."""

    # Additional initialization step after application startup is complete
    slicer.app.connect("startupCompleted()", registerSampleData)


#
# Register sample data sets in Sample Data module
#

def registerSampleData():
  """
  Add data sets to Sample Data module.
  """
  # It is always recommended to provide sample data for users to make it easy to try the module,
  # but if no sample data is available then this method (and associated startupCompeted signal connection) can be removed.

  import SampleData
  iconsPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons')

  # To ensure that the source code repository remains small (can be downloaded and installed quickly)
  # it is recommended to store data sets that are larger than a few MB in a Github release.

  # CustomFilters1
  # MRHead https://github.com/Slicer/Slicer/blob/main/Modules/Scripted/SampleData/SampleData.py
  SampleData.SampleDataLogic.registerCustomSampleDataSource(
    # Category and sample name displayed in Sample Data module
    category='CustomFilters',
    sampleName='CustomFilters1',
    # Thumbnail should have size of approximately 260x280 pixels and stored in Resources/Icons folder.
    # It can be created by Screen Capture module, "Capture all views" option enabled, "Number of images" set to "Single".
    thumbnailFileName=os.path.join(iconsPath, 'CustomFilters1.png'),
    # Download URL and target file name
    uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/cc211f0dfd9a05ca3841ce1141b292898b2dd2d3f08286affadf823a7e58df93",
    fileNames='CustomFilters1.nrrd',
    # Checksum to ensure file integrity. Can be computed by this command:
    #  import hashlib; print(hashlib.sha256(open(filename, "rb").read()).hexdigest())
    checksums='SHA256:cc211f0dfd9a05ca3841ce1141b292898b2dd2d3f08286affadf823a7e58df93',
    # This node name will be used when the data set is loaded
    nodeNames='CustomFilters1'
  )

  # CustomFilters2
  # CTChest https://github.com/Slicer/Slicer/blob/main/Modules/Scripted/SampleData/SampleData.py
  SampleData.SampleDataLogic.registerCustomSampleDataSource(
    # Category and sample name displayed in Sample Data module
    category='CustomFilters',
    sampleName='CustomFilters2',
    thumbnailFileName=os.path.join(iconsPath, 'CustomFilters2.png'),
    # Download URL and target file name
    uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/4507b664690840abb6cb9af2d919377ffc4ef75b167cb6fd0f747befdb12e38e",
    fileNames='CustomFilters2.nrrd',
    checksums='SHA256:4507b664690840abb6cb9af2d919377ffc4ef75b167cb6fd0f747befdb12e38e',
    # This node name will be used when the data set is loaded
    nodeNames='CustomFilters2'
  )


#
# CustomFiltersWidget
#

class CustomFiltersWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
  """



  def __init__(self, parent=None):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.__init__(self, parent)
    VTKObservationMixin.__init__(self)  # needed for parameter node observation
    self.logic = None
    self._parameterNode = None
    self._updatingGUIFromParameterNode = False

    global sitk
    import SimpleITK as sitk
    global sitkUtils
    import sitkUtils

    if not parent:
      self.parent = slicer.qMRMLWidget()
      self.parent.setLayout(qt.QVBoxLayout())
      self.parent.setMRMLScene(slicer.mrmlScene)
    else:
      self.parent = parent
    self.layout = self.parent.layout()
    if not parent:
      self.setup()
      self.parent.show()

    self.implemented_filters = my_filters.implemented_filters

    self.filter = None
    self.filter_ui = None

    self.logic = None
    self.filter_ui_parent = None


  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    #
    # Filters Area
    #
    filtersCollapsibleButton = ctk.ctkCollapsibleButton()
    filtersCollapsibleButton.text = "Filters"
    self.layout.addWidget(filtersCollapsibleButton)
    filtersFormLayout = qt.QFormLayout(filtersCollapsibleButton)

    # filter search
    self.searchBox = ctk.ctkSearchBox()
    filtersFormLayout.addRow("Search:", self.searchBox)
    self.searchBox.connect("textChanged(QString)", self.onSearch)

    # filter selector
    self.filterSelector = qt.QComboBox()
    filtersFormLayout.addRow("Filter:", self.filterSelector)

      # add all the filters listed in the json files
    for idx,j in enumerate(self.implemented_filters):
        # if not isinstance(j,my_filters.CustomFilter):
        #   continue
        name = j.filter_name
        self.filterSelector.addItem(name, idx)

    # connections
    self.filterSelector.connect('currentIndexChanged(int)', self.onFilterSelect)


    #
    # Parameters Area
    #
    parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    parametersCollapsibleButton.text = "Parameters"
    self.filter_ui_parent = parametersCollapsibleButton
    self.layout.addWidget(parametersCollapsibleButton)

    # Layout within the dummy collapsible button
    parametersFormLayout = qt.QFormLayout(self.filter_ui_parent)

    self.filter = my_filters.CustomFilter()
    self.filter_ui = my_filters.CustomFilterUI(self.filter_ui_parent)

    # Add vertical spacer
    self.layout.addStretch(1)

    #
    # Status and Progress
    #
    statusLabel = qt.QLabel("Status: ")
    self.currentStatusLabel = qt.QLabel("Idle")
    hlayout = qt.QHBoxLayout()
    hlayout.addStretch(1)
    hlayout.addWidget(statusLabel)
    hlayout.addWidget(self.currentStatusLabel)
    self.layout.addLayout(hlayout)

    self.filterStartTime = None

    # self.progress = qt.QProgressBar()
    # self.progress.setRange(0,1000)
    # self.progress.setValue(0)
    # self.layout.addWidget(self.progress)
    # self.progress.hide()

    #
    # Cancel/Apply Row
    #
    self.restoreDefaultsButton = qt.QPushButton("Restore Defaults")
    self.restoreDefaultsButton.toolTip = "Restore the default parameters."
    self.restoreDefaultsButton.enabled = True

    self.cancelButton = qt.QPushButton("Cancel")
    self.cancelButton.toolTip = "Abort the algorithm."
    self.cancelButton.enabled = False

    self.applyButton = qt.QPushButton("Apply")
    self.applyButton.toolTip = "Run the algorithm."
    self.applyButton.enabled = True

    hlayout = qt.QHBoxLayout()

    hlayout.addWidget(self.restoreDefaultsButton)
    hlayout.addStretch(1)
    hlayout.addWidget(self.cancelButton)
    hlayout.addWidget(self.applyButton)
    self.layout.addLayout(hlayout)

    # connections
    self.restoreDefaultsButton.connect('clicked(bool)', self.onRestoreDefaultsButton)
    self.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.cancelButton.connect('clicked(bool)', self.onCancelButton)

    # Initlial Selection
    self.filterSelector.currentIndexChanged(self.filterSelector.currentIndex)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = CustomFiltersLogic()

    # These connections ensure that we update parameter node when scene is closed
    # self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    # self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    self.removeObservers()

  def enter(self):
    """
    Called each time the user opens this module.
    """
    # Make sure parameter node exists and observed
    self.initializeParameterNode()

  def exit(self):
    """
    Called each time the user opens a different module.
    """
    # Do not react to parameter node changes (GUI wlil be updated when the user enters into the module)
    self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

  def onSceneStartClose(self, caller, event):
    """
    Called just before the scene is closed.
    """
    # Parameter node will be reset, do not use it anymore
    self.setParameterNode(None)

  def onSceneEndClose(self, caller, event):
    """
    Called just after the scene is closed.
    """
    # If this module is shown while the scene is closed then recreate a new parameter node immediately
    if self.parent.isEntered:
      self.initializeParameterNode()

  def initializeParameterNode(self):
    """
    Ensure parameter node exists and observed.
    """
    # Parameter node stores all user choices in parameter values, node selections, etc.
    # so that when the scene is saved and reloaded, these settings are restored.

    self.setParameterNode(self.logic.getParameterNode())

    # Select default input nodes if nothing is selected yet to save a few clicks for the user
    # if not self._parameterNode.GetNodeReference("InputVolume"):
    #   firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
    #   if firstVolumeNode:
    #     self._parameterNode.SetNodeReferenceID("InputVolume", firstVolumeNode.GetID())

  def setParameterNode(self, inputParameterNode):
    """
    Set and observe parameter node.
    Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
    """

    if inputParameterNode:
      self.logic.setDefaultParameters(inputParameterNode)

    # Unobserve previously selected parameter node and add an observer to the newly selected.
    # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
    # those are reflected immediately in the GUI.
    if self._parameterNode is not None and self.hasObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode):
      self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
    self._parameterNode = inputParameterNode
    if self._parameterNode is not None:
      self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    # Initial GUI update
    self.updateGUIFromParameterNode()

  def updateGUIFromParameterNode(self, caller=None, event=None):
    """
    This method is called whenever parameter node is changed.
    The module GUI is updated to show the current state of the parameter node.
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
    self._updatingGUIFromParameterNode = True

    # Update node selectors and sliders
    # self.ui.inputSelector.setCurrentNode(self._parameterNode.GetNodeReference("InputVolume"))
    # self.ui.outputSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputVolume"))
    # self.ui.invertedOutputSelector.setCurrentNode(self._parameterNode.GetNodeReference("OutputVolumeInverse"))
    # self.ui.imageThresholdSliderWidget.value = float(self._parameterNode.GetParameter("Threshold"))
    # self.ui.invertOutputCheckBox.checked = (self._parameterNode.GetParameter("Invert") == "true")

    # Update buttons states and tooltips
    # if self._parameterNode.GetNodeReference("InputVolume") and self._parameterNode.GetNodeReference("OutputVolume"):
    #   self.ui.applyButton.toolTip = "Compute output volume"
    #   self.ui.applyButton.enabled = True
    # else:
    #   self.ui.applyButton.toolTip = "Select input and output volume nodes"
    #   self.ui.applyButton.enabled = False

    # All the GUI updates are done
    self._updatingGUIFromParameterNode = False

  def updateParameterNodeFromGUI(self, caller=None, event=None):
    """
    This method is called when the user makes any change in the GUI.
    The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
    """

    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

    # self._parameterNode.SetNodeReferenceID("InputVolume", self.ui.inputSelector.currentNodeID)
    # self._parameterNode.SetNodeReferenceID("OutputVolume", self.ui.outputSelector.currentNodeID)
    # self._parameterNode.SetParameter("Threshold", str(self.ui.imageThresholdSliderWidget.value))
    # self._parameterNode.SetParameter("Invert", "true" if self.ui.invertOutputCheckBox.checked else "false")
    # self._parameterNode.SetNodeReferenceID("OutputVolumeInverse", self.ui.invertedOutputSelector.currentNodeID)

    self._parameterNode.EndModify(wasModified)

  # def onLogicRunStop(self):
  #   self.applyButton.setEnabled(True)
  #   self.restoreDefaultsButton.setEnabled(True)
  #   self.cancelButton.setEnabled(False)
  #   self.logic = None
  #   self.progress.hide()


  # def onLogicRunStart(self):
  #   self.applyButton.setEnabled(False)
  #   self.restoreDefaultsButton.setEnabled(False)

  def onSearch(self, searchText):
  # add all the filters listed in the json files
    self.filterSelector.clear()
    # split text on whitespace of and string search

    searchTextList = searchText.split()
    for idx,j in enumerate(self.implemented_filters):
      lname = j.filter_name.lower()
      # require all elements in list, to add to select. case insensitive
      if  reduce(lambda x, y: x and (lname.find(y.lower())!=-1), [True]+searchTextList):
        self.filterSelector.addItem(j.filter_name,idx)

  def onFilterSelect(self, selectorIndex):
    self.filter_ui.destroy()
    if selectorIndex < 0:
      return
    filter_index = self.filterSelector.itemData(selectorIndex)
    selected_filter = self.implemented_filters[filter_index]()
    if not isinstance(selected_filter,my_filters.CustomFilter):
      return
    new_ui = selected_filter.createUI(self.filter_ui_parent)
    self.filter = selected_filter
    self.filter_ui = new_ui

    if selected_filter.tooltip:
      tip=self.implemented_filters[filter_index].tooltip
      tip=tip.rstrip()
      self.filterSelector.setToolTip(tip)
    else:
      self.filterSelector.setToolTip("")

  def onRestoreDefaultsButton(self):
    self.onFilterSelect(self.filterSelector.currentIndex)

  def onApplyButton(self):
    try:

      self.currentStatusLabel.text = "Starting"
      self.logic = CustomFiltersLogic()

      #print "running..."
      self.logic.run(self.filter,self.filter_ui)

    except Exception as e:
      self.currentStatusLabel.text = "Exception"

      qt.QMessageBox.critical(slicer.util.mainWindow(),
                  f"Exception before execution of {self.filter.filter_name}",
                  e)


  def onCancelButton(self):
    self.currentStatusLabel.text = "Aborting"
    if self.logic:
      self.logic.abort = True


  # def onLogicEventStart(self):
  #   self.filterStartTime = time.time()
  #   self.currentStatusLabel.text = "Running"
  #   self.cancelButton.setDisabled(False)
  #   self.progress.setValue(0)
  #   self.progress.show()


  # def onLogicEventEnd(self):
  #   elapsedTimeSec = time.time() - self.filterStartTime
  #   self.currentStatusLabel.text = f"Completed ({elapsedTimeSec:3.1f}s)"
  #   self.progress.setValue(1000)


  # def onLogicEventAbort(self):
  #   #print "Aborting..."
  #   self.currentStatusLabel.text = "Aborted"


  # def onLogicEventProgress(self, progress):
  #   self.currentStatusLabel.text = "Running ({:3.1f}%)".format(progress*100.0)
  #   self.progress.setValue(progress*1000)


  # def onLogicEventIteration(self, nIter):
  #   print("Iteration " , nIter)

#   
# CustomFiltersLogic
#

class CustomFiltersLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py


  This class is hardly based on:
  https://github.com/SimpleITK/SlicerSimpleFilters/blob/master/SimpleFilters/SimpleFilters.py#L356
  """

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)


  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    pass


  def run(self,filter, ui):
    assert isinstance(filter,my_filters.CustomFilter)
    assert isinstance(ui,my_filters.CustomFilterUI)

    try:
      self.output = None
      self.outputNodeName = ui.output.GetName()
      self.outputLabelMap = ui.outputLabelMap
      filter.UI = ui
      output_img = filter.execute()

      self.updateOutput(output_img)

    except Exception as e:
      print(f"Error during executing filter '{filter.filter_name}'.")
      print(e)
      raise e


  def updateOutput(self,img):
    nodeWriteAddress=sitkUtils.GetSlicerITKReadWriteAddress(self.outputNodeName)
    sitk.WriteImage(img,nodeWriteAddress)
    node = slicer.util.getNode(self.outputNodeName)
    applicationLogic = slicer.app.applicationLogic()
    selectionNode = applicationLogic.GetSelectionNode()

    if self.outputLabelMap:
      selectionNode.SetReferenceActiveLabelVolumeID(node.GetID())
    else:
      selectionNode.SetReferenceActiveVolumeID(node.GetID())

    applicationLogic.PropagateVolumeSelection(0)
    applicationLogic.FitSliceToAll()



#
# CustomFiltersTest
#

class CustomFiltersTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_CustomFilters1()

  def test_CustomFilters1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")

    # Get/create input data

    import SampleData
    registerSampleData()
    inputVolume = SampleData.downloadSample('CustomFilters1')
    self.delayDisplay('Loaded test data set')

    
    outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
    
    # Test the module logic

    logic = CustomFiltersLogic()
    filter = my_filters.RankDownsampleFilter()
    ui = my_filters.CustomFilterUI()
    ui.inputs.append(inputVolume)
    ui.output = outputVolume

    ui.parameters["block_size"]=2
    ui.parameters["downsampling_function"] = "max"
    logic.run(filter=filter,ui=ui)

    self.delayDisplay('Test passed')