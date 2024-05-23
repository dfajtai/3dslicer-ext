import numpy as np
import vtk
import qt
import ctk

import slicer


from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils
from .myPlotter import addOrUpdateHistogram


class AutocropFilter(CustomFilter):
  filter_name = "Autocrop Filter"
  short_description = "Perform automatic cropping on an image."
  tooltip = "Autocrop filter."

  def __init__(self):
    super().__init__()
    self.filter_name = AutocropFilter.filter_name
    self.short_description = AutocropFilter.short_description
    self.tooltip = AutocropFilter.tooltip  

    self.border = [0,0,0]
    
    self.threshold = [None,None]
    
  
    self.sitk_img = None
    

  def createUI(self, parent):
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parametersFormLayout)

    slicer.modules.CustomFiltersWidget.setFooterVisibility(True)

    # set default values
    
    UI.default_parameters["border"] = [0, 0, 0]
    
    UI.default_parameters["clip"] =  [0, 100]
    
    UI.default_parameters["threshold"] =  [0, 100]
    UI.default_parameters["clean_radius"] = 0
    
    
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
    
    # # threshold widget    
    UI.threshold_widget = ctk.ctkRangeWidget()
    UI.widgets.append(UI.threshold_widget)
    UI.addWidgetWithToolTipAndLabel(UI.threshold_widget,{"tip":"Values outside the 'threshold range' will be set to the given values",
                      "label":"Input threshold range"})
    
    UI.threshold_widget.connect("valuesChanged(double,double)",
                                lambda min,max, widget=UI.threshold_widget, name = 'threshold': self.onRangeChanged(name,widget,min,max))
    UI.widgetConnections.append((UI.threshold_widget, 'valuesChanged(double,double)'))
    
    
    
    # radius
    UI.clean_radius_widget = UI.createIntWidget("clean_radius","uint8_t")
    UI.addWidgetWithToolTipAndLabel(UI.clean_radius_widget,{"tip":"Set cleaning filter radius.",
                          "label":"Clean filter radius (N)"})
    UI.clean_radius_widget.minimum = 0
    
    
    # border widget
    UI.border_widget = ctk.ctkCoordinatesWidget()
    UI.widgets.append(UI.border_widget)
    UI.addWidgetWithToolTipAndLabel(UI.border_widget,{"tip":"Set the border",
                      "label":"Border"})
    UI.border_widget.dimension = 3
    UI.border_widget.minimum = 0
    UI.border_widget.decimals = 0
    UI.border_widget.enabled = True
    UI.border_widget.connect("coordinatesChanged(double*)",
                                lambda val, widget=UI.border_widget, name = 'border': self.onFloatVectorChanged(name,widget,val))
    UI.border_widget.coordinates = ','.join([str(int(np.round(val,0))) for val in UI.default_parameters["border"]])
    UI.widgetConnections.append((UI.border_widget, 'coordinatesChanged(double*)'))
        
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
    coords = [int(x) for x in widget.coordinates.split(',')]
    if name == "border":
      self.border = coords
      
      
  def onRangeChanged(self, name, widget, min_val, max_val):
    if name == "clip":
      self.clip = [min_val,max_val]
    if name == "threshold":
      self.threshold = [min_val,max_val]
          

  def analyze_image(self):
    # load image
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      raise ReferenceError("Inputs not initialized.")
    input_img_node_name = self.UI.inputs[0].GetName()
    
    addOrUpdateHistogram(self, self.UI,self.UI.plot_container,input_image = self.UI.inputs[0])
    self.UI.plot_container.visible = True
     
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
        
    filter = sitk.MinimumMaximumImageFilter()
    filter.Execute(sitk_img)
    min_val = filter.GetMinimum()
    max_val = filter.GetMaximum()

    self.UI.threshold_widget.minimum= min_val
    self.UI.threshold_widget.minimumValue = min_val
    self.UI.threshold_widget.maximum= max_val
    self.UI.threshold_widget.maximumValue = max_val
  
  def execute(self, ui = None):
    super().execute(ui = ui)

    # load image
    if isinstance(self.UI.inputs[0],type(None)):
      print("Please select an input volume.")
      raise ReferenceError("Inputs not initialized.")
    input_img_node_name = self.UI.inputs[0].GetName()
    sitk_img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name))
    # img = sitkUtils.GetSlicerITKReadWriteAddress(input_img_node_name)
    
    mask_img = sitk.BinaryThreshold(sitk_img,self.threshold[0],self.threshold[1],1,0)
    if self.UI.parameters.get("clean_radius"):
      mask_img = sitk.BinaryMorphologicalOpening(mask_img,[int(self.UI.parameters.get("clean_radius"))]*3)
    

    labelstat_filter = sitk.LabelShapeStatisticsImageFilter()
    labelstat_filter.Execute(mask_img)
    if labelstat_filter.GetNumberOfLabels() == 0:
      raise ValueError("Auto cropping with the given parameters resulted an empty mask.")
    bbox = labelstat_filter.GetBoundingBox(1)

    xmin = bbox[0]
    ymin = bbox[1]
    zmin = bbox[2]
    
    xmax = xmin + bbox[3]
    ymax = ymin + bbox[4]
    zmax = zmin + bbox[5]
    
    orig_shape = sitk_img.GetSize()
    border = self.border
    
    # extend    
    xmin = max(0,xmin-border[0])
    ymin = max(0,ymin-border[1])
    zmin = max(0,zmin-border[2])

    xmax = min(orig_shape[0],xmax+border[0])
    ymax = min(orig_shape[1],ymax+border[1])
    zmax = min(orig_shape[2],zmax+border[2])
    
    
    cropped_image = sitk_img[xmin:xmax+1,ymin:ymax+1,zmin:zmax+1]
    
    del(mask_img)
    
    print("Autocropping done.")
    return cropped_image