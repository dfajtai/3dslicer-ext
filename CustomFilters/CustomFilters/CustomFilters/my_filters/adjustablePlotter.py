import vtk
import slicer
import numpy as np
import qt


class ControllableHistogram:
  def __init__(self,ui, input_image, widget_list, container= None):
    if not isinstance(self.input_image,slicer.vtkMRMLScalarVolumeNode):
     raise TypeError("Invalid input image")
  
    if widget_list is None:
      widget_list=[]
        
    self.ui = ui
    self.input_image = input_image,
    self.widget_list = widget_list
    self.container = container
    
    self.logscale = False
    
    self.clip_min = None
    self.clip_max = None
    
    self.plot_container = None
    self.plot_view_node = None
    
    self.clear_tables()
    
    self.tables = {}
    
  
  def clear_tables(self):
    old_tables = slicer.mrmlScene.GetNodesByName(self.table_name+"*")
    if old_tables.GetNumberOfItems()>0:
      for i in old_tables.NewIterator():
        slicer.mrmlScene.removeNode(i)
        
  def create_table(self,sub_name = ""):
    full_name = f"{self.table_name}_{sub_name}"
    old_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
    if old_node:
      slice.mrmlScene.RemoveNode(old_node)
    
    new_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode",full_name)
    self.tables[sub_name] = new_table

    
  
  def create_ui(self, add_group_box = False):
     
    if self.container is None:
      assert isinstance(self.ui.parent, qt.QFormLayout)
      
      self.container = qt.QFormLayout()
      if add_group_box:
        group_box = qt.QGroupBox("Adjustable histogram")
        group_box.setLayout(self.container)
        self.widget_list.append(group_box)
        self.ui.parent.addRow(group_box)
      else:
        self.ui.parent.addRow(self.container)
    else:
      assert isinstance(self.container,qt.QFormLayout)
    
    
    self.plot_container = slicer.qMRMLPlotWidget()
    self.plot_container.visible = False
    self.plot_container.minimumHeight = 200
    self.plot_container.setMRMLScene(slicer.mrmlScene)
      
    self.widget_list.append(self.plot_container)
    self.container.addRow(self.plot_container)
    
    self.plot_view_node = slicer.vtkMRMLPlotViewNode()
    
    
  @property
  def input_image_name(self):
    return self.input_image.GetName()
  
  @property
  def table_name(self):
    return f"{self.input_image_name}_hist_table"
  
  def calculate_histogram(self,number_of_bins):
    count, val = np.histogram(slicer.util.arrayFromVolume(self.input_image), bins=number_of_bins)
    if self.logscale:
      count = np.clip(np.log10(count),0,np.inf)

    return count,val
    
  def update_table(self,histogram_data, sub_name):
    count,val = histogram_data
    self.create_table(sub_name=sub_name)
    slicer.util.updateTableFromArray(self.tables.get(sub_name) (count,val))
    
    self.tables.get(sub_name).GetTable().GetColumn(0).SetName(f"{'' if not self.logscale else 'log '}Count")
    self.tables.get(sub_name).GetTable().GetColumn(1).SetName("Voxel Val.")
    

def addOrUpdateControllableHistogram(ui, input_image, widget_list, container = None):
  chist = ControllableHistogram(ui=ui,input_image=input_image,widget_list=widget_list,container=container)
  chist.create_ui()