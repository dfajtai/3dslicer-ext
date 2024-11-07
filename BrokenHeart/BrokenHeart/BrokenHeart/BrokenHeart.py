import logging
import os

import vtk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

import SegmentStatistics

from collections import OrderedDict

import numpy as np
import math
import SimpleITK as sitk
import sitkUtils

#
# BrokenHeart
#





class BrokenHeart(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "BrokenHeart"  # TODO: make this more human readable by adding spaces
        self.parent.categories = ["Segmentation"]  # TODO: set categories (folders where the module shows up in the module selector)
        self.parent.dependencies = []  # TODO: add here list of module names that this module requires
        self.parent.contributors = ["Daniel Fajtai"]  # TODO: replace with "Firstname Lastname (Organization)"
        # TODO: update with short description of the module and a link to online module documentation
        self.parent.helpText = """This is a rather simple module to aid heart ct segmentation."""
        # TODO: replace with organization, grant and thanks
        self.parent.acknowledgementText = """"""

        # Additional initialization step after application startup is complete
        slicer.app.connect("startupCompleted()", registerSampleData)


#
# Register sample data sets in Sample Data module
#

def registerSampleData():
  """
  Add data sets to Sample Data module.
  """
  # It is always recommended to provide sample data for users to make it easy to try the module,
  # but if no sample data is available then this method (and associated startupCompeted signal connection) can be removed.

  import SampleData
  iconsPath = os.path.join(os.path.dirname(__file__), 'Resources/Icons')
  print("Sample for 'BrokenHeart' is not implemented")


#
# BrokenHeartWidget
#

class BrokenHeartWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False

    def setup(self):
        """
        Called when the user opens the module the first time and the widget is initialized.
        """
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/BrokenHeart.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = BrokenHeartLogic()

        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
        # (in the selected parameter node).
        self.ui.input_vol.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        self.ui.input_seg.connect("currentNodeChanged(vtkMRMLNode*)", self.updateParameterNodeFromGUI)
        
        self.ui.slider_fix_thr.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        self.ui.slider_multi_otsu.connect("valueChanged(double)", self.updateParameterNodeFromGUI)
        
        self.ui.cb_fix_thr.connect("toggled(bool)", self.updateParameterNodeFromGUI)
        self.ui.cb_otsu.connect("toggled(bool)", self.updateParameterNodeFromGUI)
        self.ui.cb_triangle.connect("toggled(bool)", self.updateParameterNodeFromGUI)
        self.ui.cb_multi_otsu.connect("toggled(bool)", self.updateParameterNodeFromGUI)

        # Buttons
        self.ui.applyButton.connect('clicked(bool)', self.onApplyButton)
        self.ui.btn_remove_results.connect('clicked(bool)', self.onFlushResultsButton)
        self.ui.btn_refresh.connect('clicked(bool)', self.onRefreshButton)

        self.ui.btn_fix_stat.connect('clicked(bool)', self.on_btn_fix_stat)
        self.ui.btn_multi_stat.connect('clicked(bool)', self.on_btn_multi_stat)
        self.ui.btn_otsu_stat.connect('clicked(bool)', self.on_btn_otsu_stat)
        self.ui.btn_triangle_stat.connect('clicked(bool)', self.on_btn_triangle_stat)

        self.ui.btn_fix_view.connect('clicked(bool)', self.on_btn_fix_view)
        self.ui.btn_multi_view.connect('clicked(bool)', self.on_btn_multi_view)
        self.ui.btn_otsu_view.connect('clicked(bool)', self.on_btn_otsu_view)
        self.ui.btn_triangle_view.connect('clicked(bool)', self.on_btn_triangle_view)
    

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

    def cleanup(self):
        """
        Called when the application closes and the module widget is destroyed.
        """
        self.logic.empty_data()
        self.removeObservers()

    def enter(self):
        """
        Called each time the user opens this module.
        """
        # Make sure parameter node exists and observed
        self.initializeParameterNode()

    def exit(self):
        """
        Called each time the user opens a different module.
        """
        # Do not react to parameter node changes (GUI wlil be updated when the user enters into the module)
        self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

    def onSceneStartClose(self, caller, event):
        """
        Called just before the scene is closed.
        """
        # Parameter node will be reset, do not use it anymore
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event):
        """
        Called just after the scene is closed.
        """
        # If this module is shown while the scene is closed then recreate a new parameter node immediately
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self):
        """
        Ensure parameter node exists and observed.
        """
        # Parameter node stores all user choices in parameter values, node selections, etc.
        # so that when the scene is saved and reloaded, these settings are restored.

        self.setParameterNode(self.logic.getParameterNode())
               

        # Select default input nodes if nothing is selected yet to save a few clicks for the user
        if not self._parameterNode.GetNodeReference("input_vol"):
            lastVolumeNode = list(slicer.util.getNodes('vtkMRMLScalarVolumeNode*').values())
            if len(lastVolumeNode)>0:
                ids = sorted([n.GetID() for n in lastVolumeNode])
                self._parameterNode.SetNodeReferenceID("input_vol", ids[-1])
                
        
        # Select default input nodes if nothing is selected yet to save a few clicks for the user
        if not self._parameterNode.GetNodeReference("input_seg"):
            lastNode =list(slicer.util.getNodes('vtkMRMLSegmentationNode*').values())
            if len(lastNode)>0:
                
                ids = sorted([n.GetID() for n in lastNode])
                self._parameterNode.SetNodeReferenceID("input_seg", ids[-1])
                
                segmentation_node = slicer.mrmlScene.GetNodeByID(ids[-1])
                segmentation = segmentation_node.GetSegmentation()

                lv_id = segmentation.GetSegmentIdBySegmentName("LV")
                if lv_id!='':
                    self.ui.input_seg.setCurrentSegmentID(lv_id)
                else:
                    self.ui.input_seg.setCurrentSegmentID(segmentation.GetNthSegmentID(0))

                self._parameterNode.SetParameter("seg_id", str(self.ui.input_seg.currentSegmentID()))
                

    def setParameterNode(self, inputParameterNode):
        """
        Set and observe parameter node.
        Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
        """

        if inputParameterNode:
            self.logic.setDefaultParameters(inputParameterNode)

        # Unobserve previously selected parameter node and add an observer to the newly selected.
        # Changes of parameter node are observed so that whenever parameters are changed by a script or any other module
        # those are reflected immediately in the GUI.
        if self._parameterNode is not None and self.hasObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode):
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)
        self._parameterNode = inputParameterNode
                
        if self._parameterNode is not None:
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromParameterNode)

        # Initial GUI update
        self.updateGUIFromParameterNode()
        
    def updateGUIFromParameterNode(self, caller=None, event=None):
        """
        This method is called whenever parameter node is changed.
        The module GUI is updated to show the current state of the parameter node.
        """

        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return
        
        # Make sure GUI changes do not call updateParameterNodeFromGUI (it could cause infinite loop)
        self._updatingGUIFromParameterNode = True

        # Update node selectors and sliders
        self.ui.input_vol.setCurrentNode(self._parameterNode.GetNodeReference("input_vol"))
        self.ui.input_seg.setCurrentNode(self._parameterNode.GetNodeReference("input_seg"))
        self.ui.input_seg.setCurrentSegmentID(self._parameterNode.GetParameter("seg_id"))

        self.ui.slider_fix_thr.value = float(self._parameterNode.GetParameter("fix_thr_val"))
        self.ui.slider_multi_otsu.value = int(float(self._parameterNode.GetParameter("multi_otsu_val")))
        
        self.ui.cb_fix_thr.checked = (self._parameterNode.GetParameter("fix_thr") == "true")
        self.ui.cb_otsu.checked = (self._parameterNode.GetParameter("otsu") == "true")
        self.ui.cb_triangle.checked = (self._parameterNode.GetParameter("triangle") == "true")
        self.ui.cb_multi_otsu.checked = (self._parameterNode.GetParameter("multi_otsu") == "true")

        # Update buttons states and tooltips
        if self._parameterNode.GetNodeReference("input_vol") and self._parameterNode.GetNodeReference("input_seg"):
            self.ui.applyButton.toolTip = "Compute segmentations"
            self.ui.applyButton.enabled = True
        else:
            self.ui.applyButton.toolTip = "Select input nodes"
            self.ui.applyButton.enabled = False

        # All the GUI updates are done
        self._updatingGUIFromParameterNode = False

    def updateParameterNodeFromGUI(self, caller=None, event=None):
        """
        This method is called when the user makes any change in the GUI.
        The changes are saved into the parameter node (so that they are restored when the scene is saved and loaded).
        """

        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return

        wasModified = self._parameterNode.StartModify()  # Modify all properties in a single batch

        self._parameterNode.SetNodeReferenceID("input_vol", self.ui.input_vol.currentNodeID)
        self._parameterNode.SetNodeReferenceID("input_seg", self.ui.input_seg.currentNodeID())
        self._parameterNode.SetParameter("seg_id", str(self.ui.input_seg.currentSegmentID()))
        self._parameterNode.SetParameter("fix_thr_val", str(self.ui.slider_fix_thr.value))
        self._parameterNode.SetParameter("multi_otsu_val", str(self.ui.slider_multi_otsu.value))
        
        self._parameterNode.SetParameter("fix_thr", "true" if self.ui.cb_fix_thr.checked else "false")
        self._parameterNode.SetParameter("otsu", "true" if self.ui.cb_otsu.checked else "false")
        self._parameterNode.SetParameter("triangle", "true" if self.ui.cb_triangle.checked else "false")
        self._parameterNode.SetParameter("multi_otsu", "true" if self.ui.cb_multi_otsu.checked else "false")
        

        self._parameterNode.EndModify(wasModified)
        
        self.logic.init_editor()
        
    
    def get_all_param(self):
        params = OrderedDict(input_vol = self._parameterNode.GetNodeReference('input_vol'),
                             input_segmentation = self._parameterNode.GetNodeReference('input_seg'),
                             seg_id = self._parameterNode.GetParameter('seg_id'),
                             
                             fix_thr_val = float(self._parameterNode.GetParameter("fix_thr_val")),
                             multi_otsu_val = int(float(self._parameterNode.GetParameter("multi_otsu_val"))),
                             
                             fix_thr = self._parameterNode.GetParameter("fix_thr") == "true",
                             otsu = self._parameterNode.GetParameter("otsu") == "true",
                             triangle = self._parameterNode.GetParameter("triangle") == "true",
                             multi_otsu = self._parameterNode.GetParameter("multi_otsu") == "true",
                             )
        return params
    

    def onApplyButton(self):
        """
        Run processing when user clicks "Apply" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):            
            self.logic.process(**self.get_all_param())
            self.ui.btn_remove_results.enabled = True
            
            
            

    def onFlushResultsButton(self):

        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.empty_data()
            self.ui.btn_remove_results.enabled = False
            
    def onRefreshButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self._parameterNode.SetNodeReferenceID("input_vol","")
            self._parameterNode.SetNodeReferenceID("input_seg","")
            self.initializeParameterNode()


    def on_btn_triangle_stat(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.stat_table("triangle")
    
    def on_btn_fix_stat(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.stat_table("fix")
    
    def on_btn_otsu_stat(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.stat_table("otsu")

    def on_btn_multi_stat(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.stat_table("multi_otsu")


    def on_btn_triangle_view(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.view_seg("triangle")
    
    def on_btn_fix_view(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.view_seg("fix")
    
    def on_btn_otsu_view(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.view_seg("otsu")

    def on_btn_multi_view(self):
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            self.logic.view_seg("multi_otsu")

#
# BrokenHeartLogic
#
def triangle_threshold(image_data):
    # Compute histogram
    hist, bins = np.histogram(image_data, bins=256, range=(0,256))
    hist = hist.astype(np.float32)
    
    # Find minima
    minima = np.zeros_like(hist)
    for i in range(1, len(hist) - 1):
        if hist[i] < hist[i - 1] and hist[i] < hist[i + 1]:
            minima[i] = hist[i]
    
    # Find maximum valley
    max_valley = np.argmax(minima)
    for i in range(max_valley, 0, -1):
        if minima[i] == 0:
            break
        max_valley = i
    
    # Threshold value is the intensity level corresponding to the minimum of the valley
    threshold_value = max_valley
    
    return threshold_value


def create_binary_images(input_image, mask_image, threshold_value):
    img_data = sitk.GetArrayFromImage(input_image)
    mask_data = sitk.GetArrayFromImage(mask_image)
    
    lower_mask = np.logical_and(img_data<threshold_value, mask_data == 1).astype("uint8")
    lower_image = sitk.GetImageFromArray(lower_mask)
    lower_image.SetOrigin(input_image.GetOrigin())
    lower_image.SetSpacing(input_image.GetSpacing())
    lower_image.SetDirection(input_image.GetDirection())
    
    upper_mask = np.logical_and(img_data>=threshold_value, mask_data == 1).astype("uint8")
    upper_image = sitk.GetImageFromArray(upper_mask)
    upper_image.SetOrigin(input_image.GetOrigin())
    upper_image.SetSpacing(input_image.GetSpacing())
    upper_image.SetDirection(input_image.GetDirection())
    
    return lower_image, upper_image



class BrokenHeartLogic(ScriptedLoadableModuleLogic):
    """This class should implement all the actual
    computation done by your module.  The interface
    should be such that other python code can import
    this class and make use of the functionality without
    requiring an instance of the Widget.
    Uses ScriptedLoadableModuleLogic base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self):
        """
        Called when the logic class is instantiated. Can be used for initializing member variables.
        """
        ScriptedLoadableModuleLogic.__init__(self)
        
        self.data = {}
        
        self.segmentEditorNode = None
        self.segmentEditorWidget = None
        
        
    def init_editor(self):
        if slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentEditorNode"):
            self.segmentEditorNode = slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentEditorNode")
            self.segmentEditorWidget = slicer.util.getModuleWidget('SegmentEditor').editor
                        
        
    def setDefaultParameters(self, parameterNode):
        """
        Initialize parameter node with default settings.
        """
            
        if not parameterNode.GetParameter("multi_otsu_val"):
            parameterNode.SetParameter("multi_otsu_val", "3")
        if not parameterNode.GetParameter("fix_thr_val"):
            parameterNode.SetParameter("fix_thr_val", "90")
        
        if not parameterNode.GetParameter("fix_thr"):
            parameterNode.SetParameter("fix_thr", "false")
        
        if not parameterNode.GetParameter("multi_otsu"):
            parameterNode.SetParameter("multi_otsu", "true")
        if not parameterNode.GetParameter("otsu"):
            parameterNode.SetParameter("otsu", "false")
        if not parameterNode.GetParameter("triangle"):
            parameterNode.SetParameter("triangle", "false")


    def process(self, input_vol, input_segmentation, seg_id,
                fix_thr_val, multi_otsu_val,
                fix_thr, otsu, triangle, multi_otsu):
        
        self.empty_data()
        
        if not input_vol:
            raise ValueError("Input volume is invalid")
        if not input_segmentation:
            raise ValueError("Input segmentation is invalid")
        
        print("Broken Heart segmentation started.")
        
        self.data["segmentation"] =  input_segmentation.GetSegmentation()
        self.data["source_segment"] = self.data["segmentation"].GetSegment(seg_id)
        
        if not self.data["source_segment"]:
            raise ValueError('Invalid segment')


        # hide orig seg.
        input_segmentation.GetDisplayNode().SetVisibility(False)
        
        self.data["seg_labelmap"] = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
        # seg_labelmap.SetName(f'{seg_name}_label')
        slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(input_segmentation, [seg_id], self.data["seg_labelmap"], input_vol)

        self.data["sitk_img"] = sitkUtils.PullVolumeFromSlicer(input_vol.GetID())
        self.data["sitk_mask"] = sitkUtils.PullVolumeFromSlicer(self.data["seg_labelmap"].GetID())
        self.data["input_array"] = sitk.GetArrayFromImage(self.data["sitk_img"])
        self.data["mask_array"] = sitk.GetArrayFromImage(self.data["sitk_mask"])


        self.data["input_array"][self.data["mask_array"] ==0] = -1024
        self.data["masked_sitk_img"] = sitk.GetImageFromArray(self.data["input_array"])
        self.data["masked_sitk_img"].SetOrigin(self.data["sitk_img"].GetOrigin())
        self.data["masked_sitk_img"].SetSpacing(self.data["sitk_img"].GetSpacing())
        self.data["masked_sitk_img"].SetDirection(self.data["sitk_img"].GetDirection())
        

        self.data["masked_img"] = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLScalarVolumeNode')
        self.data["masked_img"].SetName(f'Masked image')
        sitkUtils.PushVolumeToSlicer(self.data["masked_sitk_img"],"Masked image")
        
        if fix_thr:
            self.create_fix_thr_segmentation(fix_thr_val=fix_thr_val,**self.data)
            slicer.modules.BrokenHeartWidget.ui.btn_fix_stat.enabled=True
            slicer.modules.BrokenHeartWidget.ui.btn_fix_view.enabled=True

            
        if otsu:
            self.create_otsu_segmentation(**self.data)
            slicer.modules.BrokenHeartWidget.ui.btn_otsu_stat.enabled=True
            slicer.modules.BrokenHeartWidget.ui.btn_otsu_view.enabled=True

        
        if triangle:
            self.create_triangle_segmentation(**self.data)
            slicer.modules.BrokenHeartWidget.ui.btn_triangle_stat.enabled=True
            slicer.modules.BrokenHeartWidget.ui.btn_triangle_view.enabled=True

            
        if multi_otsu:
            self.create_multi_otsu_segmentation(num_of_segments = multi_otsu_val, **self.data)
            slicer.modules.BrokenHeartWidget.ui.btn_multi_stat.enabled=True
            slicer.modules.BrokenHeartWidget.ui.btn_multi_view.enabled=True


        
        print("Broken Heart segmentation finished.")
            
    
    def create_otsu_segmentation(self, sitk_img, masked_sitk_img, masked_img, out_segmentation = None, **kwargs):
        print("Otsu segmentation started...")
        otsu = sitk.OtsuMultipleThresholdsImageFilter()
        otsu.SetNumberOfThresholds(2)
        sitk_otsu_LV_masks_image = otsu.Execute(masked_sitk_img)

        
        if not out_segmentation:
            out_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Otsu segmentation")
            out_segmentation.SetReferenceImageGeometryParameterFromVolumeNode(masked_img)
            out_segmentation.CreateDefaultDisplayNodes()
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(self.data.get('seg_labelmap')),
                                                                        f"Total")
            out_segmentation.GetDisplayNode().SetOpacity(0.5)
            out_segmentation.GetDisplayNode().SetVisibility(False)
            
            

        for i in range(2):
            otsu_img = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
            otsu_img.SetName(f'Otsu mask {i+1}')
            _arr = sitk.GetArrayFromImage(sitk_otsu_LV_masks_image)
            _arr[_arr!=i+1] = 0
            _arr[_arr==i+1] = 1
            _sitk_LV_mask_image = sitk.GetImageFromArray(_arr)
            _sitk_LV_mask_image.SetOrigin(sitk_img.GetOrigin())
            _sitk_LV_mask_image.SetSpacing(sitk_img.GetSpacing())
            _sitk_LV_mask_image.SetDirection(sitk_img.GetDirection())
            
            sitkUtils.PushVolumeToSlicer(_sitk_LV_mask_image,otsu_img)

            _seg = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(otsu_img)
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(_seg,f"Otsu mask {i+1}")
            slicer.mrmlScene.RemoveNode(otsu_img)
            del(_sitk_LV_mask_image)

        
        self.data["otsu"] = out_segmentation
    
        
    def create_multi_otsu_segmentation(self, sitk_img, masked_sitk_img, masked_img, num_of_segments, out_segmentation = None, **kwargs):
        print("Multi Otsu segmentation started...")
        otsu = sitk.OtsuMultipleThresholdsImageFilter()
        otsu.SetNumberOfThresholds(num_of_segments)
        sitk_otsu_LV_masks_image = otsu.Execute(masked_sitk_img)

        
        if not out_segmentation:
            out_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"Multi Otsu [{num_of_segments}] segmentation")
            out_segmentation.SetReferenceImageGeometryParameterFromVolumeNode(masked_img)
            out_segmentation.CreateDefaultDisplayNodes()
            
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(self.data.get('seg_labelmap')),
                                                                        f"Total")
            out_segmentation.GetDisplayNode().SetOpacity(0.5)
            out_segmentation.GetDisplayNode().SetVisibility(False)

        for i in range(num_of_segments):
            otsu_img = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
            otsu_img.SetName(f'Otsu mask {i+1}')
            _arr = sitk.GetArrayFromImage(sitk_otsu_LV_masks_image)
            _arr[_arr!=i+1] = 0
            _arr[_arr==i+1] = 1
            _sitk_LV_mask_image = sitk.GetImageFromArray(_arr)
            _sitk_LV_mask_image.SetOrigin(sitk_img.GetOrigin())
            _sitk_LV_mask_image.SetSpacing(sitk_img.GetSpacing())
            _sitk_LV_mask_image.SetDirection(sitk_img.GetDirection())
            
            sitkUtils.PushVolumeToSlicer(_sitk_LV_mask_image,otsu_img)

            _seg = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(otsu_img)
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(_seg,f"Otsu mask {i+1}")
            slicer.mrmlScene.RemoveNode(otsu_img)
            del(_sitk_LV_mask_image)

        
        self.data["multi_otsu"] = out_segmentation
    
    def create_triangle_segmentation(self, input_array, mask_array, masked_sitk_img, sitk_mask, masked_img, out_segmentation = None, **kwargs):
        print("Triangle segmentation started...")
        if not out_segmentation:
            out_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Triangle segmentation")
            out_segmentation.SetReferenceImageGeometryParameterFromVolumeNode(masked_img)
            out_segmentation.CreateDefaultDisplayNodes()
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(self.data.get('seg_labelmap')),
                                                            f"Total")
            out_segmentation.GetDisplayNode().SetOpacity(0.5)
            out_segmentation.GetDisplayNode().SetVisibility(False)
        
        
        triangle_threshold_val = triangle_threshold(np.array(input_array[mask_array==1]).flatten())

        triangle_images = create_binary_images(masked_sitk_img, sitk_mask, triangle_threshold_val)
        for _img, _name in zip(triangle_images,["lower","upper"]):
            triangle_img = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
            triangle_img.SetName(f'{_name}_triangle')
            sitkUtils.PushVolumeToSlicer(_img,triangle_img)
            _seg = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(triangle_img)
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(_seg,f"{_name} triangle")
            slicer.mrmlScene.RemoveNode(triangle_img)
        del(triangle_images)

        self.data["triangle"] = out_segmentation
        
    
    def create_fix_thr_segmentation(self, masked_sitk_img, sitk_mask, masked_img, fix_thr_val, out_segmentation = None, **kwargs):
        print("Fix threshold based segmentation started...")

        if not out_segmentation:
            out_segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Fix thr segmentation")
            out_segmentation.SetReferenceImageGeometryParameterFromVolumeNode(masked_img)
            out_segmentation.CreateDefaultDisplayNodes()
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(self.data.get('seg_labelmap')),
                                                                        f"Total")
            out_segmentation.GetDisplayNode().SetOpacity(0.5)
            out_segmentation.GetDisplayNode().SetVisibility(False)
        
        
        _images = create_binary_images(masked_sitk_img, sitk_mask, fix_thr_val)
        for _img, _name in zip(_images,[f"below {fix_thr_val}",f"above {fix_thr_val}"]):
            thr_img = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLLabelMapVolumeNode')
            thr_img.SetName(f'{_name}_fix_thr')
            sitkUtils.PushVolumeToSlicer(_img,thr_img)
            _seg = slicer.modules.segmentations.logic().CreateOrientedImageDataFromVolumeNode(thr_img)
            out_segmentation.AddSegmentFromBinaryLabelmapRepresentation(_seg,f"{_name}")
            slicer.mrmlScene.RemoveNode(thr_img)
        del(_images)
            

        
        self.data["fix"] = out_segmentation
    
    
    def view_seg(self,seg_type):
        if seg_type not in self.data.keys():
            raise ValueError('Invalid segmentation type')
        
        if not self.segmentEditorNode or not self.segmentEditorWidget:
            slicer.util.selectModule("SegmentEditor")
            self.init_editor()
                    
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)

        _segementation = self.data.get(seg_type)
        display_node = _segementation.GetDisplayNode()
        
        segementation = _segementation.GetSegmentation()
        segment_ids = list(segementation.GetSegmentIDs())

        self.segmentEditorWidget.setSegmentationNode(_segementation)
        self.segmentEditorWidget.setSourceVolumeNode(self.data.get("masked_img"))
                       
        display_node.SetAllSegmentsVisibility(False)
        display_node.SetAllSegmentsVisibility3D(False)
        
        for i in range(len(segment_ids)):
            seg_id = segment_ids[i]
            display_node.SetSegmentOpacity2DFill(seg_id,0.85)
            display_node.SetSegmentOpacity2DOutline(seg_id,1)
            
            if i == 1:
                display_node.SetSegmentVisibility(seg_id,True)
                display_node.SetSegmentVisibility3D(seg_id,True)
                display_node.SetSegmentVisibility3D(seg_id,True)

        self.segmentEditorNode.SetOverwriteMode(slicer.vtkMRMLSegmentEditorNode.OverwriteNone)
        self.segmentEditorNode.SetMaskSegmentID(segment_ids[0])
        self.segmentEditorNode.SetMaskMode(slicer.vtkMRMLSegmentationNode.EditAllowedInsideSingleSegment)
        self.segmentEditorNode.SetSelectedSegmentID(segment_ids[1])
    
        display_node.SetVisibility(True)
        display_node.SetOpacity(1.0)
        display_node.SetVisibility3D(True)
        display_node.SetOpacity3D(0.8)
                
        
        volume_display_nodes = slicer.mrmlScene.GetNodesByClass("vtkMRMLScalarVolumeDisplayNode")
        
        for v in volume_display_nodes:
            v.InterpolateOff()
            v.SetAutoWindowLevel(0)
            v.SetWindowLevelMinMax(-100,400)
        
        _segementation.CreateClosedSurfaceRepresentation()
        
        # Center and fit displayed content in 3D view
        layoutManager = slicer.app.layoutManager()
        threeDWidget = layoutManager.threeDWidget(0)
        threeDView = threeDWidget.threeDView()
        threeDView.rotateToViewAxis(3)  # look from anterior direction
        threeDView.resetFocalPoint()  # reset the 3D view cube size and center it
        threeDView.resetCamera()  # reset camera zoom
        
        
        # self.segmentEditorWidget.show()
        slicer.util.selectModule("SegmentEditor")
        
    
    def stat_table(self,seg_type):
        if seg_type not in self.data.keys():
            raise ValueError('Invalid segmentation type')
        
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
        
        self.segmentEditorWidget.close()
        
        _segementation = self.data.get(seg_type)
        display_node = _segementation.GetDisplayNode()
        
        segementation = _segementation.GetSegmentation()
        segment_ids = list(segementation.GetSegmentIDs())
        
        
        if self.data.get("stat_table"):
            if isinstance(self.data.get("stat_table"),slicer.vtkMRMLNode):
                slicer.mrmlScene.RemoveNode(self.data.get("stat_table"))
            
        self.data["stat_table"] = slicer.mrmlScene.AddNewNodeByClass('vtkMRMLTableNode')
        
        display_node.SetAllSegmentsVisibility(False)
        display_node.SetAllSegmentsVisibility3D(False)
        
        display_node.SetVisibility(True)
        display_node.SetOpacity(1.0)
        display_node.SetVisibility3D(False)
        
        display_node.SetSegmentVisibility(segment_ids[0],True)
        display_node.SetSegmentVisibility(segment_ids[1],True)
        
        segStatLogic = SegmentStatistics.SegmentStatisticsLogic()
        segStatLogic.getParameterNode().SetParameter("Segmentation", _segementation.GetID())
        segStatLogic.getParameterNode().SetParameter("ScalarVolume", self.data["masked_img"].GetID())
        segStatLogic.getParameterNode().SetParameter("LabelmapSegmentStatisticsPlugin.enabled","False")
        segStatLogic.getParameterNode().SetParameter("ScalarVolumeSegmentStatisticsPlugin.voxel_count.enabled","False")
        segStatLogic.computeStatistics()
        segStatLogic.exportToTable(self.data["stat_table"])
        segStatLogic.showTable(self.data["stat_table"])
        
        
    def empty_data(self):
        for key, value in self.data.items():
            try:
                if isinstance(value,slicer.vtkMRMLNode):
                    slicer.mrmlScene.RemoveNode(value)
            except:
                continue
            
        
        self.data.clear()
        
    
        slicer.modules.BrokenHeartWidget.ui.btn_fix_stat.enabled=False
        slicer.modules.BrokenHeartWidget.ui.btn_otsu_stat.enabled=False
        slicer.modules.BrokenHeartWidget.ui.btn_triangle_stat.enabled=False
        slicer.modules.BrokenHeartWidget.ui.btn_multi_stat.enabled=False
        
        slicer.modules.BrokenHeartWidget.ui.btn_fix_view.enabled=False
        slicer.modules.BrokenHeartWidget.ui.btn_otsu_view.enabled=False
        slicer.modules.BrokenHeartWidget.ui.btn_triangle_view.enabled=False
        slicer.modules.BrokenHeartWidget.ui.btn_multi_view.enabled=False
        
    
            
#
# BrokenHeartTest
#

class BrokenHeartTest(ScriptedLoadableModuleTest):
    """
    This is the test case for your scripted module.
    Uses ScriptedLoadableModuleTest base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def setUp(self):
        """ Do whatever is needed to reset the state - typically a scene clear will be enough.
        """
        slicer.mrmlScene.Clear()

    def runTest(self):
        """Run as few or as many tests as needed here.
        """
        self.setUp()
        self.test_BrokenHeart1()

    def test_BrokenHeart1(self):
        return True

