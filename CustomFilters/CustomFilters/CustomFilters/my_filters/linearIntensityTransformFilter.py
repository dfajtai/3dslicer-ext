import numpy as np
import vtk
import qt
import ctk

import slicer


from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils

from .myPlotter import addOrUpdateHistogram

from .dtype_handling import *


class LinearIntensityTransformFilter(CustomFilter):
  filter_name = "Linear Intensity Transform Filter"
  short_description = "Perform linear intensity transform on an image by clipping, and linear rescaling."
  tooltip = "Simple linear intensity transform."

  def __init__(self):
    super().__init__()
    self.filter_name = LinearIntensityTransformFilter.filter_name
    self.short_description = LinearIntensityTransformFilter.short_description
    self.tooltip = LinearIntensityTransformFilter.tooltip
    self.input_image_range = [None,None]
    

    self.clip = [None,None] # values bellow and above will be clipped
    self.out_range = [None,None] # return values on the range
    
    self.threshold = [None,None] # values bellow and above will be set to a given value
    self.bellow_val = None
    self.above_val = None
    
    self.out_dtype = None
  
    self.sitk_img = None
    

  def createUI(self, parent):
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parametersFormLayout)
    
    slicer.modules.CustomFiltersWidget.setFooterVisibility(True)

    # set default values
    
    UI.default_parameters["out_range"] = [0, 255]
    
    UI.default_parameters["clip"] =  [0, 100]
    
    UI.default_parameters["threshold"] =  [0, 100]
    
    UI.default_parameters["bellow_val"] =  0
    UI.default_parameters["above_val"] = 0
    UI.default_parameters["invert"] = False

    
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
    
    # clip widget    
    UI.clip_widget = ctk.ctkRangeWidget()
    UI.widgets.append(UI.clip_widget)
    
    UI.addWidgetWithToolTipAndLabel(UI.clip_widget,{"tip":"Values outside the 'clip range' will be set to the given 'clip range'",
                      "label":"Input clip range"})
    UI.clip_widget.enabled = False
    
    UI.clip_widget.connect("valuesChanged(double,double)",
                                lambda min,max, widget=UI.clip_widget, name = 'clip': self.onRangeChanged(name,widget,min,max))
    UI.widgetConnections.append((UI.clip_widget, 'valuesChanged(double,double)'))
    
    # # threshold widget    
    UI.threshold_widget = ctk.ctkRangeWidget()
    UI.widgets.append(UI.threshold_widget)
    UI.addWidgetWithToolTipAndLabel(UI.threshold_widget,{"tip":"Values outside the 'threshold range' will be set to the given values",
                      "label":"Input threshold range"})
    UI.threshold_widget.enabled = False
    
    UI.threshold_widget.connect("valuesChanged(double,double)",
                                lambda min,max, widget=UI.threshold_widget, name = 'threshold': self.onRangeChanged(name,widget,min,max))
    UI.widgetConnections.append((UI.threshold_widget, 'valuesChanged(double,double)'))
    
    
    # # bellow value
    UI.bellow_value_widget = qt.QDoubleSpinBox()
    UI.widgets.append(UI.bellow_value_widget)
    UI.addWidgetWithToolTipAndLabel(UI.bellow_value_widget,{"tip":"Values bellow the 'threshold range' will be set to this value in the output image - if it is safe to...",
                      "label":"Bellow thr. value"})
    UI.bellow_value_widget.enabled = False
    UI.bellow_value_widget.value =  UI.default_parameters["bellow_val"]
    UI.bellow_value_widget.connect("valueChanged(double)",
                                lambda val, widget=UI.bellow_value_widget, name = 'bellow_val': self.onFloatValueChanged(name,widget,val))
    UI.widgetConnections.append((UI.bellow_value_widget, 'valueChanged(double)'))
    
    
    # above value
    UI.above_value_widget = qt.QDoubleSpinBox()
    UI.widgets.append(UI.above_value_widget)
    UI.addWidgetWithToolTipAndLabel(UI.above_value_widget,{"tip":"Values above the 'threshold range' will be set to this value in the output image - if it is safe to...",
                      "label":"Above thr. value"})
    UI.above_value_widget.enabled = False
    UI.above_value_widget.value =  UI.default_parameters["above_val"]
    UI.above_value_widget.connect("valueChanged(double)",
                                lambda val, widget=UI.above_value_widget, name = 'above_val': self.onFloatValueChanged(name,widget,val))
    UI.widgetConnections.append((UI.above_value_widget, 'valueChanged(double)'))
    
    # out range widget
    UI.out_range_widget = ctk.ctkCoordinatesWidget()
    UI.widgets.append(UI.out_range_widget)
    UI.addWidgetWithToolTipAndLabel(UI.out_range_widget,{"tip":"Set the desired output data range",
                      "label":"Output data range"})
    UI.out_range_widget.dimension = 2
    UI.out_range_widget.enabled = True
    UI.out_range_widget.connect("coordinatesChanged(double*)",
                                lambda val, widget=UI.out_range_widget, name = 'out_range': self.onFloatVectorChanged(name,widget,val))
    UI.out_range_widget.coordinates = ','.join([str(np.round(val,2)) for val in UI.default_parameters["out_range"]])
    UI.widgetConnections.append((UI.out_range_widget, 'coordinatesChanged(double*)'))
    
    # out dtype    


    UI.dtype_widget = qt.QComboBox()
    UI.widgets.append(UI.dtype_widget)
    for l,v in zip(dtype_labels,dtype_values):
      UI.dtype_widget.addItem(l,v)
      # print((l,v))
          
    UI.addWidgetWithToolTipAndLabel(UI.dtype_widget,{"tip":"Output image data type",
                  "label":"Out data type"})
  
    UI.dtype_widget.connect("currentIndexChanged(int)", 
                            lambda selectorIndex,name="out_dtype",selector=UI.dtype_widget:self.onEnumChanged(name,selectorIndex,selector))
    UI.widgetConnections.append((UI.dtype_widget, 'currentIndexChanged(int)'))
    
    #
    # output volume selector
    #
    outputSelectorLabel = qt.QLabel("Output Volume: ")
    UI.widgets.append(outputSelectorLabel)

    UI.outputSelector = slicer.qMRMLNodeComboBox()
    UI.widgets.append(UI.outputSelector)
    UI.outputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"]
    UI.outputSelector.selectNodeUponCreation = True
    UI.outputSelector.addEnabled = True
    UI.outputSelector.removeEnabled = False
    UI.outputSelector.renameEnabled = True
    UI.outputSelector.noneEnabled = False
    UI.outputSelector.showHidden = False
    UI.outputSelector.showChildNodeTypes = False
    UI.outputSelector.baseName = self.filter_name +" Output"
    UI.outputSelector.setMRMLScene( slicer.mrmlScene )
    UI.outputSelector.setToolTip( "Pick the output to the algorithm." )

    UI.outputSelector.connect("nodeActivated(vtkMRMLNode*)", lambda node:UI.onOutputSelect(node))
    UI.widgetConnections.append((UI.outputSelector, "nodeActivated(vtkMRMLNode*)"))
    UI.addWidgetWithToolTipAndLabel(UI.outputSelector,{"tip":"Pick the output to the algorithm.","label":"Output volume"})

    UI.output = UI.outputSelector.currentNode()
    
    #
    # LabelMap toggle
    #
    outputLabelMapLabel = qt.QLabel("LabelMap: ")
    UI.widgets.append(outputLabelMapLabel)

    UI.outputLabelMapBox = qt.QCheckBox()
    UI.widgets.append(UI.outputLabelMapBox)
    UI.outputLabelMapBox.setToolTip("Output Volume is set as a labelmap")
    UI.outputLabelMapBox.setChecked(UI.outputLabelMap)
    UI.outputLabelMapBox.setDisabled(True)

    UI.outputLabelMapBox.connect("stateChanged(int)", lambda val:UI.onOutputLabelMapChanged(bool(val)))
    UI.widgetConnections.append((UI.outputLabelMapBox, "stateChanged(int)"))
    # add to layout after connection
    parametersFormLayout.addRow(outputLabelMapLabel, UI.outputLabelMapBox)

    self.UI = UI
    return UI
  
  def onFloatValueChanged(self,name,widget,val):
    if name == "above_val":
      self.above_val = val
    elif name == "bellow_val":
      self.bellow_val = val

  def onFloatVectorChanged(self, name, widget, val):
    coords = [float(x) for x in widget.coordinates.split(',')]
    if name == "out_range":
      self.out_range = sorted(coords)
      if(self.UI):
        self.UI.bellow_value_widget.minimum = coords[0]
        self.UI.bellow_value_widget.maximum = coords[1]
        
        self.UI.above_value_widget.minimum = coords[0]
        self.UI.above_value_widget.maximum = coords[1]
      
      
  def onRangeChanged(self, name, widget, min_val, max_val):
    if name == "clip":
      self.clip = [min_val,max_val]
    if name == "threshold":
      self.threshold = [min_val,max_val]
    
  def onEnumChanged(self,name,index,widget):
    data = widget.itemData(index)
    text = widget.itemText(index)
    if name == "out_dtype":
      self.out_dtype = data

      if "int" in text:  
        if text=="uint8_t":
          self.ui_set_dtype(True,0,255)
        elif text=="int8_t":
          self.ui_set_dtype(True,-128,127)
        elif text=="uint16_t":
          self.ui_set_dtype(True,0,65535)
        elif text=="int16_t":
          self.ui_set_dtype(True,-32678,32767)
        elif text=="uint32_t" or text=="unsigned int":
          self.ui_set_dtype(True,0,2147483647)
        elif text=="int32_t" or text=="int":
          self.ui_set_dtype(True,-2147483648, 2147483647)
      else:
        self.ui_set_dtype(False,-3.40282e+038, 3.40282e+038)

  def ui_set_dtype(self,is_int, min_val, max_val):
    if self.UI:
      self.UI.out_range_widget.toolTip = f"Set the desired output data range (on the [{min_val},{max_val}] range)"
      
      self.UI.out_range_widget.minimum = min_val
      self.UI.out_range_widget.maximum = max_val
      
      self.UI.bellow_value_widget.minimum = min_val
      self.UI.bellow_value_widget.maximum = max_val
      
      self.UI.above_value_widget.minimum = min_val
      self.UI.above_value_widget.maximum = max_val
      
      if is_int:
        self.UI.out_range_widget.decimals = 0
        self.UI.out_range_widget.singleStep = 1
        
        self.UI.bellow_value_widget.decimals = 0
        self.UI.bellow_value_widget.singleStep = 1
        
        self.UI.above_value_widget.decimals = 0
        self.UI.above_value_widget.singleStep = 1
      
      else:
        self.UI.out_range_widget.decimals = 2
        self.UI.out_range_widget.singleStep = 1.0
        
        self.UI.bellow_value_widget.decimals = 2
        self.UI.bellow_value_widget.singleStep = 1.0
        
        self.UI.above_value_widget.decimals = 2
        self.UI.above_value_widget.singleStep = 1.0
        
      
  
  def analyze_image(self):    
    # load image
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      self.UI.out_range_widget.enabled = False
      self.UI.clip_widget.enabled = False
      self.UI.threshold_widget.enabled  = False
      self.UI.bellow_value_widget.enabled = False
      self.UI.above_value_widget.enabled = False
        
      raise ReferenceError("Inputs not initialized.")
  
    self.UI.out_range_widget.enabled = True
    self.UI.clip_widget.enabled = True
    self.UI.threshold_widget.enabled  = True
    self.UI.bellow_value_widget.enabled = True
    self.UI.above_value_widget.enabled = True
    
    
    input_img_node_name = self.UI.inputs[0].GetName()
    
    addOrUpdateHistogram(self, self.UI,self.UI.plot_container,input_image = self.UI.inputs[0])
    self.UI.plot_container.visible = True    
    
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    
    # print(reverse_lookup_dtype(sitk_img.GetPixelID()))
    # print(sitk_img.GetPixelID())
    # print(sitk_img.GetPixelIDValue())
    # print(sitk_img.GetPixelIDTypeAsString())
    
    
    dtype_index = reverse_lookup_dtype(sitk_img.GetPixelID(),True)
    if not isinstance(dtype_index,type(None)):
      self.UI.dtype_widget.setCurrentIndex(dtype_index)
      
    
    filter = sitk.MinimumMaximumImageFilter()
    filter.Execute(sitk_img)
    min_val = filter.GetMinimum()
    max_val = filter.GetMaximum()

    self.UI.clip_widget.minimum= min_val
    self.UI.clip_widget.minimumValue = min_val
    self.UI.clip_widget.maximum= max_val
    self.UI.clip_widget.maximumValue = max_val

    self.UI.threshold_widget.minimum= min_val
    self.UI.threshold_widget.minimumValue = min_val
    self.UI.threshold_widget.maximum= max_val
    self.UI.threshold_widget.maximumValue = max_val
    
    self.UI.out_range_widget.coordinates = ','.join([str(np.round(val,2)) for val in [min_val,max_val]])

  def execute(self, ui = None):
    super().execute(ui = ui)

    # load image
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      raise ReferenceError("Inputs not initialized.")
    input_img_node_name = self.UI.inputs[0].GetName()
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    # img = sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name)
    
    img_data = sitk.GetArrayFromImage(sitk_img)
        
    # clipping
    clipped_data = np.clip(img_data, a_min=self.clip[0],a_max=self.clip[1])
    
    # rescaling
    data_min = np.min(clipped_data)
    data_max = np.max(clipped_data)
    data_range = data_max-data_min
    out_range = self.out_range[1]-self.out_range[0]
    rescaled_data = (((clipped_data-data_min)/data_range)*out_range)+self.out_range[0]
    
    # replacing
    rescaled_data[img_data<self.threshold[0]] = self.bellow_val
    rescaled_data[img_data>self.threshold[1]] = self.above_val
    

    print("UI succesfully processed.")

    del(img_data)
    rescaled_image = sitk.GetImageFromArray(rescaled_data)
    rescaled_image.SetOrigin(sitk_img.GetOrigin())
    rescaled_image.SetDirection(sitk_img.GetDirection())
    rescaled_image.SetSpacing(sitk_img.GetSpacing())
    

    out_sitk_image = sitk.Cast(rescaled_image,self.out_dtype)

    
    del(rescaled_data)
    del(rescaled_image)
    
    print("Linear intensity transform done.")
    return out_sitk_image