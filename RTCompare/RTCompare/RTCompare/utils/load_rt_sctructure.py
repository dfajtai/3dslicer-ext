from DICOMLib import DICOMUtils
import slicer
from slicer.util import getNode


def load_dicom_without_closed_surface(series_uid):
    raise NotImplementedError
    
    
    # Load the DICOM series by Series UID
    loadedNodes = DICOMUtils.loadSeriesByUID([series_uid])

    # Iterate through the loaded nodes and identify any segmentation nodes
    for node_id in loadedNodes:
        node = getNode(node_id)
        if node.IsA("vtkMRMLSegmentationNode"):
            
            print(node)
            # Check if the closed surface representation exists
            if node.GetSegmentation().HasRepresentation('Closed surface'):
                # Remove closed surface representation to retain planar contour data only
                node.GetSegmentation().RemoveRepresentation('Closed surface')
                print(f"Closed surface representation removed for segmentation node: {node.GetName()}")
