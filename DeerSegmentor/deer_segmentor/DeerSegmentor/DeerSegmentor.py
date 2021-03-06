import os
import unittest
import logging
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from qt import QFileDialog
import qSlicerBaseQTCorePythonQt as QtCore
import pathlib

#import DefaultFilePaths as _paths


#
# DeerSegmentor
#

class DeerSegmentor(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Deer Segmentor" 
    self.parent.categories = ["Segmentation"]  
    self.parent.dependencies = []  
    self.parent.contributors = ["Daniel Fajtai (Medicopus Nonprofit Ltd.)"] 
    self.parent.helpText = """
    This is a simple, in-house module for the local deer liver segementation project.
    See more information in <a href="https://github.com/dfajtai/3dslicer-ext">module documentation</a>.
    """
    self.parent.acknowledgementText = """Medicoups Nonprofit Ltd."""
      

    # Additional initialization step after application startup is complete
    slicer.app.connect("startupCompleted()", registerSampleData)


#
# Register sample data sets in Sample Data module
#

def registerSampleData():
  """
  Add data sets to Sample Data module.
  """

  import SampleData
  iconsPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons')
  print("Sample for DeerSegmentor not implemented")
  
#
# DeerSegmentorWidget
#

class DeerSegmentorWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
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

    self.tbl_selected_sid = ""
    self.tblSelectedIndex = None
    self.table_lock = False

  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/DeerSegmentor.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = DeerSegmentorLogic()

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    
    self.ui.tbDBPath.textChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.tbPresegPath.textChanged.connect(self.updateParameterNodeFromGUI)

    self.ui.cbShowControl.connect("toggled(bool)",self.updateParameterNodeFromGUI)
    self.ui.cbShowControl.connect("toggled(bool)",self.show_deer_db_table)

    self.ui.cbShowNonControl.connect("toggled(bool)",self.updateParameterNodeFromGUI)
    self.ui.cbShowNonControl.connect("toggled(bool)",self.show_deer_db_table)


    self.ui.tblDeers.selectionModel().selectionChanged.connect(self.selected_deer_changed)
    self.ui.tblDeers.itemChanged.connect(self.deer_tbl_changed)
    
    # Buttons
    #self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.ui.btnInitializeStudy.connect('clicked(bool)',self.onBtnInitializeStudy)
    self.ui.btnSelectDB.connect('clicked(bool)',self.onBtnSelectDB)
    self.ui.btnSelectPreseg.connect('clicked(bool)',self.onBtnSelectPreseg)

    self.ui.btnBatchExport.connect('clicked(bool)',self.onBtnBatchExport)
    self.ui.btnLoadSelected.connect('clicked(bool)',self.onBtnLoadSelected)
    self.ui.btnSaveActiveDeer.connect('clicked(bool)',self.onBtnSaveActiveDeer)
    self.ui.btnCloseActiveDeer.connect('clicked(bool)',self.onBtnCloseActiveDeer)
    self.ui.btnSaveDB.connect('clicked(bool)',self.onBtnSaveDB)

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
    if self._parameterNode is not None:
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

    self.ui.tbDBPath.text = str(self._parameterNode.GetParameter("DatabaseCSVPath"))
    self.ui.tbPresegPath.text = str(self._parameterNode.GetParameter("PresegCSVPath"))

    self.ui.cbShowControl.checked = (self._parameterNode.GetParameter("ShowControl") == "true")
    self.ui.cbShowNonControl.checked = (self._parameterNode.GetParameter("ShowNonControl") == "true")

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

    self._parameterNode.SetParameter("DatabaseCSVPath",str(self.ui.tbDBPath.text))
    self._parameterNode.SetParameter("PresegCSVPath",str(self.ui.tbPresegPath.text))
  
    self._parameterNode.SetParameter("ShowControl", "true" if self.ui.cbShowControl.checked else "false")
    self._parameterNode.SetParameter("ShowNonControl", "true" if self.ui.cbShowNonControl.checked else "false")

    self._parameterNode.EndModify(wasModified)
 
  def onBtnSelectDB(self):
    _orig_file = str(self._parameterNode.GetParameter("DatabaseCSVPath"))
    _orig_dir = os.path.dirname(_orig_file)
    _orig_file_name = os.path.basename(_orig_file)
  
    fname = QFileDialog.getOpenFileName(None, 'Open file',  _orig_file_name , "CSV files (*.csv)")
    if fname:
      self._parameterNode.SetParameter("DatabaseCSVPath",fname)
  
  def onBtnSelectPreseg(self):
    _orig_file = str(self._parameterNode.GetParameter("PresegCSVPath"))
    _orig_dir = os.path.dirname(_orig_file)
    _orig_file_name = os.path.basename(_orig_file)
  
    fname = QFileDialog.getOpenFileName(None, 'Open file',  _orig_file_name , "CSV files (*.csv)")
    if fname:
      self._parameterNode.SetParameter("PresegCSVPath",fname)


  def onBtnInitializeStudy(self):
    try:
      print("btnInitializeStudy clicked")
      self.logic.initializeStudy()
      self.show_deer_db_table()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

  def show_deer_db_table(self):
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()

    sids = []   

    if self.ui.cbShowControl.checked:
      sids.extend([sid for sid in self.logic.deers.keys() if self.logic.deers[sid].group == "c"])
    if self.ui.cbShowNonControl.checked:
      sids.extend([sid for sid in self.logic.deers.keys() if self.logic.deers[sid].group == "p"])
    sids = sorted(sids)

    tbl = self.ui.tblDeers
    tbl.clear()
    tbl.clearContents()

    db_info_filter = ["sid","spieces","group","count","abnorm","done"]
    
    tbl.setColumnCount(len(db_info_filter))
    tbl.setRowCount(len(sids))
    
    for i in range(len(sids)):
      deer = self.logic.deers[sids[i]]
      deer.update_done(self.logic.dbTable)
      for j in range(len(db_info_filter)):
        tbl.setItem(i,j,qt.QTableWidgetItem(deer.db_info.get(db_info_filter[j])))
        if j!=(len(db_info_filter)-1):
          #tbl.item(i,j).setFlags(qt.Qt.ItemIsEnabled)
          pass

      if deer.db_info.get("done") == str(1):
        for j in range(self.ui.tblDeers.columnCount):
          tbl.item(i,j).setBackground(qt.QColor(0,127,0))


    tbl.setHorizontalHeaderLabels(db_info_filter)
    tbl.resizeColumnsToContents()
    self._parameterNode.EndModify(wasModified) 

  def selected_deer_changed(self):
    current_selection = self.ui.tblDeers.selectedIndexes()
    if len(current_selection)>0:
      current_selection = current_selection[0]
      tbl_selected_sid = self.ui.tblDeers.item(current_selection.row(),0).text()
      self.tblSelectedIndex = current_selection
      self.tbl_selected_sid = tbl_selected_sid
      self.ui.lblSelectedDeer.text = tbl_selected_sid
      #print(f"current sid: {tbl_selected_sid}")

  
  def deer_tbl_changed(self):
    if self.table_lock:
      return
    self.table_lock = True

    try:
      tbl = self.ui.tblDeers
      current_selection = tbl.selectedIndexes()
      if len(current_selection)>0:
        current_selection = current_selection[0]
        self.tblSelectedIndex = current_selection
        current_done = tbl.item(current_selection.row(),tbl.columnCount-1).text()
        
        if str(current_done) == "1":
          for j in range(tbl.columnCount):
            tbl.item(current_selection.row(),j).setBackground(qt.QColor(0,127,0))
        else:
          for j in range(tbl.columnCount):
            tbl.item(current_selection.row(),j).setBackground(qt.QColor("transparent"))
    
        if current_selection.column() == tbl.columnCount-1:
          #modify done in table
          tbl_selected_sid = self.ui.tblDeers.item(current_selection.row(),0).text()
          deer = self.logic.deers[tbl_selected_sid]
          self.logic.dbTable.SetCellText(deer.row_index,deer.done_col_index, current_done)
          

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
    
    finally:      
      self.table_lock = False
  
  def onBtnLoadSelected(self):
    try:
      if not self.tbl_selected_sid:
        return

      load_success = self.logic.load_deer(self.tbl_selected_sid)
      self.ui.btnLoadSelected.enabled = not self.logic.hasActiveDeer
      if self.logic.hasActiveDeer:
        self.ui.lblActiveDeer.text= self.logic.active_deer.sid

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
      
  def onBtnSaveActiveDeer(self):
    try:
      save_success = self.logic.save_active_deer()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

  def onBtnCloseActiveDeer(self):
    try:
      close_success = self.logic.close_active_deer()
      self.ui.btnLoadSelected.enabled = not self.logic.hasActiveDeer
      if not self.logic.hasActiveDeer:
        self.ui.lblActiveDeer.text= ""

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
  
  def onBtnSaveDB(self):
    try:
      print("Saving database csv...")
      self.logic.save_db()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
  

  def onBtnBatchExport(self):
    import importlib.util
    batch_export_py_path =  "/home/fajtai/Git/3dslicer-ext/DeerSegmentor/deer_segmentor/DeerSegmentor/batch_exporter.py"
    spec = importlib.util.spec_from_file_location("module.name",batch_export_py_path)
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    exporter.test()


#
# DeerSegmentorLogic
#

class DeerSegmentorLogic(ScriptedLoadableModuleLogic):

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)

    self._database_csv_path_ = "/data/deer/nas_deer/etc/deer_database.csv"
    self._preseg_csv_path_ =  "/data/deer/nas_deer/etc/preseg_paths.csv"
    self._study_dir_ = "/data/deer/nas_deer/"

    self.dbTable = None
    self.dbDictList = []

    self.presegTable = None
    self.presegDictList = []
    
    self.sid_list = []
    self.deers = {}

    self.active_deer = None

  def setDefaultParameters(self, parameterNode):
    """
    Initialize parameter node with default settings.
    """
    
    if not parameterNode.GetParameter("DatabaseCSVPath"):
      parameterNode.SetParameter("DatabaseCSVPath",self._database_csv_path_)
    
    if not parameterNode.GetParameter("PresegCSVPath"):
      parameterNode.SetParameter("PresegCSVPath",self._preseg_csv_path_)

    if not parameterNode.GetParameter("ShowControl"):
      parameterNode.SetParameter("ShowControl","true")
    
    if not parameterNode.GetParameter("ShowNonControl"):
      parameterNode.SetParameter("ShowNonControl","true")


  def get_node_if_loaded(self, file_path):
    all_node = slicer.mrmlScene.GetNodes()
    node_name = ""
    for n in all_node:
      try:
        if n.GetStorageNode().GetFileName()==file_path:
          node_name = n.GetName()
          break
      except:
        continue    
      
    return node_name


  def initializeStudy(self):
    db_path = self.getParameterNode().GetParameter("DatabaseCSVPath")
    preseg_path = self.getParameterNode().GetParameter("PresegCSVPath")

    print(f"Database path {db_path}")
    print(f"Presegmentation path {preseg_path}")

    try:
      _node = slicer.util.getNode(self.get_node_if_loaded(db_path))
      self.dbTable = _node
    except slicer.util.MRMLNodeNotFoundException:
      self.dbTable = slicer.util.loadTable(db_path)

    try:
      _node = _node = slicer.util.getNode(self.get_node_if_loaded(preseg_path))
      self.presegTable = _node
    except slicer.util.MRMLNodeNotFoundException:
      self.presegTable = slicer.util.loadTable(preseg_path)    

    self.dbDictList = self.init_table(self.dbTable)
    self.presegDictList = self.init_table(self.presegTable)

    db_sid = [self.dbDictList[i].get("sid") for i in range(len(self.dbDictList))]
    preseg_sid = [self.presegDictList[i].get("sid") for i in range(len(self.presegDictList))]
    self.sid_list = sorted(list(set(db_sid).intersection(set(preseg_sid))))

    print(self.sid_list)
    print(f"Initializing {len(self.sid_list)} deers")
    self.deers = dict([(s, Deer(s,self.dbDictList, self.presegDictList, self._study_dir_)) for s in self.sid_list])

  

  def init_table(self,table):
    dict_list = []
    _dbTable = table.GetTable()
    ncol = _dbTable.GetNumberOfColumns()
    nrow = _dbTable.GetNumberOfRows()
    colnames = [_dbTable.GetColumnName(j) for j in range(ncol)]
    for i in range(nrow):
      row = _dbTable.GetRow(i)
      row_dict = dict([(colnames[j],row.GetValue(j).ToString()) for j in range(ncol)])
      dict_list.append(row_dict)
    return dict_list


  def confim_message_box(self,text):
    c = ctk.ctkMessageBox()
    c.setIcon(qt.QMessageBox.Information)
    c.setText(text)
    c.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
    c.setDefaultButton(qt.QMessageBox.Ok)
    answer = c.exec_()
    return answer == qt.QMessageBox.Yes

  def info_message_box(self,text):
    c = ctk.ctkMessageBox()
    c.setIcon(qt.QMessageBox.Information)
    c.setText(text)
    c.setStandardButtons(qt.QMessageBox.Ok)
    c.setDefaultButton(qt.QMessageBox.Ok)
    answer = c.exec_()

  def load_deer(self, sid):
    target_deer = self.deers.get(sid)

    if isinstance(self.active_deer,Deer):
      self.info_message_box("A deer has been already loaded.")      
      return

    if isinstance(target_deer,type(None)):
      raise ValueError(f"deer with sid={sid} not initialized")

    target_deer.load()

    self.active_deer = target_deer

    return True
  
  def close_active_deer(self, no_question = False):
    if no_question and not isinstance(self.active_deer,type(None)):
      self.active_deer.close()
      self.active_deer = None
      return

    if not isinstance(self.active_deer,Deer):
      self.info_message_box("There is no active deer to close.")
      return

    if not self.confim_message_box("Do you really want to close the active deer?"):
      return
    self.active_deer.close()
    self.active_deer = None

  def save_active_deer(self):
    if not isinstance(self.active_deer,Deer):
      self.info_message_box("There is no active deer to save.")
      return

    self.active_deer.save()

  def save_db(self):
    _storageNode = self.dbTable.CreateDefaultStorageNode()
    _storageNode.SetFileName(self._database_csv_path_)
    _storageNode.WriteData(self.dbTable)


  @property
  def hasActiveDeer(self):
    return isinstance(self.active_deer,Deer)

