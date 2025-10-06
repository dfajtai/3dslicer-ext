import logging
import os
from re import S

import qt
import vtk
import ctk

from qt import QFileDialog

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin



rel_paths = True

multiple_batch = False # batch data is stored in the '__study_dir__'/batch_[01..NN]/.. 
# while the db csv has a 'batch' column. db csv and preseg csv contains all batches

#stored_data_path = "Z:/Projects/ANIMALS/PIGWEB_TNA/piglet/batch03"
stored_data_path = "/nas/medicopus_share/Projects/ANIMALS/PIGWEB_TNA/piglet/batch04"
current_data_path = "/nas/medicopus_share/Projects/ANIMALS/PIGWEB_TNA/piglet/batch04"
current_data_path = "/fast_storage/piglet/batch_3_4"
current_data_path = "/nas/medicopus_share/Projects/ANIMALS/PIGWEB_TNA/piglet/batch02"
# current_data_path = stored_data_path

__database_csv_path__ = os.path.join(current_data_path,"etc","database.csv")
__preseg_csv_path__ = os.path.join(current_data_path,"etc","img_paths.csv")
__study_dir__ =  os.path.join(current_data_path,"segmentation")

enable_volume_rendering = False


segment_names = ["body","skeleton","earring_L", "earring_R", "bone_1","bone_2"]


def fix_path(path):
  if rel_paths:
    return add_current_path(path)
  else:
    return str(path).replace(stored_data_path,current_data_path)

def add_current_path(rel_path):
    return os.path.join(str(__study_dir__), rel_path)


#
# PigletSegmentor
#

