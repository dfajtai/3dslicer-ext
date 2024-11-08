import logging
import os

import vtk

import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin

from DICOMLib import DICOMUtils

import numpy as np
import pandas as pd
import json

from utils.RTCompare_config import RTCompareMeasurement
from utils.show_table import populate_qtablewidget_with_dataframe
from utils.rt_structure_to_segment import extract_rt_struct_names, group_rt_struct_names, grouped_rt_struct_to_segments, format_rt_struct_name
from utils.open_folder import open_folder
from utils.custom_segement_stats import calculate_stats

#
# RTCompare
#


__defaultSourceDirectory__ = "/local_data/sugar/dicom"
__defaultOutputDirectory__ = "/local_data/sugar/res"
__defaultStudyDesc__ = "Tervezés (CT)"
__defaultModality__ = "RTSTRUCT"


__defaultStepSizes__ = [0.5, 0.5, 0.5]
__defaultMargin__ = [5.0, 5.0, 5.0]
__defaultExportLabelmap__ = False
__defaultExportSurface__ = False


__patientsCsv_cols__ = ["patient_id","patient_name","study_date","import_timestamp"]


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
        
        self.ui.patientsCSVPath.connect("currentPathChanged(QString)",lambda path,name="patientsCsv": self.onPathChanged(path,name))
        self.ui.configJsonPath.connect("currentPathChanged(QString)",lambda path,name="configJson": self.onPathChanged(path,name))
        self.ui.resultsCSVPath.connect("currentPathChanged(QString)",lambda path,name="resultsCsv": self.onPathChanged(path,name))
        
        
        
        self.ui.margin.connect("coordinatesChanged(double*)",
                                lambda val, widget=self.ui.margin, name = 'margin': self.onFloatVectorChanged(name,widget,val))
        
        self.ui.margin.coordinates = ','.join([str(np.round(val,2)) for val in __defaultMargin__])
        
        
        self.ui.stepSizes.connect("coordinatesChanged(double*)",
                                lambda val, widget=self.ui.stepSizes, name = 'stepSizes': self.onFloatVectorChanged(name,widget,val))
        
        self.ui.stepSizes.coordinates = ','.join([str(np.round(val,2)) for val in __defaultStepSizes__])
        
        self.ui.patientsTbl.selectionModel().selectionChanged.connect(self.selected_entry_changed)
        
        
        
        self.ui.cbExportLabelmap.connect("stateChanged(int)", lambda val,name='exportLabelmap':self.onCheckboxChanged(bool(val),name))
        self.ui.cbExportLabelmap.checked = __defaultExportLabelmap__
        
        self.ui.cbExportSurface.connect("stateChanged(int)", lambda val,name='exportSurface':self.onCheckboxChanged(bool(val),name))
        self.ui.cbExportSurface.checked = __defaultExportSurface__
        
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
        
        self.ui.patientsCSVPath.currentPath = str(self._parameterNode.GetParameter("patientsCsv"))
        self.ui.configJsonPath.currentPath = str(self._parameterNode.GetParameter("configJson"))
        self.ui.resultsCSVPath.currentPath = str(self._parameterNode.GetParameter("resultsCsv"))
        

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
        self.ui.configJsonPath.currentPath = os.path.join(outputDirectory,"config.json")
        self.ui.resultsCSVPath.currentPath = os.path.join(outputDirectory,"results.csv")

        
    def selected_entry_changed(self):
        current_selection = self.ui.patientsTbl.selectedIndexes()
        if len(current_selection)>0:
            self.ui.btnExtractStructureInfo.enabled = True
            
            current_selection = current_selection[0]
            tbl_selected_ID = self.ui.patientsTbl.item(current_selection.row(),0).text()
            self.logic.set_selected_entry(tbl_selected_ID)
        else:
            self.ui.btnExtractStructureInfo.enabled = True            
            
    def onFloatVectorChanged(self, name, widget, val):
        coords = [float(x) for x in widget.coordinates.split(',')]
        if name == "stepSizes":
            self.logic.stepSizes = coords
        if name == "margin":
            self.logic.stepSizes = coords
            
    
    def onCheckboxChanged(self, val, name):
        if name == "exportLabelmap":
            self.logic.exportLabelmap = val
        if name == "exportSurface":
            self.logic.exportSurface = val
            
    def onPathChanged(self,path,name):
        if name == "patientsCsv":
            self._parameterNode.SetParameter("patientsCsv",str(self.ui.patientsCSVPath.currentPath))
        if name == "configJson":    
            self._parameterNode.SetParameter("configJson",str(self.ui.configJsonPath.currentPath))
        if name == "resultsCsv":
            self._parameterNode.SetParameter("resultsCsv",str(self.ui.resultsCSVPath.currentPath))
            
        
        
    def onInitializeButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to initialize DICOM DB", waitCursor=True):
            self.logic.initializeDB()
            self.ui.patientsTbl.enabled= True
            
            self.ui.runBtn.enabled = True
            
            slicer.util.selectModule("RTCompare")
            
            populate_qtablewidget_with_dataframe(self.logic.entries_df,self.ui.patientsTbl,["patient_id","patient_name","study_date","import_timestamp"])
            self.ui.patientsTbl
            
    
    def onExtractStructureInfoButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to extract structure info", waitCursor=True):
            self.logic.extractInfo()
            
            
            populate_qtablewidget_with_dataframe(self.logic.struct_info_df,self.ui.structsTbl,["organ","type","structure_name"])
            self.ui.structsTbl.enabled = True
            
            self.ui.patientsCSVPath.enabled = True
            self.ui.configJsonPath.enabled = True
            self.ui.initConfigsBtn.enabled = True
            
            self.ui.resultsCSVPath.enabled = True

            
    
    def onInitializeConfigsButton(self):
        with slicer.util.tryWithErrorDisplay("Failed to initialize configs", waitCursor=True):
            # Suppress VTK warnings
            vtk.vtkObject.SetGlobalWarningDisplay(0)

            self.logic.initializeConfigs()
            open_folder(self.logic.outputDir)
            
            
            # Re-enable VTK warnings
            vtk.vtkObject.SetGlobalWarningDisplay(1)

    
    
        
    def onStartProcessingButton(self):
        """
        Run processing when user clicks "Apply" button.
        """
        with slicer.util.tryWithErrorDisplay("Failed to compute results.", waitCursor=True):
            
            
            # Suppress VTK warnings
            vtk.vtkObject.SetGlobalWarningDisplay(0)


            self.logic.runAnalysis()
            
            
            # Re-enable VTK warnings
            vtk.vtkObject.SetGlobalWarningDisplay(1)

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
        self.entries_df = None
        
        self.selected_entry = None
        
        self.struct_info_df = None
        
        self.stepSizes = __defaultStepSizes__
        self.margin = __defaultMargin__
        
        self.exportLabelmap = __defaultExportLabelmap__
        self.exportSurface = __defaultExportSurface__

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
        return {"patientsCsv":self.getParameterNode().GetParameter("patientsCsv"),
                "configJson":self.getParameterNode().GetParameter("configJson"),
                "resultsCsv":self.getParameterNode().GetParameter("resultsCsv")}
        
    
    
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
        
        self.entries_df = pd.DataFrame([x.__dict__ for x in entries])

    
    def extractInfo(self):
        names = []
        if self.selected_entry:
            slicer.mrmlScene.Clear()
            DICOMUtils.loadSeriesByUID([self.selected_entry.series_uid])
            names = extract_rt_struct_names()
                    
        self.struct_info_df = pd.DataFrame(group_rt_struct_names(names))
        
        return names
    
                    
    def initializeConfigs(self):      
        assert isinstance(self.entries_df,pd.DataFrame)        
        assert isinstance(self.struct_info_df,pd.DataFrame)

        if not os.path.exists(self.outputDir):
            os.makedirs(self.outputDir,exist_ok=True)
            
                
        out_df = pd.DataFrame(self.entries_df[__patientsCsv_cols__])
        out_df.loc[:,"MarkForProcessing"] = [1]*len(out_df.index)
        out_df.to_csv(self.file_paths.get("patientsCsv"), index=False)
        
        # strucure default json
        
        groups = self.struct_info_df["organ"].unique().tolist()
        
        json_data = []
        for g in groups:
            _rows = self.struct_info_df[self.struct_info_df["organ"]==g]
            types = _rows["type"].unique().tolist()
            group_data = {"group":g,"organ":g,"types":types,"structure_names":_rows["structure_name"].unique().tolist()}
            
            json_data.append(group_data)
            
        with open(self.file_paths.get("configJson"),"w") as json_file:
            json.dump(json_data,json_file,indent=4)
    
    def runAnalysis(self):
        
        assert os.path.exists(self.file_paths.get("patientsCsv"))
        assert os.path.exists(self.file_paths.get("configJson"))
    
        entries_dict = dict([(f"{e.patient_id}_{e.study_date}",e) for e in self.RT_entries])
        
        _results = []
        _volumes = []
        
        # load selected entries    
        df = pd.read_csv(self.file_paths.get("patientsCsv"))
        
        
        # load group configs
        
        configs = None
        with open(self.file_paths.get("configJson"),"r") as json_file:
            configs = json.load(json_file)
        
        
        for index,row in df.iterrows():
            patient_id, run_analysis, study_date = row.get("patient_id"), row.get("MarkForProcessing"), row.get("study_date")
                       
            case_id = f"{patient_id}_{study_date}"
                        
            if not bool(run_analysis):
                continue
            
            if case_id not in entries_dict.keys():
                continue
            
            case_dir = os.path.join(self.outputDir,case_id)
            os.makedirs(case_dir,exist_ok=True)
            
            
            target_entry = entries_dict.get(case_id)
            
            slicer.app.processEvents()
            print(f"Processing case:\n{str(target_entry)}")
            
            slicer.mrmlScene.Clear()
            DICOMUtils.loadSeriesByUID([target_entry.series_uid])
            
            
            shNode = slicer.mrmlScene.GetSubjectHierarchyNode()
            
            for grouping in configs:
                grouping_name = grouping.get("group")
                organ = grouping.get("organ")
                structure_names = grouping.get("structure_names")

                slicer.app.processEvents()
                print(f"Analyzing structures: {structure_names}")
                
                #results = {"ref_vol":referenceVolumeNode, "new_segmentation":new_segmentation, "number_of_segments":new_segment_index,"labelmaps":labelmaps,"names":names}
                segment_data = grouped_rt_struct_to_segments(target_segment_names=structure_names,spacing=self.stepSizes,margin=self.margin)
                
                # calc stats
                res_metrics, volumes, distances = calculate_stats(case_id= case_id,
                                                                  grouping_name = grouping_name,
                                                                  labelmap_nodes= segment_data.get("labelmaps"),
                                                                  labelmap_names=segment_data.get("names"),
                                                                  step_sizes=self.stepSizes)
                
                res_metrics_df = pd.DataFrame(res_metrics)
                res_metrics_df.to_csv(os.path.join(case_dir,f"{grouping_name}_results.csv"),index=False,float_format="%.4f")
                
                volumes_df = pd.DataFrame(volumes)
                volumes_df.to_csv(os.path.join(case_dir,f"{grouping_name}_volumes.csv"),index=False,float_format="%.4f")
                
                distances_df = pd.DataFrame(distances)
                distances_df.to_csv(os.path.join(case_dir,f"{grouping_name}_distances.csv"),index=False,float_format="%.4f")
                
                
                _results.extend(res_metrics)
                _volumes.extend(volumes)
                
                if self.exportLabelmap:
                    _out_dir = os.path.join(case_dir,"labelmaps")
                    os.makedirs(_out_dir,exist_ok=True)
                    for l,n in zip(segment_data.get("labelmaps"),segment_data.get("names")):
                        success = slicer.util.saveNode(l, os.path.join(_out_dir,f"{n}.nii.gz"))
                    
                if self.exportSurface:
                    _out_dir = os.path.join(case_dir,"models")
                    os.makedirs(_out_dir,exist_ok=True)
                    
                    exportFolderItemId = shNode.CreateFolderItem(shNode.GetSceneItemID(), "Segment_models")
                    success = slicer.modules.segmentations.logic().ExportAllSegmentsToModels(segment_data.get("new_segmentation"), exportFolderItemId)
                    
                    if success:
                        child_item_ids = vtk.vtkIdList()
                        shNode.GetItemChildren(exportFolderItemId, child_item_ids)


                        for i in range(child_item_ids.GetNumberOfIds()):
                            child_item_id = child_item_ids.GetId(i)
                            
                            # Get the associated node for the child item
                            child_node = shNode.GetItemDataNode(child_item_id)
                            slicer.util.exportNode(child_node,os.path.join(_out_dir,f"{child_node.GetName()}.stl"))
                            slicer.mrmlScene.RemoveNode(child_node)
                            
                        
                    shNode.RemoveItem(exportFolderItemId)
                    
                # clean up
                slicer.mrmlScene.RemoveNode(segment_data.get("ref_vol"))
                slicer.mrmlScene.RemoveNode(segment_data.get("new_segmentation"))
                for l in segment_data.get("labelmaps"):
                    slicer.mrmlScene.RemoveNode(l)
                
        
        _res_df = pd.DataFrame(_results)
        _res_df.to_csv(self.file_paths.get("resultsCsv"),index=False,float_format="%.4f")
        
        _volumes_df = pd.DataFrame(_volumes)
        _volumes_df.to_csv(os.path.join(self.outputDir,"volumes.csv"),index=False,float_format="%.4f")
        
        slicer.mrmlScene.Clear()
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
