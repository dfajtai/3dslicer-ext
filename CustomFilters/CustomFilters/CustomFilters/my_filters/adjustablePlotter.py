import vtk
import slicer
import numpy as np
import qt

import sitkUtils
import SimpleITK as sitk


class ControllableHistogram:
  def __init__(self,ui, input_image, widget_list, container= None, segmentation_node = None, segment_names = None):
    if not isinstance(self.input_image,slicer.vtkMRMLScalarVolumeNode):
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
    
    self.number_of_bins = None
    self.clip_min = None
    self.clip_max = None
    
    self.plot_container = None
    self.plot_view_node = None
    self.plot_chart_node = None
    
    self.clear_tables()
    
    self.tables = {}
    self.series = {}
  
  @property
  def input_image_name(self):
    return self.input_image.GetName()
  
  @property
  def table_name(self):
    return f"{self.input_image_name}_hist_table"
  
  @property
  def series_name(self):
    return f"{self.input_image_name}_hist_series"
  
  @property
  def chart_name(self):
    return f"{self.input_image_name}_hist_chart"
  
  
  def clear_tables(self):
    old_tables = slicer.mrmlScene.GetNodesByName(self.table_name+"*")
    if old_tables.GetNumberOfItems()>0:
      for i in old_tables.NewIterator():
        slicer.mrmlScene.removeNode(i)
        
  def create_table(self,sub_name = ""):
    full_name = f"{self.table_name}_{sub_name}"
    if self.tables.get(sub_name):
      slice.mrmlScene.RemoveNode(self.tables.get(sub_name))
    else:
      old_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
      if old_node:
        slice.mrmlScene.RemoveNode(old_node)
      
    new_table = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode",full_name)
    self.tables[sub_name] = new_table

    return new_table
  
  
  def clear_series(self):
    old_series = slicer.mrmlScene.GetNodesByName(self.series_name+"*")
    if old_series.GetNumberOfItems()>0:
      for i in old_series.NewIterator():
        slicer.mrmlScene.removeNode(i)
        
  def create_series(self,sub_name = ""):
    full_name = f"{self.series_name}_{sub_name}"
    if self.series.get(sub_name):
      slice.mrmlScene.RemoveNode(self.series.get(sub_name))
    else:
      old_node = slicer.mrmlScene.GetFirstNodeByName(full_name)
      if old_node:
        slice.mrmlScene.RemoveNode(old_node)
    
    new_series = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",full_name)
    self.series[sub_name] = new_series
    
    return new_series
  
  def clear_chart(self):
    if self.plot_chart_node:
      slicer.mrmlScene.RemoveNode(self.plot_chart_node)
    else:
      old_node = slicer.mrmlScene.GetFirstNodeByName(self.chart_name)
      if old_node:
        slice.mrmlScene.RemoveNode(old_node)
  
  def create_chart(self):
    self.clear_chart()
    self.plot_chart_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode",self.chart_name)
  
  
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
    
    
  def calculate_histogram(self,number_of_bins,clip_min=None, clip_max = None):
    data = slicer.util.arrayFromVolume(self.input_image)
    data = np.clip(data,clip_min,clip_max)
    count, val = np.histogram(data, bins=number_of_bins)
    if self.logscale:
      count = np.clip(np.log10(count),0,np.inf)

    return count,val
  
  def calculate_histogram(self, mask, number_of_bins,clip_min=None, clip_max = None):
    assert isinstance(mask,np.ndarray)
    
    data = slicer.util.arrayFromVolume(self.input_image)
    assert np.allclose(mask.shape,data.shape)
    
    data = np.clip(data,clip_min,clip_max)
    count, val = np.histogram(data[mask==1], bins=number_of_bins)
    if self.logscale:
      count = np.clip(np.log10(count),0,np.inf)

    return count,val
  
  def update_table(self,histogram_data, sub_name):
    count,val = histogram_data
    new_table = self.create_table(sub_name=sub_name)
    slicer.util.updateTableFromArray(new_table, (count,val))
    
    new_table.GetTable().GetColumn(0).SetName(f"{'' if not self.logscale else 'log '}Count")
    new_table.GetTable().GetColumn(1).SetName("Voxel Val.")
    
    return new_table
    
  def update_histogram(self):
    tables = {}
    
    if isinstance(self.segmentation_node,slicer.vtkMRMLSegmentationNode):
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

        histogram_data = self.calculate_histogram(self.number_of_bins,clip_min=self.clip_min,clip_max=self.clip_max,mask=mask)
        self.update_table(histogram_data=histogram_data,sub_name=segment_name)
      
      slicer.mrmlScene.RemoveNode(new_seg)
      slicer.mrmlScene.RemoveNode(colorTableNode)
    
    else:
      histogram_data = self.calculate_histogram(self.number_of_bins,self.clip_min,self.clip_max)
      self.update_table(histogram_data=histogram_data,sub_name="")

  def update_plot(self):
    #TODO create series from tables, update chart... or so
    pass

def addOrUpdateControllableHistogram(ui, input_image, widget_list, container = None):
  chist = ControllableHistogram(ui=ui,input_image=input_image,widget_list=widget_list,container=container)
  chist.create_ui()