import vtk
import slicer
import numpy as np
import qt
import ctk

import sitkUtils
import SimpleITK as sitk


class ControllableHistogram:
  def __init__(self, ui, input_image, widget_list, container= None, segmentation_node = None, segment_names = None):
    if not isinstance(input_image,slicer.vtkMRMLScalarVolumeNode):
     raise TypeError("Invalid input image")
  
    if widget_list is None:
      widget_list=[]
      
    if segment_names is None:
      segment_names = []
        
    self.ui = ui
    self.input_image = input_image
    self.widget_list = widget_list
    self.container = container
    
    self.segmentation_node = segmentation_node
    self.segment_names = segment_names
    
    self.logscale = False
    
    self.number_of_bins = 50
    self.clip_min = None
    self.clip_max = None
    
    self.gui_initialized = False
    
    # ui elements
    self.plot_widget = None
    self.plot_view_node = None
    self.plot_chart_node = None
    
    self.control_group = None
    self.input_vol_selector = None
    self.input_seg_selector = None
    self.clip_range_control = None
    self.bin_control = None
    self.logscale_control = None
      
    self.image_min = None
    self.image_max = None
    
    self.tables = {}
    self.series = {}
    
    # clear data...
    self.remove_all_tables()
    self.remove_all_series()
  
  @property
  def input_image_name(self):
    """Input image name"""
    return self.input_image.GetName()
  
  @property
  def table_name(self):
    """Base table name"""
    return f"{self.input_image_name}_hist_table"
  
  @property
  def series_name(self):
    """Base plot series name"""
    return f"{self.input_image_name}_hist_series"
  
  @property
  def chart_name(self):
    """Chart name"""
    return f"{self.input_image_name}_hist_chart"
  
  
  def table_name_with_subname(self,subname = ""):
    """Extends the base table name with a subname (e.g. segment name)"""
    full_name = f"{self.table_name}_{subname}" if subname !="" else f"{self.table_name}"
    return full_name
  
  def series_name_with_subname(self,subname = ""):
    """Extends the base plot series name with a subname (e.g. segment name)"""
    full_name = f"{self.series_name}_{subname}" if subname !="" else f"{self.series_name}"
    return full_name
  
  
  def table_name_to_series_name(self,table_name):
    """Converts the table name to the corresponding plot series name"""
    return str(table_name).replace(self.table_name,self.series_name)
    
  def series_name_to_table_name(self,series_name):
    """Converts the plot series name to the corresponding table name"""
    return str(series_name).replace(self.series_name,self.table_name)
  
  def extract_subname(self,name_with_subname):
    """Extracts subname from a table or a series name (with/without a subname)"""
    if self.table_name in name_with_subname:
      name = name_with_subname.replace(self.table_name,"")
      
    elif self.series_name in name_with_subname:
      name = name_with_subname.replace(self.series_name,"")
    
    else:
      name = ""
    
    if name.startswith("_"):
      name = name[1:] if len(name)>1 else ""
    
    return name
  
  
       
  
  def create_ui(self, add_group_box = True):
    """Creates the UI"""
     
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
    
    
    self.plot_widget = slicer.qMRMLPlotWidget()
    self.plot_widget.visible = True
    self.plot_widget.minimumHeight = 200
    self.plot_widget.setMRMLScene(slicer.mrmlScene)
      
    self.widget_list.append(self.plot_widget)
    self.container.addWidget(self.plot_widget)
    
    self.plot_view_node = slicer.vtkMRMLPlotViewNode()
    print("create controls")
    
    # controls
    control_group_layout = qt.QFormLayout()
    self.control_group = ctk.ctkCollapsibleGroupBox()
    self.container.addRow(self.control_group)
    
    self.control_group .setTitle("Plot controls")
    
    self.input_vol_selector = slicer.qMRMLNodeComboBox()
    self.input_vol_selector.setMRMLScene(slicer.mrmlScene)
    self.input_vol_selector.nodeTypes = ('vtkMRMLScalarVolumeNode',)
    

    self.clip_range_control = ctk.ctkRangeWidget()
    
    self.control_group.setLayout(control_group_layout)
  
    # functions
    def update_volume_min_max(self,caller=None, event=None):
      volume_node = self.input_vol_selector.currentNode()
      image_data = volume_node.GetImageData()
      scalar_range = image_data.GetScalarRange()
      self.image_min = scalar_range[0]
      self.image_max = scalar_range[1]

      self.clip_range_control.minimum = self.image_min
      self.clip_range_control.maximum = self.image_max
      
    self.input_vol_selector.connect("currentNodeChanged(vtkMRMLNode*)",lambda x:update_volume_min_max(self))
        
    # initialization
    self.input_vol_selector.setCurrentNode(self.input_image)    
    
    self.gui_initialized = True
  
  # TABLES
  def remove_all_tables(self):
    """Removes all tables from SCENE"""
    old_tables = slicer.mrmlScene.GetNodesByName(self.table_name+"*")
    if old_tables.GetNumberOfItems()>0:
      for i in old_tables.NewIterator():
        slicer.mrmlScene.removeNode(i)
    self.tables = {}
    
  def remove_table(self,name):
    """Removes a given table form SCENE"""
    if self.tables.get(name):
      slice.mrmlScene.RemoveNode(self.tables.get(name))
      
        
  def create_table(self,subname = "", remove=False):
    """Creates a new table"""
    
    def _create_table(subname,full_name):
      table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode",full_name)
      self.tables[subname] = table_node
      return table_node
    
    full_name = self.table_name_with_subname(subname)
    
    if self.tables.get(subname):
      table_node = self.tables.get(subname)
    else:
      table_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
    
    if isinstance(table_node,slicer.vtkMRMLTableNode):
      if remove:
        slice.mrmlScene.RemoveNode(table_node)
        table_node = _create_table(subname=subname,full_name=full_name)
    else:
      table_node = _create_table(subname=subname,full_name=full_name)

    return table_node
  
  
  # SERIES
  def remove_all_series(self):
    """Revmoves all plot series form SCENE"""
    
    old_series = slicer.mrmlScene.GetNodesByName(self.series_name+"*")
    if old_series.GetNumberOfItems()>0:
      for i in old_series.NewIterator():
        slicer.mrmlScene.removeNode(i)
    self.series = {}
  
  def remove_series(self,series):
    """Removes a given plot series form SCENE"""
    if not isinstance(series,slicer.vtkMRMLPlotSeriesNode):
      self.remove_series_by_name(series)

    else:
      name = series.GetName()
      slice.mrmlScene.RemoveNode()
      del(self.series[name])

  
  def remove_series_by_name(self,name):
    """Removes a given plot series by its name (with/without subname) from SCENE"""
    if not isinstance(name,str):
      return
    name = self.extract_subname(name)
    if self.series.get(name):
      slice.mrmlScene.RemoveNode(self.series.get(name))
      del(self.series[name])
  
    
  def create_or_update_series(self,subname = "",remove = False):
    """Creates or updates a plot series with a given subname"""
    full_name = self.series_name_with_subname(subname)
    
    def create_series(subname,full_name):
      series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",full_name)
      self.series[subname] = series_node
      return series_node
    
    if self.series.get(subname):
      series_node = self.series.get(subname)
    else:
      series_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
      
    if isinstance(series_node, slicer.vtkMRMLPlotSeriesNode):
      if remove:
        slice.mrmlScene.RemoveNode(series_node)
        series_node = create_series(subname=subname, full_name=full_name)
    else:
      series_node = create_series(subname=subname, full_name=full_name)
      
    self.update_series(series_node,subname)
    self.set_initial_series_parameters(series_node,self.logscale)
      
    return series_node 
  
  def update_series(self,series,subname):
    """Updates a the table represented by the given series"""
    
    if not isinstance(series,slicer.vtkMRMLPlotSeriesNode):
      return self.create_or_update_series(subname=subname)
          
    table_node = self.tables.get(subname)
    if isinstance(table_node,slicer.vtkMRMLTableNode):
      series.SetAndObserveTableNodeID(table_node.GetID())
      
    return series
  
  
  # CHART
  def remove_chart(self):
    """Removes the chart form SCENE"""
    if self.plot_chart_node:
      slicer.mrmlScene.RemoveNode(self.plot_chart_node)
    else:
      old_node = slicer.mrmlScene.GetFirstNodeByName(self.chart_name)
      if old_node:
        slice.mrmlScene.RemoveNode(old_node)
  
  def create_chart(self):
    """Creates the chart"""
    self.remove_chart()
    self.plot_chart_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode",self.chart_name)
  
          
  def calculate_histogram(self,number_of_bins,clip_min=None, clip_max = None):
    """Calculates histogram data wihtout mask"""
    
    data = slicer.util.arrayFromVolume(self.input_image)
    if (clip_min is not None) or (clip_max is not None): 
      data = np.clip(data,clip_min,clip_max)
    count, val = np.histogram(data, bins=number_of_bins)
    if self.logscale:
      count = np.clip(np.log10(count),0,np.inf)

    return count,val
  
  def calculate_histogram_with_mask(self, mask, number_of_bins,clip_min=None, clip_max = None):
    """Calculates histogram data INSIDE a mask"""
    assert isinstance(mask,np.ndarray)
    
    data = slicer.util.arrayFromVolume(self.input_image)
    assert np.allclose(mask.shape,data.shape)
    
    if (clip_min is not None) or (clip_max is not None): 
      data = np.clip(data,clip_min,clip_max)
    count, val = np.histogram(data[mask==1], bins=number_of_bins)
    if self.logscale:
      count = np.clip(np.log10(count),0,np.inf)

    return count,val
  
  def update_table(self,histogram_data, subname):
    """Updates a given table (with a histogram data)"""
    
    count,val = histogram_data
    new_table = self.create_table(subname=subname)
    slicer.util.updateTableFromArray(new_table, (count,val))
    
    new_table.GetTable().GetColumn(0).SetName(f"{'' if not self.logscale else 'log '}Count")
    new_table.GetTable().GetColumn(1).SetName("Voxel Val.")
    
    return new_table
    
  def update_histogram(self, add_whole_image_histogram = False):
    """Creates tables form the selected image (and selected segment(s))"""
       
    if isinstance(self.segmentation_node,slicer.vtkMRMLSegmentationNode):
      if add_whole_image_histogram:
        histogram_data = self.calculate_histogram(self.number_of_bins,self.clip_min,self.clip_max)
        self.update_table(histogram_data=histogram_data,subname="")
      
      # iterate over segments
      
      segmentation = self.segmentation_node.GetSegmentation()
      num_of_segments = segmentation.GetNumberOfSegments()
      
      
      new_seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
      new_seg.SetReferenceImageGeometryParameterFromVolumeNode(self.input_image)
      new_segmentation = new_seg.GetSegmentation()
      
      new_segment_index = 0
      
      colorTableNode = slicer.mrmlScene.GetFirstNodeByName('vtkMRMLColorTableNodeGreen')
      
      for i in range(num_of_segments):
        segment = segmentation.GetNthSegment(i)
        segment_name = segment.GetName()
        if segment_name not in self.segment_names:
            continue
          
        print(f"Processign segment '{segment_name}'")
                    
        segmentId = segmentation.GetSegmentIdBySegmentName(segment_name)
        labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")

        new_segmentation.CopySegmentFromSegmentation(segmentation,segmentId)            
        new_segment_id = new_segmentation.GetNthSegmentID(new_segment_index)            
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(new_seg, 
                                                                          [new_segment_id], 
                                                                          labelmapVolumeNode, 
                                                                          self.input_image, 
                                                                          slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY, 
                                                                          colorTableNode)
        
        new_segment_index +=1
        
        sitk_address = sitkUtils.GetSlicerITKReadWriteAddress(labelmapVolumeNode)
        sitk_img = sitk.ReadImage(sitk_address)
        mask = sitk.GetArrayFromImage(sitk_img)
        
        slicer.mrmlScene.RemoveNode(labelmapVolumeNode)
        
        print(f"Segement '{segment_name}' processed")
        slicer.app.processEvents()

        histogram_data = self.calculate_histogram_with_mask(self.number_of_bins,clip_min=self.clip_min,clip_max=self.clip_max,mask=mask)
        self.update_table(histogram_data=histogram_data,subname=segment_name)
      
      slicer.mrmlScene.RemoveNode(new_seg)
      slicer.mrmlScene.RemoveNode(colorTableNode)
      
    else:
      histogram_data = self.calculate_histogram(self.number_of_bins,self.clip_min,self.clip_max)
      self.update_table(histogram_data=histogram_data,subname="")
  
  
  def add_series_to_chart(self, subname):
    """Adds a plot series to the chart"""
    if not isinstance(self.plot_chart_node,slicer.vtkMRMLPlotChartNode):
      return
    if isinstance(self.series.get(subname),slicer.vtkMRMLPlotSeriesNode):
      self.plot_chart_node.AddAndObservePlotSeriesNodeID(self.series.get(subname).GetID())
  
  def remove_all_series_from_chart(self):
    """Removes all plot series node from the chart"""
    if not isinstance(self.plot_chart_node,slicer.vtkMRMLPlotChartNode):
      return
    self.plot_chart_node.RemoveAllPlotSeriesNodeIDs()
  
  def remove_series_form_chart(self,subname):
    """Removes a plot series from the chart"""
    if not isinstance(self.plot_chart_node,slicer.vtkMRMLPlotChartNode):
      return
    if isinstance(self.series.get(subname),slicer.vtkMRMLPlotSeriesNode):
      self.plot_chart_node.RemovePlotSeriesNodeID(self.series.get(subname).GetID())
    else:
      full_name = self.series_name_with_subname(subname)
      node = slicer.mrmlScene.GetFirstNodeByName(full_name)
      if isinstance(node,slicer.vtkMRMLPlotSeriesNode):
        self.plot_chart_node.RemovePlotSeriesNodeID(node.GetID())

  @staticmethod
  def set_initial_series_parameters(series_node, logscale = False):
    """Initializes plto series graphical settigns and so"""
    if not isinstance(series_node,slicer.vtkMRMLPlotSeriesNode ):
      return
  
    
  def update_histogram_plots(self, visible_names = None):    
    """Creates plot series form table(s), adds visible plot series to the chart"""
    if not isinstance(self.plot_chart_node,slicer.vtkMRMLPlotChartNode):
      self.create_chart()
  
    if visible_names is None:
      visible_names = list(self.tables.keys())
      
    assert isinstance(visible_names,list)
    unwanted_subnames = []
    visible_series_count = self.plot_chart_node.GetNumberOfPlotSeriesNodes()
    for idx in range(visible_series_count):
      series_node = self.plot_chart_node.GetNthPlotSeriesNode(idx)
      if not isinstance(series_node,slicer.vtkMRMLPlotSeriesNode):
        continue
      full_name = series_node.GetName()
      subname = self.extract_subname(full_name)
      if name not in visible_names:
        unwanted_subnames.append(subname)
      
    for subname in unwanted_subnames:
      self.remove_series_form_chart(subname=subname)
    
    for name in visible_names:
      _name = self.extract_subname(name)
      series = self.create_or_update_series(subname=_name)      

      self.plot_chart_node.AddAndObservePlotSeriesNodeID(series.GetID())
      # self.add_series_to_chart(_name)
      
    return self.show_chart()
      
  def show_chart(self):
    if not self.gui_initialized:
      return False
    
    assert isinstance(self.plot_view_node,slicer.vtkMRMLPlotViewNode)
    assert isinstance(self.plot_widget,slicer.qMRMLPlotWidget)
    
    self.plot_view_node.SetPlotChartNodeID(self.plot_chart_node.GetID())
    self.plot_widget.setMRMLPlotViewNode(self.plot_view_node)


def addOrUpdateControllableHistogram(ui, input_image, widget_list, container = None):
  chist = ControllableHistogram(ui=ui,input_image=input_image,widget_list=widget_list,container=container)
  chist.create_ui()
  chist.update_histogram()
  chist.update_histogram_plots()