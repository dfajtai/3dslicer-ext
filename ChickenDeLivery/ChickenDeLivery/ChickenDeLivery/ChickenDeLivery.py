import logging
import os
from unicodedata import name
import qt
import vtk
import ctk

from qt import QFileDialog

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin


root_path = "/nas/medicopus_share/Projects/ANIMALS/kendermagos/liver_segmentation_ors"
# root_path = "/media/fajtai/DF64_4/"

_volume_rendering_  = True
# _render_mask_ = False

__database_csv_path__ = os.path.join(root_path,"etc","database.csv")
__preseg_csv_path__ = os.path.join(root_path,"etc","img_paths.csv")
__study_dir__ =  os.path.join(root_path)


def fix_path(rel_path):
  return os.path.join(str(__study_dir__), rel_path)


#
# ChickenDeLivery
#

class ChickenDeLivery(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "ChickenDeLivery"  # TODO: make this more human readable by adding spaces
    self.parent.categories = ["Segmentation"]  # TODO: set categories (folders where the module shows up in the module selector)
    self.parent.dependencies = []  # TODO: add here list of module names that this module requires
    self.parent.contributors = ["Daniel Fajtai"]  # TODO: replace with "Firstname Lastname (Organization)"
    # TODO: update with short description of the module and a link to online module documentation
    self.parent.helpText = """
    This is a simple module for chicken CT rib and vertebrae counting.
    See more information in <a href="https://github.com/organization/projectname#ChickenDeLivery">module documentation</a>.
    """
    # TODO: replace with organization, grant and thanks
    self.parent.acknowledgementText = """I made this on my own."""

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
  print("Sample for ChickenDeLivery not implemented")


#
# ChickenDeLiveryWidget
#

class ChickenDeLiveryWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
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

    self.tbl_selected_key_tuple = ()
    self.tbl_selected_key = "" # f"{batch}-{ID}-{position}
    self.tblSelectedIndex = None
    self.table_lock = False


  def setup(self):
    """
    Called when the user opens the module the first time and the widget is initialized.
    """
    ScriptedLoadableModuleWidget.setup(self)

    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    uiWidget = slicer.util.loadUI(self.resourcePath('UI/ChickenDeLivery.ui'))
    self.layout.addWidget(uiWidget)
    self.ui = slicer.util.childWidgetVariables(uiWidget)

    # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
    # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
    # "setMRMLScene(vtkMRMLScene*)" slot.
    uiWidget.setMRMLScene(slicer.mrmlScene)

    # Create logic class. Logic implements all computations that should be possible to run
    # in batch mode, without a graphical user interface.
    self.logic = ChickenDeLiveryLogic()

    # Connections

    # These connections ensure that we update parameter node when scene is closed
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
    self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

    # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
    # (in the selected parameter node).
    
    self.ui.tbDBPath.textChanged.connect(self.updateParameterNodeFromGUI)
    self.ui.tbPresegPath.textChanged.connect(self.updateParameterNodeFromGUI)

    self.ui.tblChickens.selectionModel().selectionChanged.connect(self.selected_chicken_changed)
    self.ui.tblChickens.itemChanged.connect(self.chicken_tbl_changed)
    
    # Buttons
    #self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.ui.btnInitializeStudy.connect('clicked(bool)',self.onBtnInitializeStudy)
    self.ui.btnSelectDB.connect('clicked(bool)',self.onBtnSelectDB)
    self.ui.btnSelectPreseg.connect('clicked(bool)',self.onBtnSelectPreseg)

    self.ui.btnBatchExport.connect('clicked(bool)',self.onBtnBatchExport)
    self.ui.btnLoadSelected.connect('clicked(bool)',self.onBtnLoadSelected)
    self.ui.btnSaveActiveChicken.connect('clicked(bool)',self.onBtnSaveActiveChicken)
    self.ui.btnCloseActiveChicken.connect('clicked(bool)',self.onBtnCloseActiveChicken)
    self.ui.btnSaveDB.connect('clicked(bool)',self.onBtnSaveDB)

    # Make sure parameter node is initialized (needed for module reload)
    self.initializeParameterNode()

  def cleanup(self):
    """
    Called when the application closes and the module widget is destroyed.
    """
    print("ChickenDelivery cleanup")
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
    if hasattr(self.logic, "active_chicken") and self.logic.active_chicken:
      self.logic.close_active_chicken(no_question=True)

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
      self.show_chicken_db_table()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

  def show_chicken_db_table(self):
    if self._parameterNode is None or self._updatingGUIFromParameterNode:
      return

    wasModified = self._parameterNode.StartModify()

    IDs = []   
    IDs.extend([ID for ID in self.logic.chickens.keys()])
    
    IDs = sorted(IDs)

    tbl = self.ui.tblChickens
    tbl.clear()
    tbl.clearContents()

    db_info_filter = ["ID","position","sex","Comment","done"]
    
    tbl.setColumnCount(len(db_info_filter))
    tbl.setRowCount(len(IDs))
    
    for i in range(len(IDs)):
      chicken = self.logic.chickens[IDs[i]]
      chicken.update_done(self.logic.dbTable)
      for j in range(len(db_info_filter)):
        tbl.setItem(i,j,qt.QTableWidgetItem(chicken.db_info.get(db_info_filter[j])))
        if j!=(len(db_info_filter)-1):
          #tbl.item(i,j).setFlags(qt.Qt.ItemIsEnabled)
          pass

      if chicken.db_info.get("done") == str(1):
        for j in range(self.ui.tblChickens.columnCount):
          tbl.item(i,j).setBackground(qt.QColor(0,127,0))


    tbl.setHorizontalHeaderLabels(db_info_filter)
    tbl.resizeColumnsToContents()
    self._parameterNode.EndModify(wasModified) 

  def selected_chicken_changed(self):
    current_selection = self.ui.tblChickens.selectedIndexes()
    if len(current_selection)>0:
      current_selection = current_selection[0]
      _ID = self.ui.tblChickens.item(current_selection.row(),0).text()
      _position = self.ui.tblChickens.item(current_selection.row(),1).text()
      
      tbl_selected = f"{_ID}-{_position}"
      
      self.tblSelectedIndex = current_selection
      self.tbl_selected_key = tbl_selected
      self.tbl_selected_key_tuple = (_ID,_position)
      self.ui.lblSelectedChicken.text = tbl_selected
  
  def chicken_tbl_changed(self):
    if self.table_lock:
      return
    self.table_lock = True

    try:
      tbl = self.ui.tblChickens
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
          _ID = self.ui.tblChickens.item(current_selection.row(),0).text()
          _position = self.ui.tblChickens.item(current_selection.row(),1).text()
          chicken = self.logic.chickens[(_ID,_position)]
        
          self.logic.dbTable.SetCellText(chicken.row_index,chicken.done_col_index, current_done)
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
      if not self.tbl_selected_key:
        return

      _ID, _position = self.tbl_selected_key_tuple
      load_success = self.logic.load_chicken(ID=_ID, position= _position,volume_rendering=_volume_rendering_)
      self.ui.btnLoadSelected.enabled = not self.logic.hasActiveChicken
      if self.logic.hasActiveChicken:
        self.ui.lblActiveChicken.text= f"{self.logic.active_chicken.ID}-{self.logic.active_chicken.position}"

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
      
  def onBtnSaveActiveChicken(self):
    try:
      save_success = self.logic.save_active_chicken()

    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()

  def onBtnCloseActiveChicken(self):
    try:
      close_success = self.logic.close_active_chicken()
      self.ui.btnLoadSelected.enabled = not self.logic.hasActiveChicken
      if not self.logic.hasActiveChicken:
        self.ui.lblActiveChicken.text= ""

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
# ChickenDeLiveryLogic
#

class ChickenDeLiveryLogic(ScriptedLoadableModuleLogic):
  _database_csv_path_ = fix_path(__database_csv_path__)
  _preseg_csv_path_ =  fix_path(__preseg_csv_path__)
  _study_dir_ = fix_path(__study_dir__)
  _root_dir_ = fix_path(root_path)
  
  def __init__(self):
    """
    Called when the logic class is instantiated. Can be used for initializing member variables.
    """
    ScriptedLoadableModuleLogic.__init__(self)

    self.dbTable = None
    self.dbDictList = []

    self.presegTable = None
    self.presegDictList = []
    
    self.ID_list = []
    self.chickens = {}

    self.active_chicken = None

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

    id_position = [(item.get("ID"),item.get("position"))  for item in self.dbDictList]
    id_position = sorted(id_position,key=lambda x: (x[0],x[1]))
    self.ID_list = id_position

    print(self.ID_list)
    print(f"Initializing {len(self.ID_list)} chickens")
    self.chickens = dict([((ID,position), Chicken(
                                                             ID = ID,
                                                             position = position, 
                                                             dbDictList= self.dbDictList, 
                                                             presegDictList = self.presegDictList, 
                                                             study_dir = self._study_dir_)) for (ID, position) in self.ID_list])

  

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

  def load_chicken(self, ID, position, volume_rendering = False):
    target_chicken = self.chickens.get((ID,position))

    if isinstance(self.active_chicken,Chicken):
      self.info_message_box("A chicken has been already loaded.")      
      return

    if isinstance(target_chicken,type(None)):
      raise ValueError(f"chicken {ID}-{position} not initialized")

    target_chicken.load(volume_rendering=volume_rendering)

    self.active_chicken = target_chicken

    return True
  
  def close_active_chicken(self, no_question = False):
    if no_question and not isinstance(self.active_chicken,type(None)):
      self.active_chicken.close()
      self.active_chicken = None
      return

    if not isinstance(self.active_chicken,Chicken):
      self.info_message_box("There is no active chicken to close.")
      return

    if not self.confim_message_box("Do you really want to close the active chicken?"):
      return
    self.active_chicken.close()
    self.active_chicken = None

  def save_active_chicken(self):
    if not isinstance(self.active_chicken,Chicken):
      self.info_message_box("There is no active chicken to save.")
      return

    self.active_chicken.save()
    qt.QApplication.processEvents()
    self.info_message_box("Save complete. You can safely close the chicken.")

  def save_db(self):
    _storageNode = self.dbTable.CreateDefaultStorageNode()
    _storageNode.SetFileName(self._database_csv_path_)
    _storageNode.WriteData(self.dbTable)


  @property
  def hasActiveChicken(self):
    return isinstance(self.active_chicken,Chicken)

#
# ChickenDeLiveryTest
#

class ChickenDeLiveryTest(ScriptedLoadableModuleTest):
  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear()
    

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_ChickenDeLivery()

  def test_ChickenDeLivery(self):
    assert(False)


class Chicken():
  def __init__(self, ID, position, dbDictList, presegDictList, study_dir):
    self.ID = ID
    self.position = position
    
    self.db_info = {}
    self.preseg_paths = {}
    self.study_dir = study_dir

    self.node_dict = {} # file path - node
    self.writeable_node_paths = []
    
    self.volume_rendering_node = None
    self.volume_rendering_roi  = None

    #get corresponding rows
    db_row = list(filter(lambda x: (x["ID"]==ID) & (x["position"]==position) , dbDictList))
    if len(db_row)>0:
      self.db_info = db_row[0]

    preseg_row = list(filter(lambda x: (x["ID"]==ID) & (x["position"]==position), presegDictList))
    if len(preseg_row)>0:
      self.preseg_paths = preseg_row[0]

    self.CT_path = fix_path(str(self.preseg_paths["img_path"]).replace(2*os.sep,os.sep))
    
    # self.enhanced_path = fix_path(str(self.preseg_paths["enhanced_img_path"]).replace(2*os.sep,os.sep))
    
    # self.mask_path = fix_path(str(self.preseg_paths["mask_path"]).replace(2*os.sep,os.sep))
    self.markups_path = fix_path(str(self.preseg_paths["markups_path"]).replace(2*os.sep,os.sep))

    self.row_index = 0
    for i in range(len(dbDictList)):
      if (dbDictList[i]["ID"]==ID) & (dbDictList[i]["position"]==position) :
        break
    self.row_index = i
    
    db_cols = list(db_row[0].keys())
    for j in range(len(db_cols)):
      if db_cols[j]=="done":
        break
    self.done_col_index = j


    #print(f"Chicken {self.ID} initialized." )

  @property
  def slicer_out_dir(self):
    return os.path.join(self.study_dir)
  
  @property
  def final_save_dir(self):
    return os.path.join(root_path,"results")

  def update_done(self,table):
    try:
      self.db_info["done"] = table.GetCellText(self.row_index,self.done_col_index)
    except Exception as e:
      slicer.util.errorDisplay("Failed to compute results: "+str(e))
      import traceback
      traceback.print_exc()
  
  def customize_workplace(self):
    #TODO implement...    
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

    # crosshair
    crosshair=slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLCrosshairNode")
    crosshair.SetCrosshairBehavior(crosshair.OffsetJumpSlice)
    crosshair.SetCrosshairToFine()
    crosshair.SetCrosshairMode(crosshair.ShowBasic)
    
    volume_display_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeDisplayNode")
    for v in volume_display_nodes:
      v.InterpolateOff()
      v.SetAutoWindowLevel(0)
      v.SetWindowLevelMinMax(-150,700)
    
    
    segmentEditorWidget = slicer.modules.segmenteditor.widgetRepresentation().self().editor
    # segmentEditorWidget.toggleMasterVolumeIntensityMaskEnabled()

  def start_volume_rendering(self, autoremove = False):
    logic = slicer.modules.volumerendering.logic()
    displayNode = logic.CreateVolumeRenderingDisplayNode()
    displayNode.UnRegister(logic)
    slicer.mrmlScene.AddNode(displayNode)
    
    # if _render_mask_:
    #   self.node_dict[self.mask_path].AddAndObserveDisplayNodeID(displayNode.GetID())
    #   logic.UpdateDisplayNodeFromVolumeNode(displayNode, self.node_dict[self.mask_path])
    # else:
    #   self.node_dict[self.CT_path].AddAndObserveDisplayNodeID(displayNode.GetID())
    #   logic.UpdateDisplayNodeFromVolumeNode(displayNode, self.node_dict[self.CT_path])
    
    self.node_dict[self.CT_path].AddAndObserveDisplayNodeID(displayNode.GetID())
    logic.UpdateDisplayNodeFromVolumeNode(displayNode, self.node_dict[self.CT_path])
    preset = logic.GetPresetByName('CT-Chest-Contrast-Enhanced')
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
    threeDView = threeDWidget.threeDView()
    
    viewNode = threeDView.mrmlViewNode()
    if viewNode:
      # Tengelyek (Axes) beállítása
      viewNode.SetOrientationMarkerType(slicer.vtkMRMLAbstractViewNode.OrientationMarkerTypeAxes)
      viewNode.SetOrientationMarkerSize(slicer.vtkMRMLAbstractViewNode.OrientationMarkerSizeLarge)
      viewNode.SetBoxVisible(False)
    # ------------------------------------
    
    threeDView.resetFocalPoint()
    threeDView.resetCamera()
    
    # restore markups node as default markup
    selectionNode = slicer.app.applicationLogic().GetSelectionNode()
    selectionNode.SetReferenceActivePlaceNodeID(self.markups_node.GetID())
    markupsLogic = slicer.modules.markups.logic()
    markupsLogic.SetActiveListID(self.markups_node)
    
    markupsWidget = slicer.modules.markups.widgetRepresentation()
    if markupsWidget:
      controlPointsButton = slicer.util.findChild(markupsWidget, 'controlPointsCollapsibleButton')
      if controlPointsButton:
        controlPointsButton.collapsed = False
        
    if autoremove:
      for r in self.volume_rendering_roi:
        slicer.mrmlScene.RemoveNode(r)
      self.volume_rendering_roi = []    
  
  def load(self, volume_rendering = True):
    print(f"loading chicken {self.ID}-{self.position}")

    #load ct
    CT_node = slicer.util.loadVolume(self.CT_path)
    self.node_dict[self.CT_path] = CT_node
    
    # mask_node = slicer.util.loadLabelVolume(self.mask_path)
    # self.node_dict[self.mask_path] = mask_node

    markups_node = slicer.util.loadMarkups(self.markups_path)
    self.node_dict[self.markups_path] = markups_node
    
    self.markups_node =  self.node_dict[self.markups_path] 
    self.markups_node.GetDisplayNode().SetColor(1,1,0)   

    self.writeable_node_paths.append(self.markups_path)
    
    slicer.util.setSliceViewerLayers(background=CT_node)
    
    self.customize_workplace()
    if volume_rendering:
      self.start_volume_rendering()


  def save(self):
    print(f"saving chicken {self.ID}-{self.position}")
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
      # slicer.mrmlScene.RemoveNode(_storageNode)


  def close(self):
    if slicer.mrmlScene.IsClosing():
      print("Scene is closing, skip chicken cleanup")
      return

    print(f"closing chicken '{self.ID}-{self.position}'")

    # Volume rendering display node
    if self.volume_rendering_node and slicer.mrmlScene.IsNodePresent(self.volume_rendering_node):
      slicer.mrmlScene.RemoveNode(self.volume_rendering_node)
      self.volume_rendering_node = None

    # ROI node – csak ha saját!
    if hasattr(self, "volume_rendering_roi") and self.volume_rendering_roi:
      for roi in self.volume_rendering_roi:
        if roi and slicer.mrmlScene.IsNodePresent(roi):
          slicer.mrmlScene.RemoveNode(roi)
      self.volume_rendering_roi = []

    # Saját node-ok
    for node in list(self.node_dict.values()):
      if node and slicer.mrmlScene.IsNodePresent(node):
        slicer.mrmlScene.RemoveNode(node)

    self.node_dict = {}


def batch_exporter():
    import vtk, qt, ctk, slicer
    import os
    if slicer.modules.ChickenDeLiveryWidget.logic.hasActiveChicken:
      print("Please close active chicken!")
      return
    
    slicer.modules.ChickenDeLiveryWidget.onBtnInitializeStudy()
    for (ID,position), chicken in slicer.modules.ChickenDeLiveryWidget.logic.chickens.items():
      if not chicken.db_info["done"]=='1':
        continue
      #open chicken
      slicer.modules.ChickenDeLiveryWidget.logic.load_chicken(ID = ID, position = position, volume_rendering= False)

      markups_node = chicken.node_dict[chicken.markups_path]
      if not os.path.isdir(chicken.final_save_dir):
        os.makedirs(chicken.final_save_dir,exist_ok=True)

      markups_save_path = os.path.join(chicken.final_save_dir,f"{str(chicken.ID).upper()}-{str(chicken.position).upper()}-markups.mrk.json")

      storageNode = markups_node.CreateDefaultStorageNode()
      storageNode.SetFileName(markups_save_path)
      storageNode.WriteData(markups_node)

      slicer.mrmlScene.RemoveNode(storageNode)

      #close chicken
      slicer.modules.ChickenDeLiveryWidget.logic.close_active_chicken(True)
        

        
