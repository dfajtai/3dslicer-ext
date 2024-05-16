import numpy as np
import vtk
import qt
import ctk

import slicer


from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils

def intensity_rescale_transform(image, clip, out_range, out_dtype, func_kwargs = None):
  """
  
  """

  if np.isscalar(block_size):
    block_size = (block_size,) * image.ndim
  elif len(block_size) != image.ndim:
    raise ValueError("`block_size` must be a scalar or have "
             "the same length as `image.shape`")

  if func_kwargs is None:
    func_kwargs = {}

  pad_width = []
  for i in range(len(block_size)):
    if block_size[i] < 1:
      raise ValueError("Down-sampling factors must be >= 1. Use "
               "`skimage.transform.resize` to up-sample an "
               "image.")
    if image.shape[i] % block_size[i] != 0:
      after_width = block_size[i] - (image.shape[i] % block_size[i])
    else:
      after_width = 0
    pad_width.append((0, after_width))

  image = np.pad(image, pad_width=pad_width, mode='constant',
           constant_values=cval)

  blocked = view_as_blocks(image, block_size)

  return func(blocked, axis=tuple(range(image.ndim, blocked.ndim)),
        **func_kwargs)


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
    

  def createUI(self, parent):
    self.parent = parent
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parent)

    # set default values
    
    UI.default_parameters["out_range"] = [0, 255]
    UI.default_parameters["out_dtype"] = "sitk.sitkUInt8"
    
    UI.default_parameters["clip"] =  [0, 100]
    
    UI.default_parameters["threshold"] =  [0, 100]
    
    UI.default_parameters["bellow_val"] =  0
    UI.default_parameters["above_val"] = 100
    UI.default_parameters["invert"] = False

    
    # input node
    
    name = "Input Volume: "
    input_widget = UI.createInputWidget(0)
    inputSelectorLabel = qt.QLabel(name)
    UI.widgets.append(inputSelectorLabel)

    # add to layout after connection
    parametersFormLayout.addRow(inputSelectorLabel, input_widget)
    UI.inputs.append(input_widget.currentNode())

    analyze_image_button = qt.QPushButton("Analyze image")
    # UI.widgets.append(analyze_image_button)
    
    UI.addWidgetWithToolTip(analyze_image_button,{"tip":"Analyze input image"})
    analyze_image_button.connect('clicked(bool)', self.analyze_image)
    
    
    # clip widget    
    UI.clip_widget = ctk.ctkRangeWidget()
    UI.widgets.append(UI.clip_widget)
    
    UI.addWidgetWithToolTipAndLabel(UI.clip_widget,{"tip":"Values outside the 'clip range' will be set to the given 'clip range'",
                      "label":"Input clip range"})
    UI.clip_widget.enabled = False
    
    UI.clip_widget.connect("valuesChanged(double,double)",
                                lambda min,max, widget=UI.clip_widget, name = 'clip': self.onRangeChanged(name,widget,min,max))
    
    
    # threshold widget    
    UI.threshold_widget = ctk.ctkRangeWidget()
    UI.widgets.append(UI.threshold_widget)
    UI.addWidgetWithToolTipAndLabel(UI.threshold_widget,{"tip":"Values outside the 'threshold range' will be set to the given values",
                      "label":"Input threshold range"})
    UI.threshold_widget.enabled = False
    
    UI.threshold_widget.connect("valuesChanged(double,double)",
                                lambda min,max, widget=UI.threshold_widget, name = 'threshold': self.onRangeChanged(name,widget,min,max))
    
    
    
    # bellow value
    UI.bellow_value_widget = qt.QDoubleSpinBox()
    UI.widgets.append(UI.bellow_value_widget)
    UI.addWidgetWithToolTipAndLabel(UI.bellow_value_widget,{"tip":"Values bellow the 'threshold range' will be set to this value in the output image - if it is safe to...",
                      "label":"Bellow thr. value"})
    UI.bellow_value_widget.enabled = False
    UI.bellow_value_widget.value =  UI.default_parameters["bellow_val"]
    UI.bellow_value_widget.connect("valueChanged(double)",
                                lambda val, widget=UI.bellow_value_widget, name = 'bellow_val': self.onFloatValueChanged(name,widget,val))
    
    # above value
    UI.above_value_widget = qt.QDoubleSpinBox()
    UI.widgets.append(UI.above_value_widget)
    UI.addWidgetWithToolTipAndLabel(UI.above_value_widget,{"tip":"Values above the 'threshold range' will be set to this value in the output image - if it is safe to...",
                      "label":"Above thr. value"})
    UI.above_value_widget.enabled = False
    UI.above_value_widget.value =  UI.default_parameters["above_val"]
    UI.above_value_widget.connect("valueChanged(double)",
                                lambda val, widget=UI.above_value_widget, name = 'above_val': self.onFloatValueChanged(name,widget,val))
    
    
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
    
    
    # out dtype
    
    labels=["int8_t",
                "uint8_t",
                "int16_t",
                "uint16_t",
                "uint32_t",
                "int32_t",
                "float",
                "double"]
    values=["sitk.sitkInt8",
                "sitk.sitkUInt8",
                "sitk.sitkInt16",
                "sitk.sitkUInt16",
                "sitk.sitkInt32",
                "sitk.sitkUInt32",
                "sitk.sitkFloat32",
                "sitk.sitkFloat64"]
    
    UI.dtype_widget = qt.QComboBox()
    UI.widgets.append(UI.dtype_widget)
    for l,v in zip(labels,values):
      UI.dtype_widget.addItem(l,v)
      if v == UI.default_parameters["out_dtype"]:
        UI.dtype_widget.setCurrentIndex(UI.dtype_widget.count-1)
        self.onEnumChanged("out_dtype",UI.dtype_widget.count-1,UI.dtype_widget)
          
    UI.addWidgetWithToolTipAndLabel(UI.dtype_widget,{"tip":"Output image data type",
                  "label":"Out data type"})
  
    UI.dtype_widget.connect("currentIndexChanged(int)", 
                            lambda selectorIndex,name="out_dtype",selector=UI.dtype_widget:self.onEnumChanged(name,selectorIndex,selector))

  
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


    # add to layout after connection
    parametersFormLayout.addRow(outputSelectorLabel, UI.outputSelector)

    UI.output = UI.outputSelector.currentNode()


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
      self.out_range = coords
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
    
    self.UI.out_range_widget.enabled = True
    self.UI.clip_widget.enabled = True
    self.UI.threshold_widget.enabled  = True
    self.UI.bellow_value_widget.enabled = True
    self.UI.above_value_widget.enabled = True
    
    pass
    

  def execute(self, ui = None):
    super().execute(ui = ui)

    # handle UI

    # load image
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      raise ReferenceError("Inputs not initialized.")
    input_img_node_name = self.UI.inputs[0].GetName()
    img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    # img = sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name)
    
    # retrieve block size
    block_size = self.UI.parameters.get("block_size")
    if isinstance(block_size,type(None)):
      print(f"Invalid block size: '{block_size}'")
      raise ReferenceError("Invalid block size.")
    block_size = int(block_size)

    # retrieve downsampling function
    selected_function_name = self.UI.parameters.get("downsampling_function")
    func_dict = {"min":np.min,"max":np.max,"mean":np.mean,"std":np.std,"median":np.median}
    selected_function = func_dict.get(selected_function_name)

    if not callable(selected_function):
      print(f"Invalid downsampling function: '{selected_function}'")
      raise ReferenceError("Invalid downsampling function.")

    print("UI succesfully processed.")

    image_data = sitk.GetArrayFromImage(img)
    downsampled_image_data = block_reduce(image=image_data,
                                          block_size= block_size,
                                          func=selected_function,
                                          cval = np.min(image_data))
    del(image_data)
    downsampled_spacing = (np.array(img.GetSpacing())*float(block_size)).flatten().tolist()
    downsampled_image = sitk.GetImageFromArray(downsampled_image_data)
    downsampled_image.SetOrigin(img.GetOrigin())
    downsampled_image.SetDirection(img.GetDirection())
    downsampled_image.SetSpacing(downsampled_spacing)
    
    print("Downsampling done.")
    return downsampled_image