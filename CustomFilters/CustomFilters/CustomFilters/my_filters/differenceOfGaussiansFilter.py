import numpy as np
import vtk
import qt
import ctk

import slicer
import math

from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils
from .myPlotter import addOrUpdateHistogram


class DoGFilter(CustomFilter):
  filter_name = "Difference of Gaussians Filter"
  short_description = "Apply (multi-level) Difference of Gaussians Filter on the input image."
  tooltip = "Difference of Gaussians filter."

  def __init__(self):
    super().__init__()
    self.filter_name = DoGFilter.filter_name
    self.short_description = DoGFilter.short_description
    self.tooltip = DoGFilter.tooltip
    
    self.input_image = None
    
    self.smooth_image_lookup = {}
    self.smooth_image_dict = {}
    self.smooth_image_idx = 0
    
    self.dog_image_lookup = {}
    self.dog_image_dict = {}
    self.dog_image_idx = 0
    
    self.current_image = None
    
    self.selected_item = None
    self.selected_item_type = None
    

  def createUI(self, parent):
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parametersFormLayout)
    
    slicer.modules.CustomFiltersWidget.setFooterVisibility(False)
    
    # # input node
    input_widget = UI.createInputWidget()
    UI.addWidgetWithToolTipAndLabel(input_widget,{"tip":"Pick the input  to the algorithm.","label":"Input volume"})
    UI.inputs.append(input_widget.currentNode())

    input_widget.connect("nodeActivated(vtkMRMLNode*)", lambda node:self.flush_data())
    UI.widgetConnections.append((input_widget, "nodeActivated(vtkMRMLNode*)"))
    
    # additional UI elements    
    # Load widget from .ui file (created by Qt Designer).
    # Additional widgets can be instantiated manually and added to self.layout.
    UI.dog_ui = slicer.util.loadUI(slicer.modules.CustomFiltersWidget.resourcePath('UI/DoGFilter.ui'))
    UI.dog_ui.setMRMLScene(slicer.mrmlScene)
    UI.dog_ui_elements = slicer.util.childWidgetVariables(UI.dog_ui)
    parametersFormLayout.addRow(UI.dog_ui)
    UI.widgets.append(UI.dog_ui)
    
    UI.dog_ui_elements.btn_create_smooth_image.connect('clicked(bool)',self.calculate_smooth_image)
    UI.widgetConnections.append((UI.dog_ui_elements.btn_create_smooth_image,'clicked(bool)'))
    
    UI.dog_ui_elements.btn_calculate_dog.connect('clicked(bool)',self.calculate_dog_image)
    UI.widgetConnections.append((UI.dog_ui_elements.btn_calculate_dog,'clicked(bool)'))
    
    
    UI.dog_ui_elements.btn_remove_all.connect('clicked(bool)',self.flush_data)
    UI.widgetConnections.append((UI.dog_ui_elements.btn_remove_all,'clicked(bool)'))
    
    UI.dog_ui_elements.btn_remove_selected.connect('clicked(bool)',self.remove_selected)
    UI.widgetConnections.append((UI.dog_ui_elements.btn_remove_selected,'clicked(bool)'))

    UI.dog_ui_elements.btn_view_image.connect('clicked(bool)',self.show_selected)
    UI.widgetConnections.append((UI.dog_ui_elements.btn_view_image,'clicked(bool)'))

    UI.dog_ui_elements.btn_export_image.connect('clicked(bool)',self.export_selected)
    UI.widgetConnections.append((UI.dog_ui_elements.btn_export_image,'clicked(bool)'))
    
    
    UI.dog_ui_elements.smooth_image_list.connect('itemClicked(QListWidgetItem*)',
                                                   lambda item: self.select_changed(item,"smooth"))
    UI.widgetConnections.append((UI.dog_ui_elements.smooth_image_list,'itemClicked(QListWidgetItem*)'))
    
    
    UI.dog_ui_elements.dog_image_list.connect('itemClicked(QListWidgetItem*)',
                                                   lambda item: self.select_changed(item,"dog"))
    UI.widgetConnections.append((UI.dog_ui_elements.dog_image_list,'itemClicked(QListWidgetItem*)'))
    
    
    
    UI.outputSelector = UI.dog_ui_elements.export_node
    UI.outputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    UI.outputSelector.selectNodeUponCreation = True
    UI.outputSelector.addEnabled = True
    UI.outputSelector.removeEnabled = False
    UI.outputSelector.renameEnabled = True
    UI.outputSelector.noneEnabled = False
    UI.outputSelector.showHidden = False
    UI.outputSelector.showChildNodeTypes = False
    UI.outputSelector.baseName = self.filter_name +" Output"
    UI.outputSelector.setMRMLScene( slicer.mrmlScene )
    UI.outputSelector.setToolTip("Pick/create image to export the selected result image." )

    
    self.UI = UI
    
    self.update_gui()
    
    return UI
  

          
  def calculate_smooth_image(self):
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      raise ReferenceError("Input image not initialized.")
    
    # read the gui
    fwhm = self.UI.dog_ui_elements.fwhm_input.value
    
    if not fwhm:
      print("FWHM must be > 0.")
      raise ValueError("Invalid FWHM.")
    
    input_img_node_name = self.UI.inputs[0].GetName()
    
    sigma = fwhm / (2 * math.sqrt(2 * math.log(2)))
    
    # smooth the image
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    
    self.input_image = sitk_img

    smooth_image = sitk.Cast(sitk.SmoothingRecursiveGaussian(sitk_img,[sigma]*3),sitk_img.GetPixelID())

    
    # store the result
    name = f'FWHM = {fwhm} mm'
    old_index = self.smooth_image_lookup.get(name)
    
    if not isinstance(old_index,type(None)):
      self.smooth_image_dict[old_index] = smooth_image
    else:
      self.smooth_image_lookup[name] = self.smooth_image_idx      
      self.smooth_image_dict[self.smooth_image_idx] = smooth_image
      self.smooth_image_idx+=1

    # show the result
    
    self.show_stored_image(smooth_image,name)
    
    # update the gui
    self.update_gui()
    
    
  def calculate_dog_image(self):    
    fist_image_cb = self.UI.dog_ui_elements.first_image_cb
    second_image_cb = self.UI.dog_ui_elements.second_image_cb
    
    first_image_index = fist_image_cb.currentData
    second_image_index = second_image_cb.currentData
    
    if first_image_index == second_image_index:
      raise ValueError("First and Second images can not be the same")

    first_image = self.smooth_image_dict[first_image_index] if first_image_index != -1 else self.input_image
    second_image = self.smooth_image_dict[second_image_index] if second_image_index != -1 else self.input_image
    
    first_text = fist_image_cb.currentText if fist_image_cb.currentData == -1 else f'Smooth {str(fist_image_cb.currentText).replace("FWHM = ","")}'
    second_text = second_image_cb.currentText if second_image_cb.currentData == -1 else f'Smooth {str(second_image_cb.currentText).replace("FWHM = ","")}'
    
    name = f"DoG : {first_text} - {second_text}"
    
    diff = sitk.Subtract(first_image,second_image)
    
    # store the result
    old_index = self.dog_image_lookup.get(name)
    
    if not isinstance(old_index,type(None)):
      self.dog_image_dict[old_index] = diff
    else:
      self.dog_image_lookup[name] = self.dog_image_idx
      self.dog_image_dict[self.dog_image_idx] = diff
      self.dog_image_idx+=1
    
        # show the result

    self.show_stored_image(diff,name)
    
    # update the gui
    self.update_gui()
    
    
  def show_stored_image(self, image,image_name = "DoG Filter Result"):
    if isinstance(self.current_image, slicer.vtkMRMLScalarVolumeNode):
      slicer.mrmlScene.RemoveNode(self.current_image)
      
    self.current_image = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode')
    
    self.current_image.SetName(image_name)
    sitkUtils.PushVolumeToSlicer(image,image_name)
    
    slicer.util.setSliceViewerLayers(background=self.current_image)
  
  def has_selected(self):
    smooth_selected = self.UI.dog_ui_elements.smooth_image_list.selectedItems()
    dog_selected = self.UI.dog_ui_elements.dog_image_list.selectedItems()
    
    return len(smooth_selected) or len(dog_selected)
  
  
  def get_selected_image(self): 
    if self.has_selected():
      image_type = self.selected_item_type
      
      data = self.selected_item.data(1)
      text = self.selected_item.text()
      image_name = text
      
      if image_type == "smooth":
        image = self.smooth_image_dict[data]
      else:
        image = self.dog_image_dict[data]
      
      return (image, image_name, image_type)
    else:
      raise ValueError("No item selected")
  
    
  def show_selected(self):
    selected_image, image_name, image_type = self.get_selected_image()
    self.show_stored_image(selected_image,image_name)
    
  def remove_selected(self):
    selected_image, image_name, image_type = self.get_selected_image()
    
    if image_type == "smooth":
      idx = self.smooth_image_lookup[image_name]
      del self.smooth_image_dict[idx]
      del self.smooth_image_lookup[image_name]
      
    elif image_type == "dog":
      idx = self.dog_image_lookup[image_name]
      del self.dog_image_dict[idx]
      del self.dog_image_lookup[image_name]
    
    self.update_gui()
  
  def export_selected(self):
    selected_image, image_name, image_type = self.get_selected_image()
    
    out_node = slicer.mrmlScene.GetNodeByID(self.UI.dog_ui_elements.export_node.currentNodeID)
    if out_node:
      sitkUtils.PushVolumeToSlicer(selected_image,out_node)
  
  
  def flush_data(self):
    self.smooth_image_lookup = {}
    self.smooth_image_dict = {}
    self.smooth_image_idx = 0
    
    self.dog_image_lookup = {}
    self.dog_image_dict = {}
    self.dog_image_idx = 0
    
    if isinstance(self.current_image, slicer.vtkMRMLScalarVolumeNode):
      slicer.mrmlScene.RemoveNode(self.current_image)
      self.current_image = None
    
    self.update_gui()
     
  
  def select_changed(self,item, list_type):
    if list_type == "smooth":
      self.UI.dog_ui_elements.dog_image_list.clearSelection()
      
    elif list_type == "dog":
      self.UI.dog_ui_elements.smooth_image_list.clearSelection()
    
    self.selected_item = item
    self.selected_item_type = list_type
    
    self.UI.dog_ui_elements.btn_remove_selected.enabled = True
    self.UI.dog_ui_elements.btn_view_image.enabled = True
    self.UI.dog_ui_elements.btn_export_image.enabled = True
    
    
    
  def update_gui(self):
    smooth_images_list_widget = self.UI.dog_ui_elements.smooth_image_list
    dog_images_list_widget = self.UI.dog_ui_elements.dog_image_list
    
    fist_image_cb = self.UI.dog_ui_elements.first_image_cb
    second_image_cb = self.UI.dog_ui_elements.second_image_cb
    
    smooth_images_list_widget.clear()
    fist_image_cb.clear()
    second_image_cb.clear()
    
    fist_image_cb.addItem("Original image",-1)
    second_image_cb.addItem("Original image",-1)
    
    for key, index in self.smooth_image_lookup.items():
      label =  key
      new_item = qt.QListWidgetItem()
      new_item.setText(label)
      new_item.setData(1,index)
      smooth_images_list_widget.addItem(new_item)
      
      fist_image_cb.addItem(label,index)
      second_image_cb.addItem(label,index)
      
    dog_images_list_widget.clear()
    for key, index in self.dog_image_lookup.items():
      label =  key
      new_item = qt.QListWidgetItem()
      new_item.setText(label)
      new_item.setData(1,index)
      dog_images_list_widget.addItem(new_item)
    
    if not self.selected_item:
      self.UI.dog_ui_elements.btn_remove_selected.enabled = False
      self.UI.dog_ui_elements.btn_view_image.enabled = False
      self.UI.dog_ui_elements.btn_export_image.enabled = False
    else:
      self.UI.dog_ui_elements.btn_remove_selected.enabled = True
      self.UI.dog_ui_elements.btn_view_image.enabled = True
      self.UI.dog_ui_elements.btn_export_image.enabled = True