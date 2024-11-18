import numpy as np
import sitkUtils
import SimpleITK as sitk
import itertools
from collections import OrderedDict
import copy

import slicer

from typing import Dict, Union, Optional, Sequence, Set, List

def computeQualityMeasures(lP: np.ndarray,
                           lT: np.ndarray,
                           spacing: np.ndarray,
                           metrics_names: Union[Sequence, set, None] = None,
                           fullyConnected=True,
                           return_distances = False,
                           return_contours = False):
    """

    :param lP: prediction, shape (x, y, z)
    :param lT: ground truth, shape (x, y, z)
    :param spacing: shape order (x, y, z)
    :return: metrics_names: container contains metircs names
    """
    quality = {}
    labelPred = sitk.GetImageFromArray(lP, isVector=False)
    labelPred.SetSpacing(np.array(spacing).astype(np.float64))
    labelTrue = sitk.GetImageFromArray(lT, isVector=False)
    labelTrue.SetSpacing(np.array(spacing).astype(np.float64))  # spacing order (x, y, z)

    voxel_metrics = ['dice', 'jaccard', 'precision', 'recall', 'fpr', 'fnr', 'vs', 'TP', 'TN', 'FP', 'FN']
    distance_metrics = ['hd', 'hd95', 'msd', 'mdsd', 'stdsd']
    if metrics_names is None:
        metrics_names = {'dice', 'jaccard', 'precision', 'recall', 'fpr', 'fnr', 'vs', 'hd', 'hd95', 'msd', 'mdsd',
                         'stdsd', 'TP', 'TN', 'FP', 'FN'}
    else:
        metrics_names = set(metrics_names)

    # to save time, we need to determine which metrics we need to compute
    if set(voxel_metrics).intersection(metrics_names) or not metrics_names:
        pred = lP.astype(int)  # float data does not support bit_and and bit_or
        gdth = lT.astype(int)  # float data does not support bit_and and bit_or
        fp_array = copy.deepcopy(pred)  # keep pred unchanged
        fn_array = copy.deepcopy(gdth)
        gdth_sum = np.sum(gdth)
        pred_sum = np.sum(pred)
        intersection = gdth & pred
        union = gdth | pred
        intersection_sum = np.count_nonzero(intersection)
        union_sum = np.count_nonzero(union)

        tp_array = intersection

        tmp = pred - gdth
        fp_array[tmp < 1] = 0

        tmp2 = gdth - pred
        fn_array[tmp2 < 1] = 0

        tn_array = np.ones(gdth.shape) - union

        tp, fp, fn, tn = np.sum(tp_array), np.sum(fp_array), np.sum(fn_array), np.sum(tn_array)

        smooth = 0.001
        precision = tp / (pred_sum + smooth)
        recall = tp / (gdth_sum + smooth)

        fpr = fp / (fp + tn + smooth)
        fnr = fn / (fn + tp + smooth)

        jaccard = intersection_sum / (union_sum + smooth)
        dice = 2 * intersection_sum / (gdth_sum + pred_sum + smooth)

        dicecomputer = sitk.LabelOverlapMeasuresImageFilter()
        dicecomputer.Execute(labelTrue > 0.5, labelPred > 0.5)

        quality["dice"] = dice
        quality["jaccard"] = jaccard
        quality["precision"] = precision
        quality["recall"] = recall
        quality["fnr"] = fnr
        quality["fpr"] = fpr
        quality["vs"] = dicecomputer.GetVolumeSimilarity()

        quality["TP"] = tp
        quality["TN"] = tn
        quality["FP"] = fp
        quality["FN"] = fn

    if set(distance_metrics).intersection(metrics_names) or not metrics_names:
        # Surface distance measures
        signed_distance_map = sitk.SignedMaurerDistanceMap(labelTrue > 0.5, squaredDistance=False,
                                                           useImageSpacing=True)  # It need to be adapted.

        ref_distance_map = sitk.Abs(signed_distance_map)

        ref_surface = sitk.LabelContour(labelTrue > 0.5, fullyConnected=fullyConnected)
        ref_surface_array = sitk.GetArrayViewFromImage(ref_surface)

        statistics_image_filter = sitk.StatisticsImageFilter()
        statistics_image_filter.Execute(ref_surface > 0.5)

        num_ref_surface_pixels = int(statistics_image_filter.GetSum())

        signed_distance_map_pred = sitk.SignedMaurerDistanceMap(labelPred > 0.5, squaredDistance=False,
                                                                useImageSpacing=True)

        seg_distance_map = sitk.Abs(signed_distance_map_pred)

        seg_surface = sitk.LabelContour(labelPred > 0.5, fullyConnected=fullyConnected)
        seg_surface_array = sitk.GetArrayViewFromImage(seg_surface)

        seg2ref_distance_map = ref_distance_map * sitk.Cast(seg_surface, sitk.sitkFloat32)

        ref2seg_distance_map = seg_distance_map * sitk.Cast(ref_surface, sitk.sitkFloat32)

        statistics_image_filter.Execute(seg_surface > 0.5)

        num_seg_surface_pixels = int(statistics_image_filter.GetSum())

        seg2ref_distance_map_arr = sitk.GetArrayViewFromImage(seg2ref_distance_map)
        seg2ref_distances = list(seg2ref_distance_map_arr[seg2ref_distance_map_arr != 0])
        seg2ref_distances = seg2ref_distances + list(np.zeros(num_seg_surface_pixels - len(seg2ref_distances)))
        ref2seg_distance_map_arr = sitk.GetArrayViewFromImage(ref2seg_distance_map)
        ref2seg_distances = list(ref2seg_distance_map_arr[ref2seg_distance_map_arr != 0])
        ref2seg_distances = ref2seg_distances + list(np.zeros(num_ref_surface_pixels - len(ref2seg_distances)))  #

        all_surface_distances = seg2ref_distances + ref2seg_distances

        if return_distances:
            quality["sef2ref_distances"] = seg2ref_distances
            quality["ref2seg_distances"] = ref2seg_distances

        quality["msd"] = np.mean(all_surface_distances)
        quality["mdsd"] = np.median(all_surface_distances)
        quality["stdsd"] = np.std(all_surface_distances)
        quality["hd95"] = np.percentile(all_surface_distances, 95)
        quality["hd"] = np.max(all_surface_distances)

    return quality