class PigletSegmentor(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "PigletSegmentor"  # TODO: make this more human readable by adding spaces
    self.parent.categories = ["Segmentation"]  # TODO: set categories (folders where the module shows up in the module selector)
    self.parent.dependencies = []  # TODO: add here list of module names that this module requires
    self.parent.contributors = ["Daniel Fajtai"]  # TODO: replace with "Firstname Lastname (Organization)"
    # TODO: update with short description of the module and a link to online module documentation
    self.parent.helpText = """
    This is a simple module for piglet bone segmentation.
    See more information in <a href="https://github.com/organization/projectname#PigletSegmentor">module documentation</a>.
    """
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """I made this for myself on my own."""

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
  print("Sample for PigletSegmentor not implemented")


#
# PigletSegmentorWidget
#

class PigletSegmentorWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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

    self.tbl_selected_ID = ""
    self.tblSelectedIndex = None
    self.table_lock = False
    self.volume_rendering = enable_volume_rendering


  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/PigletSegmentor.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = PigletSegmentorLogic()

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    
    self.ui.tbDBPath.textChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.tbPresegPath.textChanged.connect(self.updateParameterNodeFromGUI)

    self.ui.tblSpecimens.selectionModel().selectionChanged.connect(self.selected_specimen_changed)
    self.ui.tblSpecimens.itemChanged.connect(self.specimen_tbl_changed)
    
    # Buttons
    #self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.ui.btnInitializeStudy.connect('clicked(bool)',self.onBtnInitializeStudy)
    self.ui.btnSelectDB.connect('clicked(bool)',self.onBtnSelectDB)
    self.ui.btnSelectPreseg.connect('clicked(bool)',self.onBtnSelectPreseg)

    self.ui.btnBatchExport.connect('clicked(bool)',self.onBtnBatchExport)
    self.ui.btnLoadSelected.connect('clicked(bool)',self.onBtnLoadSelected)
    self.ui.btnSaveActiveSpecimen.connect('clicked(bool)',self.onBtnSaveActiveSpecimen)
    self.ui.btnCloseActiveSpecimen.connect('clicked(bool)',self.onBtnCloseActiveSpecimen)
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

    # Select default input nodes if nothing is selected yet to save a few clicks for the user
    if not self._parameterNode.GetNodeReference("InputVolume"):
      firstVolumeNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode")
      if firstVolumeNode:
        self._parameterNode.SetNodeReferenceID("InputVolume", firstVolumeNode.GetID())

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

    self.ui.tbDBPath.text = fix_path(str(self._parameterNode.GetParameter("DatabaseCSVPath")))
    self.ui.tbPresegPath.text = fix_path(str(self._parameterNode.GetParameter("PresegCSVPath")))


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
  
    self._parameterNode.EndModify(wasModified)  

# GUI functionality
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
      self.show_specimen_db_table()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

  def show_specimen_db_table(self):
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()

    IDs = []   
    IDs.extend([ID for ID in self.logic.Specimens.keys()])
    
    IDs = sorted(IDs)

    tbl = self.ui.tblSpecimens
    tbl.clear()
    tbl.clearContents()

    db_info_filter = ["ID","batch", "done"]
    
    tbl.setColumnCount(len(db_info_filter))
    tbl.setRowCount(len(IDs))
    
    for i in range(len(IDs)):
      specimen = self.logic.Specimens[IDs[i]]
      specimen.update_done(self.logic.dbTable)
      for j in range(len(db_info_filter)):
        tbl.setItem(i,j,qt.QTableWidgetItem(specimen.db_info.get(db_info_filter[j])))
        if j!=(len(db_info_filter)-1):
          #tbl.item(i,j).setFlags(qt.Qt.ItemIsEnabled)
          pass

      if specimen.db_info.get("done") == str(1):
        for j in range(self.ui.tblSpecimens.columnCount):
          tbl.item(i,j).setBackground(qt.QColor(0,127,0))


    tbl.setHorizontalHeaderLabels(db_info_filter)
    tbl.resizeColumnsToContents()
    self._parameterNode.EndModify(wasModified) 

  def selected_specimen_changed(self):
    current_selection = self.ui.tblSpecimens.selectedIndexes()
    if len(current_selection)>0:
      current_selection = current_selection[0]
      tbl_selected_ID = self.ui.tblSpecimens.item(current_selection.row(),0).text()
      self.tblSelectedIndex = current_selection
      self.tbl_selected_ID = tbl_selected_ID
      self.ui.lblSelectedSpecimen.text = f"{tbl_selected_ID}"
      #print(f"current ID: {tbl_selected_ID}")

  
  def specimen_tbl_changed(self):
    if self.table_lock:
      return
    self.table_lock = True

    try:
      tbl = self.ui.tblSpecimens
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
          tbl_selected_ID = self.ui.tblSpecimens.item(current_selection.row(),0).text()
          specimen = self.logic.Specimens[tbl_selected_ID]
          self.logic.dbTable.SetCellText(specimen.row_index,specimen.done_col_index, current_done)
        else:
          # ducktaped...
          val = tbl.item(current_selection.row(),current_selection.column()).text()
          self.logic.dbTable.SetCellText(current_selection.row(),current_selection.column(), val)
          

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
    
    finally:      
      self.table_lock = False
  
  def onBtnLoadSelected(self):
    try:
      if not self.tbl_selected_ID:
        return

      load_success = self.logic.load_specimen(self.tbl_selected_ID,load_bg=True, volume_rendering=self.volume_rendering)
      self.ui.btnLoadSelected.enabled = not self.logic.hasActiveSpecimen
      if self.logic.hasActiveSpecimen:
        self.ui.lblActiveSpecimen.text= f"{self.logic.active_specimen.ID}"

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
      
  def onBtnSaveActiveSpecimen(self):
    try:
      save_success = self.logic.save_active_specimen()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

  def onBtnCloseActiveSpecimen(self):
    try:
      close_success = self.logic.close_active_specimen()
      self.ui.btnLoadSelected.enabled = not self.logic.hasActiveSpecimen
      if not self.logic.hasActiveSpecimen:
        self.ui.lblActiveSpecimen.text= ""

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
    batch_exporter()

#
# PigletSegmentorLogic
#

class PigletSegmentorLogic(ScriptedLoadableModuleLogic):

  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)

    self._database_csv_path_ = fix_path(__database_csv_path__)
    self._preseg_csv_path_ =  fix_path(__preseg_csv_path__)
    self._study_dir_ = fix_path(__study_dir__)

    self.dbTable = None
    self.dbDictList = []

    self.presegTable = None
    self.presegDictList = []
    
    self.ID_list = []
    self.Specimens = {}

    self.active_specimen = None

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

    db_ID = [self.dbDictList[i].get("ID") for i in range(len(self.dbDictList))]
    preseg_ID = [self.presegDictList[i].get("ID") for i in range(len(self.presegDictList))]
    self.ID_list = sorted(list(set(db_ID).intersection(set(preseg_ID))))
    batch_dict = dict([(self.dbDictList[i].get("ID"),self.dbDictList[i].get("batch")) for i in range(len(self.dbDictList))])

    print(self.ID_list)
    print(f"Initializing {len(self.ID_list)} specimens")
    self.Specimens = dict([(s, Specimen(ID = s,
                                        batch = batch_dict.get(s),
                                        dbDictList = self.dbDictList, 
                                        presegDictList= self.presegDictList, 
                                        study_dir = self._study_dir_)) for s in self.ID_list])


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

  def load_specimen(self, ID, load_bg = True, volume_rendering = True):
    target_specimen = self.Specimens.get((ID))

    if isinstance(self.active_specimen,Specimen):
      self.info_message_box("A specimen has been already loaded.")      
      return

    if isinstance(target_specimen,type(None)):
      raise ValueError(f"Specimen with ID={ID} not initialized")

    target_specimen.load(load_bg = load_bg, volume_rendering=volume_rendering)

    self.active_specimen = target_specimen

    return True
  
  def close_active_specimen(self, no_question = False):
    if no_question and not isinstance(self.active_specimen,type(None)):
      self.active_specimen.close()
      self.active_specimen = None
      return

    if not isinstance(self.active_specimen,Specimen):
      self.info_message_box("There is no active specimen to close.")
      return

    if not self.confim_message_box("Do you really want to close the active specimen?"):
      return
    self.active_specimen.close()
    self.active_specimen = None

  def save_active_specimen(self):
    if not isinstance(self.active_specimen,Specimen):
      self.info_message_box("There is no active specimen to save.")
      return

    self.active_specimen.save()
    qt.QApplication.processEvents()
    self.info_message_box("Save complete. You can safely close the specimen.")

  def save_db(self):
    _storageNode = self.dbTable.CreateDefaultStorageNode()
    _storageNode.SetFileName(self._database_csv_path_)
    _storageNode.WriteData(self.dbTable)


  @property
  def hasActiveSpecimen(self):
    return isinstance(self.active_specimen,Specimen)

