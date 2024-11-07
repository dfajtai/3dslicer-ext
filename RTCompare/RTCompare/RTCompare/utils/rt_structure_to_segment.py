

import numpy as np
import vtk
import slicer


def extract_rt_struct_names():
    allSegmentNodes = slicer.util.getNodes('vtkMRMLSegmentationNode*').values()
    names = []
    for _segment_node in allSegmentNodes:
        seg_node_name = _segment_node.GetName()
        segmentation_node = slicer.util.getNode(seg_node_name)
        segmentation_node.CreateBinaryLabelmapRepresentation()
    
        segmentation = segmentation_node.GetSegmentation()
        num_of_segments = segmentation.GetNumberOfSegments()
    
        for i in range(num_of_segments):
            segment = segmentation.GetNthSegment(i)
            names.append(segment.GetName())

    return names


def group_rt_struct_names(names):
    split_names = [{"group":str(n).split("_")[0],"type":"".join(str(n).split("_")[1:]),"structure_name":n} for n in names]
    return split_names


def rt_struct_to_segment(outputVolumeSpacingMm,outputVolumeMarginMm):
    allSegmentNodes = slicer.util.getNodes('vtkMRMLSegmentationNode*').values()
    shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    
    colorTableNode = slicer.mrmlScene.GetFirstNodeByName('vtkMRMLColorTableNodeGreen')
    
    for _segment_node in allSegmentNodes:
        bounds = []
    
        seg_info = shNode.GetItemByDataNode(_segment_node)
        volumeItemId = shNode.GetItemByDataNode(_segment_node)
        seriesInstanceUID = shNode.GetItemUID(volumeItemId, 'DICOM')
        instUids = slicer.dicomDatabase.instancesForSeries(seriesInstanceUID)
        patient_id = slicer.dicomDatabase.instanceValue(instUids[0], '0010,0020')
    
    
        seg_node_name = _segment_node.GetName()
        segmentation_node = slicer.util.getNode(seg_node_name)
        segmentation_node.CreateBinaryLabelmapRepresentation()
    
        segmentation = segmentation_node.GetSegmentation()
        num_of_segments = segmentation.GetNumberOfSegments()
    
        for i in range(num_of_segments):
            segment = segmentation.GetNthSegment(i)
            # print(segment.GetName())
            _bounds = np.zeros(6)
            segment.GetBounds(_bounds)
            bounds.append(_bounds)
            # print(_bounds)
    
        bounds = np.array(bounds)
        mutual_bounds = [bounds[:,0].min(),bounds[:,1].max(),bounds[:,2].min(),bounds[:,3].max(),bounds[:,4].min(),bounds[:,5].max()]
        print(mutual_bounds)
    
        imageData = vtk.vtkImageData()
        imageSize = [ int((mutual_bounds[axis*2+1]-mutual_bounds[axis*2]+outputVolumeMarginMm[axis]*2.0)/outputVolumeSpacingMm[axis]) for axis in range(3) ]
        imageOrigin = [ mutual_bounds[axis*2]-outputVolumeMarginMm[axis] for axis in range(3) ]
        imageData.SetDimensions(imageSize)
        imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    
        referenceVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        referenceVolumeNode.SetName("ref_vol")
        referenceVolumeNode.SetOrigin(imageOrigin)
        referenceVolumeNode.SetSpacing(outputVolumeSpacingMm)
        referenceVolumeNode.SetAndObserveImageData(imageData)
        referenceVolumeNode.CreateDefaultDisplayNodes()
    
        new_seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        new_seg.SetReferenceImageGeometryParameterFromVolumeNode(referenceVolumeNode)
        new_segmentation = new_seg.GetSegmentation()
        for i in range(num_of_segments):
            segment = segmentation.GetNthSegment(i)
            segmentId = segmentation.GetNthSegmentID(i)
            labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            labelmapVolumeNode.SetName(segment.GetName())
    
            new_segmentation.CopySegmentFromSegmentation(segmentation,segmentId)
            new_segment_id = new_segmentation.GetNthSegmentID(i)
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(new_seg, 
                                                                              [new_segment_id], 
                                                                              labelmapVolumeNode, 
                                                                              referenceVolumeNode, 
                                                                              slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY, 
                                                                              colorTableNode)