def calculate_stats(case_id,grouping_name, labelmap_nodes, labelmap_names, step_sizes, keep_alive = False ):
    res_metrics = []
    volumes = []
    distances = []
    
    vox_vol = np.prod(step_sizes)
    
    image_dict = {}
    for labelmap,name in zip(labelmap_nodes,labelmap_names):
        sitk_address = sitkUtils.GetSlicerITKReadWriteAddress(labelmap)
        sitk_img = sitk.ReadImage(sitk_address)
        image_data = sitk.GetArrayFromImage(sitk_img)
        image_dict[name] = image_data
        
        volumes.append(OrderedDict(case_id = case_id,grouping_name=grouping_name,
                            segmentation = name,
                            vol_ccm = np.sum(image_data>0)*vox_vol/1000.0))
        if keep_alive:
            slicer.app.processEvents()
        
        
    combinations = list(itertools.combinations(image_dict.keys(), 2))
    
    for c in combinations:
        # print(c)
        A = image_dict[c[0]]
        B = image_dict[c[1]]

        metrics = computeQualityMeasures(A,B,step_sizes, return_distances= True)

        d_ba = metrics.get("sef2ref_distances")
        d_ab = metrics.get("ref2seg_distances")

        try:
            del metrics["sef2ref_distances"]
            del metrics["ref2seg_distances"]

            dist_histogram, dist_bins = np.histogram( np.array(d_ba+d_ab),40,[0,20])
            total_dist = np.sum(dist_histogram)
            for bin,count in zip(dist_bins.tolist(),dist_histogram.tolist()):
                distances.append(OrderedDict(case_id = case_id,grouping_name=grouping_name, first = c[0],second = c[1],bin = bin,prob=count/total_dist))
        except:
            pass

        metrics["overlap_ccm"] = np.sum(np.logical_and(A>0,B>0))*(np.mean([vox_vol,vox_vol]))/1000.0
        metrics["A_but_not_B_ccm"] = np.sum(np.logical_and(A> 0, B == 0)) * vox_vol / 1000.0
        metrics["B_but_not_A_ccm"] = np.sum(np.logical_and(A == 0, B > 0)) * vox_vol / 1000.0


        for key,value in metrics.items():
            res_metrics.append(OrderedDict(case_id = case_id,grouping_name=grouping_name, first = c[0],second = c[1],metric = key, value = value))

        if keep_alive:
            slicer.app.processEvents()
        
    del image_dict
    
    
    return res_metrics, volumes, distances