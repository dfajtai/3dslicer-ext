import logging
import os

import vtk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from DICOMLib import DICOMUtils


import pandas as pd

from utils.RTCompare_config import RTCompareMeasurement
from utils.show_table import populate_qtablewidget_with_dataframe
from utils.rt_structure_to_segment import rt_struct_to_segment, extract_rt_struct_names, group_rt_struct_names

#
# RTCompare
#


__defaultSourceDirectory__ = "/local_data/sugar/dicom"
__defaultOutputDirectory__ = "/local_data/sugar/res"
__defaultStudyDesc__ = "Tervezés (CT)"
__defaultModality__ = "RTSTRUCT"


outputVolumeSpacingMm = [0.5, 0.5, 0.5]
outputVolumeMarginMm = [5.0, 5.0, 5.0]




class RTCompare(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "RTCompare"  # TODO: make this more human readable by adding spaces
        self.parent.categories = ["Quantification"]  # TODO: set categories (folders where the module shows up in the module selector)
        self.parent.dependencies = ["DicomRtImportExport","Segmentations"]  # TODO: add here list of module names that this module requires
        self.parent.contributors = ["Daniel Fajtai (none)"]  # TODO: replace with "Firstname Lastname (Organization)"
        # TODO: update with short description of the module and a link to online module documentation
        self.parent.helpText = """This is a neat little extension for on-demand RT structure comparison"""
        # TODO: replace with organization, grant and thanks
        self.parent.acknowledgementText = """Noone just for myself."""

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
    print("Sample for 'RTCompare' not included")


#
# RTCompareWidget
#

class RTCompareWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """
    defaultSourceDirectory = __defaultSourceDirectory__
    defaultOutputDirectory = __defaultOutputDirectory__
    
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
        uiWidget = slicer.util.loadUI(self.resourcePath('UI/RTCompare.ui'))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = RTCompareLogic()

        # Connections
        
        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)
        
        # These connections ensure that whenever user changes some settings on the GUI, that is saved in the MRML scene
        # (in the selected parameter node).
        

        self.ui.sourceDirBtn.directoryChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.outputDirBtn.directoryChanged.connect(self.updateParameterNodeFromGUI)
        
        self.ui.tbModality.textChanged.connect(self.updateParameterNodeFromGUI)
        self.ui.tbStudyDesc.textChanged.connect(self.updateParameterNodeFromGUI)
        
        self.ui.patientsCSVPath.currentPathChanged.connect(self.path_changed)
        self.ui.jsonPath.currentPathChanged.connect(self.path_changed)
        self.ui.resultsCSVPath.currentPathChanged.connect(self.path_changed)


        
        self.ui.patientsTbl.selectionModel().selectionChanged.connect(self.selected_entry_changed)
        
        
        # Buttons
        
        self.ui.initBtn.connect('clicked(bool)',self.onInitializeButton)
        self.ui.btnExtractStructureInfo.connect('clicked(bool)',self.onExtractStructureInfoButton)
        self.ui.initConfigsBtn.connect('clicked(bool)',self.onInitializeConfigsButton)
        self.ui.runBtn.connect('clicked(bool)', self.onStartProcessingButton)

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()

    def cleanup(self):
        """
        Called when the application closes and the module widget is destroyed.
        """
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
        

        
        if not os.path.exists(RTCompareWidget.defaultSourceDirectory):
            RTCompareWidget.defaultSourceDirectory = os.getcwd()
        
        if not os.path.exists(RTCompareWidget.defaultOutputDirectory):
            RTCompareWidget.defaultOutputDirectory = os.getcwd()
            
            
    
        self._parameterNode.SetParameter("sourceDir",str(RTCompareWidget.defaultSourceDirectory))
        self._parameterNode.SetParameter("outDir",str(RTCompareWidget.defaultOutputDirectory))
            
        self._parameterNode.SetParameter("acceptedModality",str(__defaultModality__))
        self._parameterNode.SetParameter("acceptedStudy",str(__defaultStudyDesc__))        
        
        self.outputChanged()
        self.logic.syncParameters(self._parameterNode)   


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
        
        
        
        self.ui.sourceDirBtn.directory = self._parameterNode.GetParameter("sourceDir")
        self.ui.outputDirBtn.directory = self._parameterNode.GetParameter("outDir")
        
        
        self.ui.tbModality.text = self._parameterNode.GetParameter("acceptedModality")
        self.ui.tbStudyDesc.text = self._parameterNode.GetParameter("acceptedStudy")
        

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
        
        
        
        self._parameterNode.SetParameter("sourceDir",str(self.ui.sourceDirBtn.directory))
        orig_out_dir = self._parameterNode.GetParameter("outDir")
        self._parameterNode.SetParameter("outDir",str(self.ui.outputDirBtn.directory))
        if orig_out_dir!=str(self.ui.outputDirBtn.directory):
            self.outputChanged()
        
        
        self._parameterNode.SetParameter("acceptedModality",str(self.ui.tbModality.text))
        self._parameterNode.SetParameter("acceptedStudy",str(self.ui.tbStudyDesc.text))
        
        
        self.logic.setAcceptedModality(self._parameterNode.GetParameter("acceptedModality"))
        self.logic.setAcceptedStudyDesc(self._parameterNode.GetParameter("acceptedStudy"))
        
        self.logic.syncParameters(self._parameterNode)

        
        self._parameterNode.EndModify(wasModified)
        
                
        
    def outputChanged(self):
        outputDirectory =  self._parameterNode.GetParameter("outDir")
        self.ui.patientsCSVPath.currentPath = os.path.join(outputDirectory,"patients.csv")
        self.ui.jsonPath.currentPath = os.path.join(outputDirectory,"config.json")
        self.ui.resultsCSVPath.currentPath = os.path.join(outputDirectory,"results.csv")

    
    def path_changed(self):        
        self._parameterNode.SetParameter("patientCsv",str(self.ui.patientsCSVPath.currentPath))
        self._parameterNode.SetParameter("configJson",str(self.ui.jsonPath.currentPath))
        self._parameterNode.SetParameter("resultsCsv",str(self.ui.resultsCSVPath.currentPath))
        
        
    def selected_entry_changed(self):
        current_selection = self.ui.patientsTbl.selectedIndexes()
        if len(current_selection)>0:
            current_selection = current_selection[0]
            tbl_selected_ID = self.ui.patientsTbl.item(current_selection.row(),0).text()
            self.logic.set_selected_entry(tbl_selected_ID)
            
        
    def onInitializeButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to initialize DICOM DB", waitCursor=True):
            self.logic.initializeDB()
            self.ui.patientsTbl.enabled= True
            self.ui.btnExtractStructureInfo.enabled = True
            
            slicer.util.selectModule("RTCompare")
            
            populate_qtablewidget_with_dataframe(self.logic.patients_df,self.ui.patientsTbl,["patient_id","patient_name","study_date"])
            
    
    def onExtractStructureInfoButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to extract structure info", waitCursor=True):
            self.logic.extractInfo()
            
            
            populate_qtablewidget_with_dataframe(self.logic.struct_info_df,self.ui.structsTbl,["group","type","structure_name"])
            self.ui.structsTbl.enabled = True
            
            self.ui.patientsCSVPath.enabled = True
            self.ui.jsonPath.enabled = True
            self.ui.initConfigsBtn.enabled = True
            
            self.ui.resultsCSVPath.enabled = True

            
    
    def onInitializeConfigsButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to initialize configs", waitCursor=True):
            self.logic.initializeConfigs()
    

    
    
        
    def onStartProcessingButton(self):
        """
        Run processing when user clicks "Apply" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            pass

    
#
# RTCompareLogic
#

class RTCompareLogic(ScriptedLoadableModuleLogic):
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
        
        self.sourceDir = ""
        self.outputDir = ""
        
        self.acceptedStudyDesc = ""
        self.acceptedModality = ""
        
        self.param_node = None
        
        self.RT_entries = []
        self.patients_df = None
        
        self.selected_entry = None
        
        self.struct_info_df = None
        

    def setDefaultParameters(self, parameterNode):
        """
        Initialize parameter node with default settings.
        """
        
        if not parameterNode.GetParameter("acceptedModality"):
            parameterNode.SetParameter("acceptedModality",__defaultModality__)

        if not parameterNode.GetParameter("acceptedStudy"):
            parameterNode.SetParameter("acceptedStudy",__defaultStudyDesc__)
        
    
    def setSourceDirectory(self,sourceDir):
        if str(self.sourceDir) != str(sourceDir):
            self.sourceDir = str(sourceDir)
            print(f"Source dir updated to '{sourceDir}'")

    def setOutputDirectory(self,outputDir):
        if str(self.outputDir) != str(outputDir):
            self.outputDir = str(outputDir)
            print(f"Output dir updated to '{outputDir}'")
        
    def setAcceptedStudyDesc(self,study_desc):
        if str(self.acceptedStudyDesc) != str(study_desc):
            self.acceptedStudyDesc = str(study_desc)
            print(f"Accepted StudyDescription updated to '{study_desc}'")
    
    def setAcceptedModality(self, modality):
        if str(self.acceptedModality) != str(modality):
            self.acceptedModality = str(modality)
            print(f"Accepted Modality updated to '{modality}'")
    
    
    def set_selected_entry(self,patient_id):
        self.selected_entry = None
        for e in self.RT_entries:
            if e.patient_id == patient_id:
                self.selected_entry = e
                return
        self.selected_entry = None
    
    def syncParameters(self, parameterNode):
        if parameterNode.GetParameter("acceptedModality"):
            self.setAcceptedModality(parameterNode.GetParameter("acceptedModality"))
        
        if parameterNode.GetParameter("acceptedStudy"):
            self.setAcceptedStudyDesc(parameterNode.GetParameter("acceptedStudy"))
        
        
        if parameterNode.GetParameter("sourceDir"):
            self.setSourceDirectory(parameterNode.GetParameter("sourceDir"))
        
        if parameterNode.GetParameter("outDir"):
            self.setOutputDirectory(parameterNode.GetParameter("outDir"))

        self.param_node = parameterNode
    
    @property
    def file_paths(self):
        return {"patient_csv":self.getParameterNode().GetParameter("patientCsv"),
                "config_json":self.getParameterNode().GetParameter("configJson"),
                "results_csv":self.getParameterNode().GetParameter("resultsCsv")}
        
    
    
    def initializeDB(self):
        if not os.path.exists(self.sourceDir):
            print(f"Source directory '{self.sourceDir}' not exists!")
            return
        
                    
        # instantiate a new DICOM browser
        slicer.util.selectModule("DICOM")
        dicomBrowser = slicer.modules.DICOMWidget.browserWidget.dicomBrowser
        
        orig_patients = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().patients()
        
        # use dicomBrowser.ImportDirectoryCopy to make a copy of the files (useful for importing data from removable storage)
        dicomBrowser.importDirectory(self.sourceDir, dicomBrowser.ImportDirectoryAddLink)
        # wait for import to finish before proceeding (optional, if removed then import runs in the background)
        dicomBrowser.waitForImportFinished()
        

        all_patients = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().patients()
        
        entries = []
        
        
        for patient_index in all_patients:
            patient_studies = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().studiesForPatient(patient_index)
            patient_name = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().displayedNameForPatient(patient_index)
            sex = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForPatient('PatientsSex',patient_index)
            age = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForPatient('PatientsAge',patient_index)
            
            for study_uid in patient_studies:
                series = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().seriesForStudy(study_uid)
                study_desc = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForStudy('StudyDescription',study_uid)
                study_date = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForStudy('StudyDate',study_uid)
                
                if study_desc != self.acceptedStudyDesc:
                    continue
                
                for series_uid in series:
                    import_timestamp = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForSeries('InsertTimestamp',series_uid)
                    files = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().filesForSeries(series_uid)
                    series_desc = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForSeries('SeriesDescription',series_uid)
                    modality = slicer.modules.DICOMWidget.browserWidget.dicomBrowser.database().fieldForSeries('Modality',series_uid)
                    
                    if modality != self.acceptedModality:
                        continue
                    
                    entries.append(RTCompareMeasurement(patient_id=patient_index,
                                                                patient_name=patient_name,
                                                                patient_age=age,
                                                                patient_sex=sex,
                                                                study_desc=study_desc,
                                                                study_date=study_date,
                                                                series_description=series_desc,
                                                                import_timestamp=import_timestamp,
                                                                modality=modality,
                                                                series_uid = series_uid,
                                                                files=files
                                                                ))

        self.RT_entries = entries
        
        self.patients_df = pd.DataFrame([x.__dict__ for x in entries])

    
    def extractInfo(self):
        names = []
        if self.selected_entry:
            slicer.mrmlScene.Clear()
            DICOMUtils.loadSeriesByUID([self.selected_entry.series_uid])
            names = extract_rt_struct_names()
            
            # rt_struct_to_segment(outputVolumeSpacingMm=outputVolumeSpacingMm,outputVolumeMarginMm=outputVolumeMarginMm)
        
        self.struct_info_df = pd.DataFrame(group_rt_struct_names(names))
        
        return names
    
                    
    def initializeConfigs(self):
        raise NotImplementedError

#
# RTCompareTest
#

class RTCompareTest(ScriptedLoadableModuleTest):
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
        self.test_RTCompare1()

    def test_RTCompare1(self):
        """ Ideally you should have several levels of tests.  At the lowest level
        tests should exercise the functionality of the logic with different inputs
        (both valid and invalid).  At higher levels your tests should emulate the
        way the user would interact with your code and confirm that it still works
        the way you intended.
        One of the most important features of the tests is that it should alert other
        developers when their changes will have an impact on the behavior of your
        module.  For example, if a developer removes a feature that you depend on,
        your test should break so they know that the feature is needed.
        """

        assert(False)