#
# PigletSegmentorTest
#

class PigletSegmentorTest(ScriptedLoadableModuleTest):
  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()
    

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_specimen2Segment()

  def test_specimen2Segment(self):
    assert(False)


class Specimen():
  def __init__(self, ID, batch, dbDictList, presegDictList, study_dir):
    self.ID = ID
    self.batch = batch
    self.db_info = {}
    self.preseg_paths = {}
    self.study_dir = study_dir

    self.node_dict = {} # file path - node
    self.writeable_node_paths = []


    #get corresponding rows
    db_row = list(filter(lambda x: x["ID"]==ID, dbDictList))
    if len(db_row)>0:
      self.db_info = db_row[0]

    preseg_row = list(filter(lambda x: x["ID"]==ID, presegDictList))
    if len(preseg_row)>0:
      self.preseg_paths = preseg_row[0]

    self.bg_path = self.get_img_path("background")
    self.mask_path = self.get_img_path("mask")
    
    
    self.row_index = 0

    for i in range(len(dbDictList)):
      if dbDictList[i]["ID"]==ID:
        break
    self.row_index = i
    

    db_cols = list(db_row[0].keys())
    for j in range(len(db_cols)):
      if db_cols[j]=="done":
        break
    self.done_col_index = j

    self.segment_path = os.path.join(self.slicer_out_dir,"segment.seg.nrrd")

    #print(f"Specimen {self.ID} initialized." )

  @property
  def slicer_out_dir(self):
    if multiple_batch:
      return os.path.join(self.study_dir,f'batch_{str(self.batch).zfill(2)}',self.ID)
    else:
      return os.path.join(self.study_dir,self.ID)

  @property
  def batch_export_dir(self):
    if multiple_batch:
      return os.path.join(self.study_dir,f'batch_{str(self.batch).zfill(2)}_export',self.ID)
    else:
      return os.path.join(self.study_dir,'batch_export',self.ID)
  
  def get_img_path(self, img_name):
        
    if not self.preseg_paths.get(img_name):
      img_path =  os.path.join(self.slicer_out_dir,f"{self.ID}-{img_name}.nii.gz")
    else:
      img_path = self.preseg_paths.get(img_name)
    
    if multiple_batch:
      img_path = os.path.join(f"batch_{str(int(self.batch)).zfill(2)}",img_path)  
    
    return  fix_path(str(img_path).replace(2*os.sep,os.sep))
    
  def update_done(self,table):
    try:
      self.db_info["done"] = table.GetCellText(self.row_index,self.done_col_index)
    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
  
  def customize_workplace(self):
    #customize segment editor
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

    # crosshair
    crosshair=slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode")
    crosshair.SetCrosshairBehavior(crosshair.OffsetJumpSlice)
    crosshair.SetCrosshairToFine()
    crosshair.SetCrosshairMode(crosshair.ShowBasic)
    
    
    # segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
    # segmentEditorWidget.toggleMasterVolumeIntensityMaskEnabled()

    # set opacity
    seg_node = slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode").GetItemAsObject(0)
    segments = list(seg_node.GetSegmentation().GetSegmentIDs())
    for seg_id in segments:
        seg_node.GetDisplayNode().SetSegmentOpacity2DFill(seg_id,0.65)
        seg_node.GetDisplayNode().SetSegmentOpacity2DOutline(seg_id,1)
    
  
  def start_volume_rendering(self, autoremove = True):
    logic = slicer.modules.volumerendering.logic()
    displayNode = logic.CreateVolumeRenderingDisplayNode()
    displayNode.UnRegister(logic)
    slicer.mrmlScene.AddNode(displayNode)
    self.node_dict[self.mask_path].AddAndObserveDisplayNodeID(displayNode.GetID())
    logic.UpdateDisplayNodeFromVolumeNode(displayNode, self.node_dict[self.mask_path])
    self.volume_rendering_node = displayNode  
    self.volume_rendering_roi = slicer.mrmlScene.GetNodesByClass("vtkMRMLMarkupsROINode")

    slicer.app.processEvents() 
  
    layoutManager = slicer.app.layoutManager()
    threeDWidget = layoutManager.threeDWidget(0)
    threeDView = threeDWidget.threeDView()
    threeDView.resetFocalPoint()
    
    if autoremove:
        for r in self.volume_rendering_roi:
            slicer.mrmlScene.RemoveNode(r)
        self.volume_rendering_roi = []
  
  def load_or_init_segement(self, path, name, segmentation_node, default_mask_node):
    print(f"Loading '{name}'")
    try:
      _mask_node = slicer.util.loadLabelVolume(path) #load mask
      _m_img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(_mask_node)
      segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(_m_img,name)
      slicer.mrmlScene.RemoveNode(_mask_node)
    except:
      print(f"unable to open {path}")
      label_dummy = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
      slicer.vtkSlicerVolumesLogic().CreateLabelVolumeFromVolume(slicer.mrmlScene, label_dummy, default_mask_node)
      empty = label_dummy.GetImageData().GetPointData().GetScalars().Fill(0)
      slicer.mrmlScene.RemoveNode(label_dummy)
      segmentation_node.AddSegmentFromBinaryLabelmapRepresentation(empty,name)
  
  def load(self,load_bg = True, volume_rendering = True):
    print(f"loading specimen {self.ID}")
    
    print(self.bg_path)

    #load background image
    if load_bg or not os.path.exists(self.segment_path):
      bg_node = slicer.util.loadVolume(self.bg_path)
      self.node_dict[self.bg_path] = bg_node

    # load mask
    mask_node = slicer.util.loadVolume(self.mask_path)
    self.node_dict[self.mask_path] = mask_node

    #return 

    if os.path.exists(self.segment_path):
      # if segmentation file exists -> load it
      print("loading previous segmentation...")
      segmentationNode = slicer.util.loadSegmentation(self.segment_path)
      
      qt.QApplication.processEvents()
      
      if load_bg:
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.node_dict[self.bg_path])
      else:
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.node_dict[self.mask_path])  
      
      # segmentationNode.GetDisplayNode().SetOpacity(.5)
      # self.node_dict[self.segment_path] = segmentationNode 
      # self.writeable_node_paths.append(self.segment_path)
      
    
    else:
      # if segmentation file not exists -> initialize it

      #create segmentation
      segmentationNode = slicer.vtkMRMLSegmentationNode()
      slicer.mrmlScene.AddNode(segmentationNode)
      segmentationNode.CreateDefaultDisplayNodes()
      
      if load_bg:
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.node_dict[self.bg_path])
      else:
        segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(self.node_dict[self.mask_path])  

      qt.QApplication.processEvents()
      
      print("initializing new segmentation...")
      m_img = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(mask_node)
      s = segmentationNode.AddSegmentFromBinaryLabelmapRepresentation(m_img,"mask", [1,1,1])
      segmentation = segmentationNode.GetSegmentation()
      displayNode = segmentationNode.GetDisplayNode()
      _id = segmentation.GetSegmentIdBySegmentName(s)
      displayNode.SetSegmentVisibility(_id, False)
     

      for sn in segment_names:
        self.load_or_init_segement(self.get_img_path(sn), sn, segmentationNode, mask_node)
        qt.QApplication.processEvents()


    self.node_dict[self.segment_path] = segmentationNode
    self.writeable_node_paths.append(self.segment_path)
    segmentationNode.GetDisplayNode().SetOpacity(.5)
    print("initialization done")

    if load_bg:
      slicer.util.setSliceViewerLayers(background=bg_node)
      # slicer.util.setSliceViewerLayers(background=bg_node,foreground=mask_node,foregroundOpacity=0.0)

    self.customize_workplace()
    
    if volume_rendering:
      self.start_volume_rendering()


  def save(self):
    print(f"saving specimen {self.ID}")
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
    print(f"closing specimen {self.ID}")
    remaining_nodes = {}

    for k in self.node_dict.keys():
      try:
        node = self.node_dict[k]
        slicer.mrmlScene.RemoveNode(node)
      except:
        remaining_nodes[k] = node

    self.node_dict = dict(remaining_nodes)


