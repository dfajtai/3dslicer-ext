import vtk
import slicer
import numpy as np
import qt
import ctk

import sitkUtils
import SimpleITK as sitk


class InteractiveHistogram:  
  def __init__(self, ui, input_image, widget_list, container= None, segmentation_node = None, segment_names = None,
               use_masks = False, show_total = True):
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
    self.show_total = show_total
    self.use_masks = use_masks
    
    self.gui_initialized = False
    
    # ui elements
    self.plot_widget = None
    self.plot_view_node = None
    self.plot_chart_node = None
    
    self.control_group = None
    self.input_vol_selector = None
    self.clip_range_control = None
    self.bin_control = None
    self.logscale_control = None
    self.use_masks_control = None
    
    
    self.segment_selector_block = None
    self.segment_selector = None
    self.segment_list_control = None
    self.show_total_control = None
      
    self.image_min = None
    self.image_max = None
    
    self.tables = {}
    self.series = {}
    
    # clear data...
    self.remove_all_series()
    self.remove_all_tables()
    
  
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
  
  
  @property
  def x_axis_label(self):
    return "Voxel Val."
  
  @property
  def noscale_y_axis_label(self):
    return "Count"
  
  @property
  def logscale_y_axis_label(self):
    return "log Count"
  
  @property
  def y_axis_label(self):
    return self.logscale_y_axis_label if self.logscale else self.noscale_y_axis_label
  
  
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
        group_box = qt.QGroupBox("Interactive histogram")
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
    
    self.control_group.setTitle("Plot controls")
    
    self.input_vol_selector = slicer.qMRMLNodeComboBox()
    self.input_vol_selector.setMRMLScene(slicer.mrmlScene)
    self.input_vol_selector.nodeTypes = ('vtkMRMLScalarVolumeNode',)
    self.input_vol_selector.setCurrentNode(self.input_image)   
    
    control_group_layout.addRow(qt.QLabel("Input image"))
    control_group_layout.addRow(self.input_vol_selector)
    

    self.clip_range_control = ctk.ctkRangeWidget()
    control_group_layout.addRow(qt.QLabel("Histogram range"))
    control_group_layout.addRow(self.clip_range_control)
    
    control_group_layout.addRow(qt.QLabel("Bin count on range"))
    self.bin_control = slicer.qMRMLSliderWidget()
    self.bin_control.decimals = 0
    self.bin_control.minimum = 1
    self.bin_control.maximum = 100
    self.bin_control.value = self.number_of_bins
    control_group_layout.addRow(self.bin_control)
    
    
    self.logscale_control = qt.QCheckBox("Show counts in log10 scale")
    self.logscale_control.checked = self.logscale
    control_group_layout.addRow(self.logscale_control)
    
    self.use_masks_control = qt.QCheckBox("Use segments as masks")
    self.use_masks_control.checked = self.use_masks
    control_group_layout.addRow(self.use_masks_control)
    
    # --> segment selector...
    self.segment_selector_block = qt.QGroupBox()
    self.segment_selector_block.setTitle("Segment based settings")
    self.segment_selector_block.visible = self.use_masks
    segment_selector_layout = qt.QFormLayout()
    self.segment_selector_block.setLayout(segment_selector_layout)
    control_group_layout.addRow(self.segment_selector_block)
    
    self.show_total_control = qt.QCheckBox("Show total image histogram")
    self.show_total_control.checked = self.show_total
    segment_selector_layout.addRow(self.show_total_control)
        
    self.segment_selector = slicer.qMRMLSegmentSelectorWidget()
    self.segment_selector.setMRMLScene(slicer.mrmlScene)
    segment_selector_layout.addRow(self.segment_selector)
    
    add_segment_btn = qt.QPushButton()
    add_segment_btn.text = "Add segment"            
    segment_selector_layout.addRow(add_segment_btn)
    
    
    
    remove_segment_btn = qt.QPushButton()
    remove_segment_btn.text = "Remove segment"            
    segment_selector_layout.addRow(remove_segment_btn)
    
    
    self.control_group.setLayout(control_group_layout)
    
    # functions
    def on_input_image_changed(self,caller=None, event=None):
      volume_node = self.input_vol_selector.currentNode()
      image_data = volume_node.GetImageData()
      scalar_range = image_data.GetScalarRange()
      self.image_min = scalar_range[0]
      self.image_max = scalar_range[1]

      self.clip_range_control.minimum = self.image_min
      self.clip_range_control.maximum = self.image_max
      # self.clip_range_control.minimumValue = max(self.clip_range_control.minimumValue,self.image_min)
      # self.clip_range_control.maximumValue = min(self.clip_range_control.maximumValue,self.image_max)
      self.clip_range_control.minimumValue = self.image_min
      self.clip_range_control.maximumValue = self.image_max
      
      if self.gui_initialized:
        self.remove_all_series()
        self.remove_all_tables()
        self.input_image = volume_node
        self.update_histogram()
        self.update_histogram_plots()
        
    
    def on_add_segment(self):
      seg_node_id = self.segment_selector.currentNodeID()
      seg_node = slicer.mrmlScene.GetNodeByID(seg_node_id)
      if not isinstance(seg_node,slicer.vtkMRMLSegmentationNode):
        return
      is_changed = False
      if self.segmentation_node is None:
        is_changed = True
      else:
        if isinstance(self.segmentation_node,slicer.vtkMRMLSegmentationNode):
          if self.segmentation_node.GetID()!=seg_node.GetID():
            is_changed = True
        else:
          is_changed = True
          
      self.segmentation_node = seg_node
      if self.segment_names is None:
        self.segment_names = []
        is_changed = True
      
      
      segment_id =  self.segment_selector.currentSegmentID()
      segment_node = seg_node.GetSegmentation().GetSegment(segment_id)
      segment_name = segment_node.GetName()
      
      if segment_name not in self.segment_names:
        self.segment_names.append(segment_name)
        is_changed = True
        
      if is_changed: on_segment_change(self)
    
    def on_remove_segment(self):
      seg_node_id = self.segment_selector.currentNodeID()
      seg_node = slicer.mrmlScene.GetNodeByID(seg_node_id)
      if not isinstance(seg_node,slicer.vtkMRMLSegmentationNode):
        return
      
      segment_id =  self.segment_selector.currentSegmentID()
      segment_node = seg_node.GetSegmentation().GetSegment(segment_id)
      segment_name = segment_node.GetName()
      
      is_changed = False
      
      if self.segment_names is None:
        return
      
      if isinstance(self.segment_names, list):
        if segment_name in self.segment_names:
          is_changed = True
      self.segment_names.remove(segment_name)
      
      if is_changed: on_segment_change(self)
      
    
    def clear_all_segments(self):
      self.segmentation_node = None
      self.segment_names = None
      on_segment_change(self)
                      
    
    def on_show_total_changed(self):
      self.show_total = self.show_total_control.checked
      on_segment_change(self)
      
                      
    def on_segment_change(self):
      if self.gui_initialized:
        self.update_histogram()
        self.update_histogram_plots()
        
    def on_clip_change(self):
      self.clip_min = self.clip_range_control.minimumValue
      self.clip_max = self.clip_range_control.maximumValue

      if self.gui_initialized:
        self.update_histogram()
        self.update_histogram_plots()
      
      
    def on_logscale_change(self):
      self.logscale = self.logscale_control.checked
      
      if self.gui_initialized:
        self.update_histogram_plots() 
    
    
    def on_use_masks_change(self):
      self.use_masks = self.use_masks_control.checked
      self.segment_selector_block.visible = self.use_masks
      
      if self.use_masks == False:
        self.show_total=True
      
      self.show_total_control.checked = self.show_total
      
      clear_all_segments(self)
      
    
    def on_bincount_change(self):
      self.number_of_bins = int(self.bin_control.value)
      
      if self.gui_initialized:
        self.update_histogram()
        self.update_histogram_plots()
      
      
    self.input_vol_selector.connect("currentNodeChanged(vtkMRMLNode*)",lambda x:on_input_image_changed(self))
    self.logscale_control.connect("toggled(bool)",lambda x: on_logscale_change(self))
    self.use_masks_control.connect("toggled(bool)",lambda x: on_use_masks_change(self))
    self.bin_control.connect("valueChanged(double)", lambda x: on_bincount_change(self))
    self.clip_range_control.connect("valuesChanged(double,double)", lambda x: on_clip_change(self))
    add_segment_btn.connect('clicked(bool)',lambda x:on_add_segment(self))
    self.show_total_control.connect("toggled(bool)",lambda x: on_show_total_changed(self))
    
    # initialization     
    
    self.gui_initialized = True

    # trigger events
    on_input_image_changed(self)
    
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
      slicer.mrmlScene.RemoveNode(self.tables.get(name))
      
        
  def create_table(self,subname = "", use_full_name = False):
    """Creates a new table"""
    
    def _create_table(subname, full_name):
      if use_full_name:
        table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", full_name)
        self.tables[subname] = table_node
        return table_node
      
      table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", subname)
      self.tables[subname] = table_node
      return table_node
    
    full_name = self.table_name_with_subname(subname)
    
    if self.tables.get(subname):
      table_node = self.tables.get(subname)
    else:
      table_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
    
    if isinstance(table_node,slicer.vtkMRMLTableNode):
      slicer.mrmlScene.RemoveNode(table_node)
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
    
    self.remove_all_series_from_chart()
  
  def remove_series(self,series):
    """Removes a given plot series form SCENE"""
    if not isinstance(series,slicer.vtkMRMLPlotSeriesNode):
      self.remove_series_by_name(series)

    else:
      name = series.GetName()
      slicer.mrmlScene.RemoveNode()
      del(self.series[name])

  
  def remove_series_by_name(self,name):
    """Removes a given plot series by its name (with/without subname) from SCENE"""
    if not isinstance(name,str):
      return
    name = self.extract_subname(name)
    if self.series.get(name):
      slicer.mrmlScene.RemoveNode(self.series.get(name))
      del(self.series[name])
  
    
  def create_or_update_series(self,subname = "", use_full_name = False):
    """Creates or updates a plot series with a given subname"""
    full_name = self.series_name_with_subname(subname)
    
    def create_series(subname,full_name):
      if use_full_name:
        series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",full_name)
        self.series[subname] = series_node
        return series_node
    
      series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",subname)
      self.series[subname] = series_node
      return series_node

    if self.series.get(subname):
      series_node = self.series.get(subname)
    else:
      series_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
      
    if isinstance(series_node, slicer.vtkMRMLPlotSeriesNode):
      slicer.mrmlScene.RemoveNode(series_node)
    series_node = create_series(subname=subname, full_name=full_name)
      
    self.update_series(series_node,subname)
          
    return series_node 
  
  def update_series(self,series,subname):
    """Updates a the table represented by the given series"""
    
    if not isinstance(series,slicer.vtkMRMLPlotSeriesNode):
      return self.create_or_update_series(subname=subname)
          
    table_node = self.tables.get(subname)
    if isinstance(table_node,slicer.vtkMRMLTableNode):
      series.SetAndObserveTableNodeID(table_node.GetID())
      
      series.SetXColumnName(self.x_axis_label)
      series.SetYColumnName(self.y_axis_label)
      
      series.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatter)
      series.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
      series.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)  
      
    return series
  
  
  # CHART
  def remove_chart(self):
    """Removes the chart form SCENE"""
    if self.plot_chart_node:
      slicer.mrmlScene.RemoveNode(self.plot_chart_node)
    else:
      old_node = slicer.mrmlScene.GetFirstNodeByName(self.chart_name)
      if old_node:
        slicer.mrmlScene.RemoveNode(old_node)
  
  def create_chart(self):
    """Creates the chart"""
    self.remove_chart()
    self.plot_chart_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode",self.chart_name)
  
          
  def calculate_histogram(self,number_of_bins,clip_min=None, clip_max = None):
    """Calculates histogram data wihtout mask"""
    
    data = slicer.util.arrayFromVolume(self.input_image)
    if (clip_min is not None) or (clip_max is not None):
      clip_min = - np.inf if clip_min is None else clip_min
      clip_max =  np.inf if clip_max is None else clip_max
      data = data[(data>=clip_min) & (data<=clip_max)]
    count, val = np.histogram(data, bins=number_of_bins)
    logcount = np.log10(count,where=count>0)

    return val,count,logcount
  
  def calculate_histogram_with_mask(self, mask, number_of_bins,clip_min=None, clip_max = None):
    """Calculates histogram data INSIDE a mask"""
    assert isinstance(mask,np.ndarray)
    
    data = slicer.util.arrayFromVolume(self.input_image)
    assert np.allclose(mask.shape,data.shape)
    
    _mask = np.ones_like(data,dtype=bool)
    
    if (clip_min is not None) or (clip_max is not None):
      clip_min = - np.inf if clip_min is None else clip_min
      clip_max =  np.inf if clip_max is None else clip_max
      _mask[(data<clip_min) | (data>clip_max)] = False
      
    count, val = np.histogram(data[(mask==1)&(_mask)], bins=number_of_bins)
    logcount = np.log10(count,where=count>0)

    return val,count,logcount
  
  def update_table(self,histogram_data, subname):
    """Updates a given table (with a histogram data)"""
    
    val,count,logcount = histogram_data
    new_table = self.create_table(subname=subname)
    slicer.util.updateTableFromArray(new_table, (val, count, logcount))
    
    new_table.GetTable().GetColumn(0).SetName(self.x_axis_label)
    new_table.GetTable().GetColumn(1).SetName(self.noscale_y_axis_label)
    new_table.GetTable().GetColumn(2).SetName(self.logscale_y_axis_label)
    
    return new_table
    
  def update_histogram(self):
    """Creates tables form the selected image (and selected segment(s))"""
       
    if isinstance(self.segmentation_node,slicer.vtkMRMLSegmentationNode) and self.use_masks:
      if self.show_total:
        histogram_data = self.calculate_histogram(self.number_of_bins,self.clip_min,self.clip_max)
        self.update_table(histogram_data=histogram_data,subname="total")
        
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
          
        # print(f"Processign segment '{segment_name}'")
                    
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
        
        # print(f"Segement '{segment_name}' processed")
        slicer.app.processEvents()

        histogram_data = self.calculate_histogram_with_mask(number_of_bins = self.number_of_bins,clip_min=self.clip_min,clip_max=self.clip_max,mask=mask)
        self.update_table(histogram_data=histogram_data,subname=f"{segment_name}")
      
      slicer.mrmlScene.RemoveNode(new_seg)
      slicer.mrmlScene.RemoveNode(colorTableNode)
      
    else:
      histogram_data = self.calculate_histogram(self.number_of_bins,self.clip_min,self.clip_max)
      self.update_table(histogram_data=histogram_data,subname="total")
  
  
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

    
  def update_histogram_plots(self, visible_names = None):    
    """Creates plot series form table(s), adds visible plot series to the chart"""
    if not isinstance(self.plot_chart_node,slicer.vtkMRMLPlotChartNode):
      self.create_chart()

    self.remove_all_series_from_chart()
    
    if visible_names is None:
      visible_names = []
      
      if self.show_total or not self.use_masks:
        visible_names.append("total")
      
      if self.use_masks and isinstance(self.segment_names,list):
        visible_names.extend(self.segment_names)
      # print(visible_names)
      
    assert isinstance(visible_names,list)
    unwanted_subnames = []
    visible_series_count = self.plot_chart_node.GetNumberOfPlotSeriesNodes()
    for idx in range(visible_series_count):
      series_node = self.plot_chart_node.GetNthPlotSeriesNode(idx)
      if not isinstance(series_node,slicer.vtkMRMLPlotSeriesNode):
        continue
      full_name = series_node.GetName()
      subname = self.extract_subname(full_name)
      if subname not in visible_names:
        unwanted_subnames.append(subname)
      
    for subname in unwanted_subnames:
      self.remove_series_form_chart(subname=subname)
    
    for name in visible_names:
      series = self.create_or_update_series(subname=name)
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
    


def addOrUpdateInteractiveHistogram(ui, input_image, widget_list, container = None):
  ihist = InteractiveHistogram(ui=ui,input_image=input_image,widget_list=widget_list,container=container)
  ihist.logscale = True
  ihist.create_ui()