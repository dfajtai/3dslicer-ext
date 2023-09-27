import numpy as np
import vtk
import qt
import ctk

import slicer


from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils

def block_reduce(image, block_size = 2, func = np.max, cval = 0, func_kwargs = None):
  """
  Downsample image by applying function `func` to local blocks.
  This function is useful for max and mean pooling, for example.
  https://github.com/scikit-image/scikit-image/blob/v0.21.0/skimage/measure/block.py
  
  Parameters
  ----------
  image : ndarray
    N-dimensional input image.
  block_size : array_like or int
    Array containing down-sampling integer factor along each axis.
    Default block_size is 2.
  func : callable
    Function object which is used to calculate the return value for each
    local block. This function must implement an ``axis`` parameter.
    Primary functions are ``numpy.sum``, ``numpy.min``, ``numpy.max``,
    ``numpy.mean`` and ``numpy.median``.  See also `func_kwargs`.
  cval : float
    Constant padding value if image is not perfectly divisible by the
    block size.
  func_kwargs : dict
    Keyword arguments passed to `func`. Notably useful for passing dtype
    argument to ``np.mean``. Takes dictionary of inputs, e.g.:
    ``func_kwargs={'dtype': np.float16})``.

  Returns
  -------
  image : ndarray
    Down-sampled image with same number of dimensions as input image.
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


def view_as_blocks(arr_in, block_shape):
  """
  Block view of the input n-dimensional array (using re-striding).
  Blocks are non-overlapping views of the input array.

  https://github.com/scikit-image/scikit-image/blob/v0.21.0/skimage/util/shape.py

  Parameters
  ----------
  arr_in : ndarray
    N-d input array.
  block_shape : tuple
    The shape of the block. Each dimension must divide evenly into the
    corresponding dimensions of `arr_in`.

  Returns
  -------
  arr_out : ndarray
    Block view of the input array.

  """
  if not isinstance(block_shape, tuple):
    raise TypeError('block needs to be a tuple')

  block_shape = np.array(block_shape)
  if (block_shape <= 0).any():
    raise ValueError("'block_shape' elements must be strictly positive")

  if block_shape.size != arr_in.ndim:
    raise ValueError("'block_shape' must have the same length "
             "as 'arr_in.shape'")

  arr_shape = np.array(arr_in.shape)
  if (arr_shape % block_shape).sum() != 0:
    raise ValueError("'block_shape' is not compatible with 'arr_in'")

  # -- restride the array to build the block view
  new_shape = tuple(arr_shape // block_shape) + tuple(block_shape)
  new_strides = tuple(arr_in.strides * block_shape) + arr_in.strides

  arr_out = as_strided(arr_in, shape=new_shape, strides=new_strides)

  return arr_out



class RankDownsampleFilter(CustomFilter):
  filter_name = "Rank Downsample Filter"
  short_description = "Perform downsampling on input volume by a given numyp function - eg: mean, min, max, median, std."
  tooltip = "Downsampling by local ranks."

  def __init__(self):
    super().__init__()
    self.filter_name = RankDownsampleFilter.filter_name
    self.short_description = RankDownsampleFilter.short_description
    self.tooltip = RankDownsampleFilter.tooltip

  def createUI(self, parent):
    self.parent = parent
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parent)

    # set default values
    UI.default_parameters["block_size"] = 2
    UI.default_parameters["downsampling_function"] = "max"

    # input node
    name = "Input Volume: "
    input_widget = UI.createInputWidget(0)
    inputSelectorLabel = qt.QLabel(name)
    UI.widgets.append(inputSelectorLabel)

    # add to layout after connection
    parametersFormLayout.addRow(inputSelectorLabel, input_widget)
    UI.inputs.append(input_widget.currentNode())


    # add members

    # block size
    block_size = UI.createIntWidget("block_size","uint8_t")
    UI.addWidgetWithToolTipAndLabel(block_size,{"tip":"Set desired block size. An NxNxN block will be used during downsampling.",
                          "label":"Block size (N)"})
    # block_size_label = qt.QLabel("Block size:")
    # UI.widgets.append(block_size_label)
    # parametersFormLayout.addRow(block_size_label,block_size)

    # functions
    labels = ["Minimum","Maximum","Mean","Median","Standard Deviation"]
    values = ["min","max","mean","median","std"]

    functions = UI.createEnumWidget("downsampling_function",enumList=labels,valueList=values)
    UI.addWidgetWithToolTipAndLabel(functions,{"tip":"Function called on disjunct local blocks to downsample the image.",
                           "label":"Downsapling function"})
    # functions_label = qt.QLabel("Rank function:")
    # UI.widgets.append(functions_label)
    # parametersFormLayout.addRow(functions_label,functions)


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