def batch_exporter():
    import vtk, qt, ctk, slicer
    import os
    if slicer.modules.PigletSegmentorWidget.logic.hasActiveSpecimen:
        print("Please close active specimen!")
        return
    
    slicer.modules.PigletSegmentorWidget.onBtnInitializeStudy()
    for sid, specimen in slicer.modules.PigletSegmentorWidget.logic.Specimens.items():
        if not specimen.db_info["done"]=='1':
            continue
        #open specimen
        slicer.modules.PigletSegmentorWidget.logic.load_specimen(sid,load_bg = False,volume_rendering = False)

        qt.QApplication.processEvents()
        
        segmentation_node = slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode").GetItemAsObject(0)

        volume = specimen.node_dict[specimen.mask_path]
        

        for seg_name in segment_names:
            print(f"exporting segement {seg_name}...")
            labelmap_node = slicer.vtkMRMLLabelMapVolumeNode()
            segment_ID = segmentation_node.GetSegmentation().GetSegmentIdBySegmentName(seg_name)
            segment = segmentation_node.GetSegmentation().GetSegment(segment_ID)
            
            qt.QApplication.processEvents()
            
            if isinstance(segment, type(None)):
                    print(f"segment {seg_name} not exists.")
                    continue

            segments = vtk.vtkStringArray()
            segments.SetNumberOfValues(1)
            segments.SetValue(0,segment_ID)
            
            slicer.mrmlScene.AddNode(labelmap_node)
            slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(segmentation_node, segments, labelmap_node, volume)
            
            myStorageNode = labelmap_node.CreateDefaultStorageNode()
            out_file = os.path.join(specimen.batch_export_dir,f"{sid}-{seg_name}.nii.gz")
            myStorageNode.SetFileName(out_file)
            myStorageNode.WriteData(labelmap_node)
            print(f"Saving {out_file}")
            try:
                slicer.mrmlScene.RemoveNode(labelmap_node)
            except Exception as e:
                print(e)
            
            # try:
            #     slicer.mrmlScene.RemoveNode(myStorageNode)
            # except Exception as e:
            #     print(e)
            
            qt.QApplication.processEvents()            


        #close specimen
        slicer.modules.PigletSegmentorWidget.logic.close_active_specimen(True)
        qt.QApplication.processEvents()
