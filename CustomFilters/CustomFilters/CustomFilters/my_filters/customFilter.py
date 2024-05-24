import re

import vtk
import qt
import ctk

import slicer


# global sitk
# sitk = None
import SimpleITK as sitk

# global sitkUtils
# sitkUtils = None
import sitkUtils


class CustomFilterUI:
  """
  This class is also for managing the widgets for a filter.
  Based on:
  https://github.com/SimpleITK/SlicerSimpleFilters/blob/master/SimpleFilters/SimpleFilters.py#L545
  """

  # class-scope regular expression to help covert from CamelCase
  reCamelCase = re.compile('((?<=[a-z0-9])[A-Z]|(?!^)[A-Z](?=[a-z]))')

  def __init__(self, parent=None):
    self.parent = parent
    self.widgets = []
    self.widgetConnections = []
    self.inputs = []
    self.output = None

    self.parameters = {}
    self.default_parameters = {}

    # self.prerun_callbacks = []
    self.outputLabelMap = False

    self.outputSelector = None
    self.outputLabelMapBox = None

  def __del__(self):
    self.widgetConnections = []
    self.widgets = []

  def BeautifyCamelCase(self, str):
    return self.reCamelCase.sub(r' \1',str)
  
  def createInputWidget(self,n = 0, noneEnabled=False):
    inputSelector = slicer.qMRMLNodeComboBox()
    self.widgets.append(inputSelector)
    inputSelector.nodeTypes = ["vtkMRMLScalarVolumeNode", "vtkMRMLLabelMapVolumeNode"]
    inputSelector.selectNodeUponCreation = True
    inputSelector.addEnabled = False
    inputSelector.removeEnabled = False
    inputSelector.noneEnabled = noneEnabled
    inputSelector.showHidden = False
    inputSelector.showChildNodeTypes = False
    inputSelector.setMRMLScene( slicer.mrmlScene )
    inputSelector.setToolTip( "Pick the input to the algorithm." )

    # connect and verify parameters
    inputSelector.connect("nodeActivated(vtkMRMLNode*)", lambda node,i=n:self.onInputSelect(node,i))
    self.widgetConnections.append((inputSelector, "nodeActivated(vtkMRMLNode*)"))
    return inputSelector

  def createEnumWidget(self,name,enumList,valueList=None):

    w = qt.QComboBox()
    self.widgets.append(w)

    default = self._getParameterValue(name)

    if valueList is None:
      valueList = ["self.filter."+e for e in enumList]


    def_val = self._getParameterValue(name)

    for e,v in zip(enumList,valueList):
      w.addItem(e,v)

      # # check if current item is default, set if it is
      # ldict = locals().copy()
      # exec('itemValue='+v, globals(), ldict)
      # if ldict['itemValue'] == default:
      #   w.setCurrentIndex(w.count-1)
      if v == def_val:
        w.setCurrentIndex(w.count-1)


    w.connect("currentIndexChanged(int)", lambda selectorIndex,n=name,selector=w:self.onEnumChanged(n,selectorIndex,selector))
    self.widgetConnections.append((w, "currentIndexChanged(int)"))
    return w

  def createVectorWidget(self,name,type):
    m = re.search(r"<([a-zA-Z ]+)>", type)
    if m:
      type = m.group(1)

    w = ctk.ctkCoordinatesWidget()
    self.widgets.append(w)

    if type in ["double", "float"]:
      w.setDecimals(5)
      w.minimum=-3.40282e+038
      w.maximum=3.40282e+038
      w.connect("coordinatesChanged(double*)", lambda val,widget=w,name=name:self.onFloatVectorChanged(name,widget,val))
    elif type == "bool":
      w.setDecimals(0)
      w.minimum=0
      w.maximum=1
      w.connect("coordinatesChanged(double*)", lambda val,widget=w,name=name:self.onBoolVectorChanged(name,widget,val))
    else:
      w.setDecimals(0)
      w.connect("coordinatesChanged(double*)", lambda val,widget=w,name=name:self.onIntVectorChanged(name,widget,val))
    self.widgetConnections.append((w, "coordinatesChanged(double*)"))

    default = self._getParameterValue(name)
    w.coordinates = ",".join(str(x) for x in default)
    return w

  def createIntWidget(self,name,type="int"):

    w = qt.QSpinBox()
    self.widgets.append(w)

    if type=="uint8_t":
      w.setRange(0,255)
    elif type=="int8_t":
      w.setRange(-128,127)
    elif type=="uint16_t":
      w.setRange(0,65535)
    elif type=="int16_t":
      w.setRange(-32678,32767)
    elif type=="uint32_t" or type=="unsigned int":
      w.setRange(0,2147483647)
    elif type=="int32_t" or type=="int":
      w.setRange(-2147483648,2147483647)

    w.setValue(int(self._getParameterValue(name)))
    w.connect("valueChanged(int)", lambda val,name=name:self.onScalarChanged(name,val))
    self.widgetConnections.append((w, "valueChanged(int)"))
    return w

  
  def createLargeIntWidget(self,name):
    w = qt.QLineEdit()
    self.widgets.append(w)
    validator = qt.QRegExpValidator(qt.QRegExp(r'[0-9-]{0,20}'), w)
    w.setValidator(validator)
    w.setText(self._getParameterValue(name))
    w.connect("textChanged(QString)", lambda val,name=name:self.onScalarChanged(name,int(val)))
    self.widgetConnections.append((w, "textChanged(QString)"))
    return w

  def createBoolWidget(self,name):
    w = qt.QCheckBox()
    self.widgets.append(w)

    w.setChecked(self._getParameterValue(name))

    w.connect("stateChanged(int)", lambda val,name=name:self.onScalarChanged(name,bool(val)))
    self.widgetConnections.append((w, "stateChanged(int)"))

    return w

  def _getParameterValue(self, parameterName, set_default = True):
    # ldict = locals().copy()
    # exec(f'default = self.filter.Get{parameterName}()', globals(), ldict)
    # return ldict['default']
    if parameterName in self.parameters:
      return self.parameters.get(parameterName)
    val = self.default_parameters.get(parameterName)
    if set_default:
      self.parameters[parameterName] = val
    return val

  def createDoubleWidget(self,name):

    w = qt.QDoubleSpinBox()
    self.widgets.append(w)

    w.setRange(-3.40282e+038, 3.40282e+038)
    w.decimals = 5

    w.setValue(self._getParameterValue(name))
    w.connect("valueChanged(double)", lambda val,name=name:self.onScalarChanged(name,val))
    self.widgetConnections.append((w, "valueChanged(double)"))

    return w

  def addWidgetWithToolTipAndLabel(self,widget,tip_label_dict):
    tip=""
    if "tip" in tip_label_dict and len(tip_label_dict["tip"]):
      tip=tip_label_dict["tip"]


    # remove trailing white space
    tip=tip.rstrip()

    l = qt.QLabel(self.BeautifyCamelCase(tip_label_dict["label"])+": ")
    self.widgets.append(l)

    widget.setToolTip(tip)
    l.setToolTip(tip)

    parametersFormLayout = self.parent.layout()
    parametersFormLayout.addRow(l,widget)
    
  def addWidgetWithToolTip(self,widget, tip_label_dict):
    tip=""
    if "tip" in tip_label_dict and len(tip_label_dict["tip"]):
      tip=tip_label_dict["tip"]

    # remove trailing white space
    tip=tip.rstrip()
    
    widget.setToolTip(tip)
    parametersFormLayout = self.parent.layout()
    parametersFormLayout.addRow(widget)
    
        

  def onToggledPointSelector(self, fidVisible, ptWidget, fiducialWidget):
    ptWidget.setVisible(False)
    fiducialWidget.setVisible(False)

    ptWidget.setVisible(not fidVisible)
    fiducialWidget.setVisible(fidVisible)

    if ptWidget.visible:
      # Update the coordinate values to envoke the changed signal.
      # This will update the filter from the widget
      ptWidget.coordinates = ",".join(str(x) for x in ptWidget.coordinates.split(',') )

  def onInputSelect(self, mrmlNode, n):
    self.inputs[n] = mrmlNode

  def onOutputSelect(self, mrmlNode):
    self.output = mrmlNode
    self.onOutputLabelMapChanged(mrmlNode.IsA("vtkMRMLLabelMapVolumeNode"))

  def onOutputLabelMapChanged(self, v):
    self.outputLabelMap = v
    self.outputLabelMapBox.setChecked(v)

  def onFiducialNode(self, name, mrmlWidget, isPoint):
    if not mrmlWidget.visible:
      return
    annotationFiducialNode = mrmlWidget.currentNode()

    # point in physical space
    coord = [0,0,0]

    if annotationFiducialNode.GetClassName() == "vtkMRMLMarkupsFiducialNode":
      # slicer4 Markups node
      if annotationFiducialNode.GetNumberOfFiducials() < 1:
        return
      annotationFiducialNode.GetNthFiducialPosition(0, coord)
    else:
      annotationFiducialNode.GetFiducialCoordinates(coord)

    # HACK transform from RAS to LPS
    coord = [-coord[0],-coord[1],coord[2]]

    # FIXME: we should not need to copy the image
    if not isPoint and len(self.inputs) and self.inputs[0]:
      imgNodeName = self.inputs[0].GetName()
      img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(imgNodeName) )
      coord = img.TransformPhysicalPointToIndex(coord)
    exec(f'self.filter.Set{name}(coord)')

  def onFiducialListNode(self, name, mrmlNode):
    annotationHierarchyNode = mrmlNode

    # list of points in physical space
    coords = []

    if annotationHierarchyNode.GetClassName() == "vtkMRMLMarkupsFiducialNode":
      # slicer4 Markups node

      for i in range(annotationHierarchyNode.GetNumberOfFiducials()):
        coord = [0,0,0]
        annotationHierarchyNode.GetNthFiducialPosition(i, coord)
        coords.append(coord)
    else:
      # slicer4 style hierarchy nodes

      # get the first in the list
      for listIndex in range(annotationHierarchyNode.GetNumberOfChildrenNodes()):
        if annotationHierarchyNode.GetNthChildNode(listIndex) is None:
          continue

        annotation = annotationHierarchyNode.GetNthChildNode(listIndex).GetAssociatedNode()
        if annotation is None:
          continue

        coord = [0,0,0]
        annotation.GetFiducialCoordinates(coord)
        coords.append(coord)

    if self.inputs[0]:
      imgNodeName = self.inputs[0].GetName()
      img = sitk.ReadImage(sitkUtils.GetSlicerITKReadWriteAddress(imgNodeName) )

      # HACK transform from RAS to LPS
      coords = [ [-pt[0],-pt[1],pt[2]] for pt in coords]

      idx_coords = [img.TransformPhysicalPointToIndex(pt) for pt in coords]

      exec(f'self.filter.Set{name}(idx_coords)')

  def onScalarChanged(self, name, val):
    # exec(f'self.filter.Set{name}(val)')
    self.parameters[name] = val

  def onEnumChanged(self, name, selectorIndex, selector):
    data=selector.itemData(selectorIndex)
    # exec(f'self.filter.Set{name}({data})')
    self.parameters[name] = data

  def onBoolVectorChanged(self, name, widget, val):
    coords = [bool(float(x)) for x in widget.coordinates.split(',')]
    # exec(f'self.filter.Set{name}(coords)')
    self.parameters[name] = coords

  def onIntVectorChanged(self, name, widget, val):
    coords = [int(float(x)) for x in widget.coordinates.split(',')]
    # exec(f'self.filter.Set{name}(coords)')
    self.parameters[name] = coords

  def onFloatVectorChanged(self, name, widget, val):
    coords = [float(x) for x in widget.coordinates.split(',')]
    # exec(f'self.filter.Set{name}(coords)')
    self.parameters[name] = coords
  
  def prerun(self):
    for f in self.prerun_callbacks:
      f()

  def destroy(self):
    # print("Filter UI destory called")
    try:     
      for widget, sig in self.widgetConnections:
        widget.disconnect(sig)
      self.widgetConnections = []
            
      for w in self.widgets:        
        self.parent.layout().removeWidget(w)
        w.deleteLater()
        w.setParent(None)    
      
      self.widgets = []
      self.parameters = {}
      
      self.inputs = []
      self.output = None
      
      # flush_data = getattr(self, "flush_data", None)
      # if callable(flush_data):
      #   self.flush_data()
        
      
    except Exception as e:
      print(e)
      
      

class CustomFilter:
  """ 
  This class is a superclass for custom defined filters
  """

  def __init__(self, filter_name = "", short_description = "", tooltip = ""):
    self.filter_name = filter_name
    self.short_description = short_description
    self.tooltip = tooltip
    self.parent = None
    self.UI = None

  def execute(self, ui = None):
    """
    Read input from UI, then execute the filter.
    """
    if not isinstance(ui,type(None)):
      self.UI = ui

    if not isinstance(self.UI,CustomFilterUI):
      raise "no UI initialized"

    # extract all paramterers
    for param in self.UI.default_parameters.keys():
      self.UI._getParameterValue(param)

  def createUI(self,parent):
    """
    Create/initialize UI inside a parent UI element by the CustomFilterUI class.
    The result should be a CustomFilterUI typen object stored in 'self.UI'.
    The logic is based on:
    https://github.com/SimpleITK/SlicerSimpleFilters/blob/master/SimpleFilters/SimpleFilters.py#L573
    """
    self.parent = parent
    
    if not self.parent:
      raise "no parent"
    
    parametersFormLayout = self.parent.layout()
    return parametersFormLayout
  
  def destroy(self):
    # print("Filter destory called")
    pass