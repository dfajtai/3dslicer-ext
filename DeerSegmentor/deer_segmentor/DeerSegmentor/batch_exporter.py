def test():
    import vtk, qt, ctk, slicer
    import os

    slicer.modules.DeerSegmentorWidget.onBtnInitializeStudy()
    for sid, deer in slicer.modules.DeerSegmentorWidget.logic.deers.items():
        if not deer.db_info["done"]=='1':
            continue
        #open deer
        slicer.modules.DeerSegmentorWidget.logic.load_deer(sid)

        segmentation_node = slicer.mrmlScene.GetNodesByClass("vtkMRMLSegmentationNode").GetItemAsObject(0)
        accepted = ["mask","non-liver","worm"]

        volume = deer.node_dict[deer.t1_path]
        labelmap_node = slicer.vtkMRMLLabelMapVolumeNode()

        for seg_name in accepted:
            print(f"exporting segement {seg_name}...")
            segment = segmentation_node.GetSegmentation().GetSegment(seg_name)
            segments = vtk.vtkStringArray()
            segments.SetNumberOfValues(1)
            segments.SetValue(0,segment.GetName())
            
            slicer.mrmlScene.AddNode(labelmap_node)
            slicer.vtkSlicerSegmentationsModuleLogic.ExportSegmentsToLabelmapNode(segmentation_node, segments, labelmap_node, volume)
            
            myStorageNode = labelmap_node.CreateDefaultStorageNode()
            myStorageNode.SetFileName(os.path.join(deer.slicer_out_dir,f"{seg_name}.nii.gz"))
            myStorageNode.WriteData(labelmap_node)
            slicer.mrmlScene.RemoveNode(myStorageNode)

        slicer.mrmlScene.RemoveNode(labelmap_node)


        #close deer
        slicer.modules.DeerSegmentorWidget.logic.close_active_deer(True)
    