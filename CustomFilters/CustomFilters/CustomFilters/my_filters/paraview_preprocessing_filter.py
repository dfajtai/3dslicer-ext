import numpy as np
import vtk
import qt
import ctk

import slicer


from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils

from .simplePlotter import addOrUpdateHistogram

from .dtype_handling import *


def showYesNoMessageBox(title, text, parent=None):
  parent = parent if parent is not None else slicer.util.mainWindow()
  msgBox = ctk.ctkMessageBox(parent)
  msgBox.setWindowTitle(title)
  msgBox.setStandardButtons(qt.QMessageBox.Yes | qt.QMessageBox.No)
  msgBox.setDefaultButton(qt.QMessageBox.Yes)

  label = qt.QLabel(text)

  # Üzenet szöveg törlése és label hozzáadása
  msgBox.setText("")
  layout = msgBox.layout()
  layout.addWidget(label, 0, 0, 1, layout.columnCount(), qt.Qt.AlignCenter)

  # Középre helyezés a Slicer főablakhoz képest
  mainWin = slicer.util.mainWindow()

  msgBox.setWindowModality(qt.Qt.ApplicationModal)
  ret = msgBox.exec_()
  return ret


class ParaviewPreprocessingFilter(CustomFilter):
  filter_name = "Paraview Preprocessing Filter"
  short_description = "Perform linear intensity transform on an image to preprocess it for Paraview Volume Rendering."
  tooltip = "Intensity transform for paraview."

  filter_sizes = [0,1,2,3,4,5,8,10,12]

  def __init__(self):
    super().__init__()
    self.filter_name = ParaviewPreprocessingFilter.filter_name
    self.short_description = ParaviewPreprocessingFilter.short_description
    self.tooltip = ParaviewPreprocessingFilter.tooltip
    

    self.clip_val = None
    self.adaptive_clip = None
    self.out_dtype = None
    self.out_name = None
    self.median_filter_list = []

    self.median_filter_controls = {}
    self.median_filter_control_group = None

    self.sitk_img = None
    

  def createUI(self, parent):
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parametersFormLayout)
    
    slicer.modules.CustomFiltersWidget.setFooterVisibility(False)

    # set default values
    
    UI.default_parameters["clip_val"] = -1024
    UI.default_parameters["adaptive_clip"] = True
    UI.default_parameters["dtype"] = "float"
    UI.default_parameters["out_name"] = ""
    UI.default_parameters["median_filter_settings"] = [0]
    # # input node
    
    input_widget = UI.createInputWidget()
    UI.addWidgetWithToolTipAndLabel(input_widget,{"tip":"Pick the input  to the algorithm.","label":"Input volume"})
    UI.inputs.append(input_widget.currentNode())

    # button...
    analyze_image_button = qt.QPushButton("Analyze image")
    UI.widgets.append(analyze_image_button)
    UI.addWidgetWithToolTip(analyze_image_button,{"tip":"Analyze input image"})
    analyze_image_button.connect('clicked(bool)', self.analyze_image)
    UI.widgetConnections.append((analyze_image_button, 'clicked(bool)'))
    
    # plot container ...
    UI.plot_container = slicer.qMRMLPlotWidget()
    UI.plot_container.visible = False
    UI.plot_container.minimumHeight = 200   
    UI.widgets.append(UI.plot_container)
    parametersFormLayout.addRow(UI.plot_container)
       
    
    # clip value
    UI.clip_value_widget =slicer.qMRMLSliderWidget()
    UI.widgets.append(UI.clip_value_widget)
    UI.addWidgetWithToolTipAndLabel(UI.clip_value_widget,{"tip":"Values bellow this value will be CERTAINLY set to zero",
                      "label":"Clip value"})
    UI.clip_value_widget.enabled = False
    UI.clip_value_widget.value =  UI.default_parameters["clip_val"]
    UI.clip_value_widget.connect("valueChanged(double)",
                                lambda val, widget=UI.clip_value_widget, name = 'clip_val': self.onFloatValueChanged(name,widget,val))
    UI.widgetConnections.append((UI.clip_value_widget, 'valueChanged(double)'))
    

    # adaptive clip checkbox
    adaptive_clip_label = qt.QLabel("Adaptive clip")
    UI.widgets.append(adaptive_clip_label)

    UI.adaptiveClipBox = qt.QCheckBox()
    UI.widgets.append(UI.adaptiveClipBox)
    UI.adaptiveClipBox.setToolTip("Enable adaptive clipping: The algorithm searches for the smallet value in the imput image greater than or equal to (closed interval) the 'Clip value'")
    UI.adaptiveClipBox.setChecked(UI.outputLabelMap)
    UI.adaptiveClipBox.setDisabled(True)

    UI.adaptiveClipBox.connect("stateChanged(int)", lambda val:self.on_adaptive_clip_changed(val))
    UI.widgetConnections.append((UI.adaptiveClipBox, "stateChanged(int)"))
    # add to layout after connection
    parametersFormLayout.addRow(adaptive_clip_label, UI.adaptiveClipBox)


    # out image name 
    UI.out_name_widget = qt.QLineEdit()
    UI.out_name_widget.text = UI.default_parameters["out_name"]
    UI.addWidgetWithToolTipAndLabel(UI.out_name_widget,{"tip":"Output image name",
                      "label":"Output base name"})
    # UI.out_name_widget.enabled = False

    # out dtype    
    UI.dtype_widget = qt.QComboBox()
    
    UI.widgets.append(UI.dtype_widget)
    for l,v in zip(dtype_labels,dtype_values):
      UI.dtype_widget.addItem(l,v)        
      # print((l,v))
    
    UI.dtype_widget.currentText = UI.default_parameters["dtype"]

    UI.addWidgetWithToolTipAndLabel(UI.dtype_widget,{"tip":"Output image data type",
                  "label":"Out data type"})

    UI.dtype_widget.enabled = False
    UI.dtype_widget.connect("currentIndexChanged(int)", 
                            lambda selectorIndex,name="out_dtype",selector=UI.dtype_widget:self.onEnumChanged(name,selectorIndex,selector))
    UI.widgetConnections.append((UI.dtype_widget, 'currentIndexChanged(int)'))
    self.out_dtype = UI.default_parameters["dtype"]

    # median filter select gui

    median_filter_select_layout = qt.QFormLayout()
    self.median_filter_control_group = ctk.ctkCollapsibleGroupBox()
    UI.parent.addRow(self.median_filter_control_group)
    UI.widgets.append(self.median_filter_control_group)    
    self.median_filter_control_group.setLayout(median_filter_select_layout)
    
    self.median_filter_control_group.setTitle("Median filter settings")
    self.median_filter_control_group.visible = False
    
    for size in self.filter_sizes:
      checkbox = qt.QCheckBox(str(size))
      if size in UI.default_parameters["median_filter_settings"]:
        self.median_filter_list.append(size)
        checkbox.checked = True
      else:
        checkbox.checked = False

      if size==0:
        checkbox.setToolTip("No filtering")
      else:
        checkbox.setToolTip(f"Apply median filter with kernel size of {str(int(size))} voxels")
      
      checkbox.connect("toggled(bool)",lambda x,_size=size: self.on_median_checkbox_changed(x,_size))
      UI.widgetConnections.append((checkbox,"toggled(bool)"))
      UI.widgets.append(checkbox)

      self.median_filter_controls[int(size)] = checkbox
      median_filter_select_layout.addRow(checkbox)
    

    # gerenrate images btn

    UI.generate_images_btn = qt.QPushButton("Generate output images")
    UI.widgets.append(UI.generate_images_btn)
    UI.addWidgetWithToolTip(UI.generate_images_btn,{"tip":"Generate images"})
    UI.generate_images_btn.connect('clicked(bool)',self.generate_images)
    UI.widgetConnections.append((UI.generate_images_btn,'clicked(bool)'))
    UI.generate_images_btn.enabled = False
    
    self.UI = UI
    return UI
  
  def onFloatValueChanged(self,name,widget,val):
    if name == "clip_val":
      self.clip_val = val

    
  def onEnumChanged(self,name,index,widget):
    data = widget.itemData(index)
    text = widget.itemText(index)
    if name == "out_dtype":
      self.out_dtype = data


  def on_median_checkbox_changed(self, checked:bool = False, size:int = 0):
    # print(f"{size} is checked: {checked}")
    if not checked:
      if size in self.median_filter_list:
        self.median_filter_list = sorted([s for s in self.median_filter_list if s != size])
    else:
      if size not in self.median_filter_list:
        self.median_filter_list.append(size)
      self.median_filter_list = sorted(self.median_filter_list)
  
  def on_adaptive_clip_changed(self,value):
    self.adaptive_clip = bool(value)


  def analyze_image(self):    
    # load image
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      self.UI.clip_value_widget.enabled = False
      self.UI.out_name_widget.enabled = False
      self.UI.adaptiveClipBox.enabled = False
      self.UI.plot_container.visible = False
      self.UI.dtype_widget.enabled = False
      self.UI.generate_images_btn.enabled = False

      self.median_filter_control_group.visible = False
        
      raise ReferenceError("Inputs not initialized.")
  
    self.UI.clip_value_widget.enabled = True
    self.UI.out_name_widget.enabled = True
    self.UI.adaptiveClipBox.enabled = True
    self.median_filter_control_group.visible = True
    self.UI.dtype_widget.enabled = True
    self.UI.generate_images_btn.enabled = True
    
    # self.UI.dtype_widget.currentText = self.UI.default_parameters["dtype"]

    input_img_node_name = self.UI.inputs[0].GetName()
    self.UI.out_name_widget.text = f"{input_img_node_name}_PV"
    
    addOrUpdateHistogram(self, self.UI,self.UI.plot_container,input_image = self.UI.inputs[0])
    self.UI.plot_container.visible = True    
    
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    
    # print(reverse_lookup_dtype(sitk_img.GetPixelID()))
    # print(sitk_img.GetPixelID())
    # print(sitk_img.GetPixelIDValue())
    # print(sitk_img.GetPixelIDTypeAsString())
    
    # dtype_index = reverse_lookup_dtype(sitk_img.GetPixelID(),True)
    # if not isinstance(dtype_index,type(None)):
    #   self.UI.dtype_widget.setCurrentIndex(dtype_index)
    
    filter = sitk.MinimumMaximumImageFilter()
    filter.Execute(sitk_img)
    min_val = filter.GetMinimum()
    max_val = filter.GetMaximum()
    self.UI.clip_value_widget.minimum = min_val
    self.UI.clip_value_widget.maximum = max_val

    self.clip_val = max(min_val,self.UI.default_parameters["clip_val"])
    self.UI.clip_value_widget.value = self.clip_val

  def generate_images(self):
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      raise ReferenceError("Inputs not initialized.")

    self.out_name = self.UI.out_name_widget.text

    # checkup
    if len(self.median_filter_list)== 0:
      self.median_filter_list = [0]
    checkup_text = f"The following images will be generated with clipping at {self.clip_val}"
    for s in self.median_filter_list:
      if s == 0:
        checkup_text +=f"\nUn-smoothed image:\t{self.out_name}"
      else:
        checkup_text +=f"\nKernel size = {s}:\t{self.out_name}-m{s}"
    checkup_text +=f"\nDo you proceed?"
    
    result = showYesNoMessageBox(
        title="Attention",
        text=checkup_text,
    )

    if result != qt.QMessageBox.Yes:
        return

    input_img_node_name = self.UI.inputs[0].GetName()
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    filter = sitk.MinimumMaximumImageFilter()
    filter.Execute(sitk_img)
    image_min_val = filter.GetMinimum()
    image_max_val = filter.GetMaximum()

    img_data = sitk.GetArrayFromImage(sitk_img)
    img_data_mask = np.zeros_like(img_data)
    
    if self.adaptive_clip:
      _clip_val = np.min(img_data[img_data>=clip_val])
    else:
      _clip_val = self.clip_val

    displacement = 0-_clip_val
    img_data = img_data + displacement
    img_data[img_data<0] = 0

    rescaled_sitk_image = sitk.GetImageFromArray(img_data)
    rescaled_sitk_image.SetOrigin(sitk_img.GetOrigin())
    rescaled_sitk_image.SetDirection(sitk_img.GetDirection())
    rescaled_sitk_image.SetSpacing(sitk_img.GetSpacing())
    
    del(img_data)

    for s in self.median_filter_list:
      out_name =self.out_name
      if s != 0:
        out_name+=f"-m{s}"
      qt.QApplication.processEvents()
      print(f"Calculating image '{out_name}' [ParaView preprocessign with clip @{_clip_val} & median filter of {s} size]")
      if s != 0:
        med_filter = sitk.MedianImageFilter()
        med_filter.SetDebug(False)
        med_filter.SetNumberOfThreads(16)
        med_filter.SetNumberOfWorkUnits(0)
        med_filter.SetRadius(tuple([s]*rescaled_sitk_image.GetDimension()))
        median_filtered = med_filter.Execute(rescaled_sitk_image)
      else:
        median_filtered = rescaled_sitk_image
      
      try:
        casted_image = sitk.Cast(median_filtered, lookup_dtype(self.out_dtype))
        outputNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", out_name)
        sitkUtils.PushVolumeToSlicer(casted_image,out_name)
        print("Calculation done.")
        qt.QApplication.processEvents()
      except Exception as e:
        print(e)
        continue
      