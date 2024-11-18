

import numpy as np
import vtk
import slicer


def extract_rt_struct_names():
    allSegmentNodes = slicer.util.getNodes('vtkMRMLSegmentationNode*').values()
    names = []
    for _segment_node in allSegmentNodes:
        seg_node_name = _segment_node.GetName()
        segmentation_node = slicer.util.getNode(seg_node_name)
        # segmentation_node.CreateBinaryLabelmapRepresentation()
    
        segmentation = segmentation_node.GetSegmentation()
        num_of_segments = segmentation.GetNumberOfSegments()
    
        for i in range(num_of_segments):
            segment = segmentation.GetNthSegment(i)
            names.append(segment.GetName())

    return names


def format_rt_struct_name(name):
    _name = str(name).strip().replace(" ","_").lower()
    return _name

def group_rt_struct_names(names):
    split_names = []
    for n in names:
        _name = format_rt_struct_name(n)
        organ = "_".join(str(_name).split("_")[:-1])
        _type = str(_name).split("_")[-1]
    
        split_names.append({"organ":organ,"type":_type,"structure_name":_name})
    
    return split_names



def grouped_rt_struct_to_segments(target_segment_names,spacing,margin,keep_alive = False):
    allSegmentNodes = slicer.util.getNodes('vtkMRMLSegmentationNode*').values()

    colorTableNode = slicer.mrmlScene.GetFirstNodeByName('vtkMRMLColorTableNodeGreen')

    
    for _segment_node in allSegmentNodes:
        seg_node_name = _segment_node.GetName()
        segmentation_node = slicer.util.getNode(seg_node_name)
        # segmentation_node.CreateBinaryLabelmapRepresentation()
    
        segmentation = segmentation_node.GetSegmentation()
        num_of_segments = segmentation.GetNumberOfSegments()
        
        bounds = []
        
        for i in range(num_of_segments):
            segment = segmentation.GetNthSegment(i)
            segment_name = segment.GetName()
            if format_rt_struct_name(segment_name) not in target_segment_names:
                continue
                        
            _bounds = np.zeros(6)
            segment.GetBounds(_bounds)
            bounds.append(_bounds)
            
            if keep_alive:
                print(f"Segement '{segment_name}' bounds: '{_bounds}'")
                slicer.app.processEvents()
            
        bounds = np.array(bounds)
        mutual_bounds = [bounds[:,0].min(),bounds[:,1].max(),bounds[:,2].min(),bounds[:,3].max(),bounds[:,4].min(),bounds[:,5].max()]

        # print(mutual_bounds)
        
        imageData = vtk.vtkImageData()
        imageSize = [ int((mutual_bounds[axis*2+1]-mutual_bounds[axis*2]+margin[axis]*2.0)/spacing[axis]) for axis in range(3) ]
        imageOrigin = [ mutual_bounds[axis*2]-margin[axis] for axis in range(3) ]
        imageData.SetDimensions(imageSize)
        imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    
        referenceVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        referenceVolumeNode.SetName("ref_vol")
        referenceVolumeNode.SetOrigin(imageOrigin)
        referenceVolumeNode.SetSpacing(spacing)
        referenceVolumeNode.SetAndObserveImageData(imageData)
        referenceVolumeNode.CreateDefaultDisplayNodes()
    
        new_seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        new_seg.SetReferenceImageGeometryParameterFromVolumeNode(referenceVolumeNode)
        new_segmentation = new_seg.GetSegmentation()
        
        if keep_alive:
            slicer.app.processEvents()
        
        new_segment_index = 0
        labelmaps = []
        names = []
        for i in range(num_of_segments):
            segment = segmentation.GetNthSegment(i)
            segment_name = segment.GetName()
            if format_rt_struct_name(segment_name) not in target_segment_names:
                continue
            
            segmentId = segmentation.GetSegmentIdBySegmentName(segment_name)
            labelmapVolumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
            labelmapVolumeNode.SetName(format_rt_struct_name(segment_name))

            new_segmentation.CopySegmentFromSegmentation(segmentation,segmentId)            
            new_segment_id = new_segmentation.GetNthSegmentID(new_segment_index)            
            slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(new_seg, 
                                                                              [new_segment_id], 
                                                                              labelmapVolumeNode, 
                                                                              referenceVolumeNode, 
                                                                              slicer.vtkSegmentation.EXTENT_REFERENCE_GEOMETRY, 
                                                                              colorTableNode)
            labelmaps.append(labelmapVolumeNode)
            names.append(format_rt_struct_name(segment_name))
            new_segment_index +=1
            if keep_alive:
                print(f"Segement '{segment_name}' processed")
                slicer.app.processEvents()
            
        results = {"ref_vol":referenceVolumeNode, "new_segmentation":new_seg, "number_of_segments":new_segment_index,"labelmaps":labelmaps,"names": names}
        
        del(imageData)
        
        
        return results