#
# DeerSegmentorTest
#

class DeerSegmentorTest(ScriptedLoadableModuleTest):
  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()
    

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_DeerSegmentor1()

  def test_DeerSegmentor1(self):
    assert(False)


class Deer():
  def __init__(self, sid, dbDictList, presegDictList, study_dir):
    self.sid = sid
    self.db_info = {}
    self.preseg_paths = {}
    self.study_dir = study_dir

    self.node_dict = {} # file path - node
    self.writeable_node_paths = []

    #get corresponding rows
    db_row = list(filter(lambda x: x["sid"]==sid, dbDictList))
    if len(db_row)>0:
      self.db_info = db_row[0]

    preseg_row = list(filter(lambda x: x["sid"]==sid, presegDictList))
    if len(preseg_row)>0:
      self.preseg_paths = preseg_row[0]
    self.group = self.db_info["group"]

    self.t1_path = self.preseg_paths["t1"]
    self.t1_mask_path = self.preseg_paths["t1_mask"]

    self.t2_path = self.preseg_paths["t2"]
    self.t2_mask_path = self.preseg_paths["t2_mask"]

    self.rel_path = self.preseg_paths["rel"]

    self.row_index = 0
    for i in range(len(dbDictList)):
      if dbDictList[i]["sid"]==sid:
        break
    self.row_index = i
    
    db_cols = list(db_row[0].keys())
    for j in range(len(db_cols)):
      if db_cols[j]=="done":
        break
    self.done_col_index = j

    self.segment_path = os.path.join(self.slicer_out_dir,"segment.seg.nrrd")

    #print(f"Deer {self.sid} initialized." )

  @property
  def slicer_out_dir(self):
    return os.path.join(self.study_dir,self.sid,"slicer_seg")

  def update_done(self,table):
    try:
      self.db_info["done"] = table.GetCellText(self.row_index,self.done_col_index)
    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
  
  def customize_workplace(self):
    #customize segement editor
    defaultSegmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
    defaultSegmentEditorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
    slicer.mrmlScene.AddDefaultNode(defaultSegmentEditorNode)

    # Set linked slice views  in all existing slice composite nodes and in the default node
    sliceCompositeNodes = slicer.util.getNodesByClass('vtkMRMLSliceCompositeNode')
    defaultSliceCompositeNode = slicer.mrmlScene.GetDefaultNodeByClass('vtkMRMLSliceCompositeNode')
    if not defaultSliceCompositeNode:
      defaultSliceCompositeNode = slicer.mrmlScene.CreateNodeByClass('vtkMRMLSliceCompositeNode')
      defaultSliceCompositeNode.UnRegister(None)  # CreateNodeByClass is factory method, need to unregister the result to prevent memory leaks
      slicer.mrmlScene.AddDefaultNode(defaultSliceCompositeNode)
    sliceCompositeNodes.append(defaultSliceCompositeNode)
    for sliceCompositeNode in sliceCompositeNodes:
      sliceCompositeNode.SetLinkedControl(True)

    
    crosshair=slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode")
    crosshair.SetCrosshairBehavior(crosshair.OffsetJumpSlice)
    crosshair.SetCrosshairToMedium()
    crosshair.SetCrosshairMode(crosshair.ShowSmallBasic)
  

  def load(self):
    print(f"loading deer {self.sid}")

    #load t1
    t1_node = slicer.util.loadVolume(self.t1_path)
    self.node_dict[self.t1_path] = t1_node

    #load t2
    t2_node = slicer.util.loadVolume(self.t2_path)
    self.node_dict[self.t2_path] = t2_node

    #load rel
    rel_node = slicer.util.loadVolume(self.rel_path)
    self.node_dict[self.rel_path] = rel_node

    slicer.util.setSliceViewerLayers(background=t1_node,foreground=rel_node,foregroundOpacity=0.45)
    rel_node_disp = rel_node.GetDisplayNode()
    rel_node_disp.SetAndObserveColorNodeID('vtkMRMLColorTableNodeRed')
    rel_node_disp.SetThreshold(1,300)
    rel_node_disp.ApplyThresholdOn()
    rel_node_disp.SetWindowLevel(1,2)
    
    #return 

    #segmentation:
    # mask = total mask of non-air voxels
    # non-liver = abnormal tissue inside mask
    # worm = worms inside mask

    if os.path.exists(self.segment_path):
      # if segmentation file exists -> load it
      print("loading previous segmentation...")
      segmentationNode = slicer.util.loadSegmentation(self.segment_path)
      segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.node_dict[self.t1_path])
      segmentationNode.GetDisplayNode().SetOpacity(0.8)
      
      self.node_dict[self.segment_path] = segmentationNode 
      self.writeable_node_paths.append(self.segment_path)
      
    
    else:
      # if segmentation file not exists -> initialize it
      print("initializing new segmentation...")
      t1_mask_node = slicer.util.loadLabelVolume(self.t1_mask_path) #load t1 mask      
      t2_mask_node = slicer.util.loadLabelVolume(self.t2_mask_path) #load t2 mask
      
      #create segemntation
      segmentationNode = slicer.vtkMRMLSegmentationNode()
      slicer.mrmlScene.AddNode(segmentationNode)
      segmentationNode.CreateDefaultDisplayNodes()
      segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.node_dict[self.t1_path])

      t1m_img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(t1_mask_node)
      t2m_img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(t2_mask_node)
      
      segmentationNode.AddSegmentFromBinaryLabelmapRepresentation(t1m_img,"t1_mask", [0,0.2,0.8])
      segmentationNode.AddSegmentFromBinaryLabelmapRepresentation(t2m_img,"t2_mask", [0.8,0.1,0.8])

      #create empty volume
      empty = t1_mask_node.GetImageData().GetPointData().GetScalars().Fill(0)
      segmentationNode.AddSegmentFromBinaryLabelmapRepresentation(empty,"mask", [1,1,1])
      segmentationNode.AddSegmentFromBinaryLabelmapRepresentation(empty,"non-liver", [0,0.8,0.3] )
      segmentationNode.AddSegmentFromBinaryLabelmapRepresentation(empty,"worm", [1,1,0])

      slicer.mrmlScene.RemoveNode(t1_mask_node)
      slicer.mrmlScene.RemoveNode(t2_mask_node)

      self.node_dict[self.segment_path] = segmentationNode
      self.writeable_node_paths.append(self.segment_path)
      segmentationNode.GetDisplayNode().SetOpacity(0.8)
      print("initialization done")

    slicer.util.setSliceViewerLayers(background=t1_node,foreground=rel_node,foregroundOpacity=0.45)

    self.customize_workplace()



  def save(self):
    print(f"saving deer {self.sid}")
    if not os.path.isdir(self.slicer_out_dir):
      os.makedirs(self.slicer_out_dir,exist_ok=True)

    for path in self.writeable_node_paths:
      print(path)
      node = self.node_dict.get(path)
      if isinstance(node,type(None)):
        continue
      _storageNode = node.CreateDefaultStorageNode()
      _storageNode.SetFileName(path)
      _storageNode.WriteData(node)


  def close(self):
    print(f"closing deer {self.sid}")
    remaining_nodes = {}

    for k in self.node_dict.keys():
      try:
        node = self.node_dict[k]
        slicer.mrmlScene.RemoveNode(node)
      except:
        remaining_nodes[k] = node

    self.node_dict = dict(remaining_nodes)
