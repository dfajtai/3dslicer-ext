import vtk
import slicer
import numpy as np


def addOrUpdatePlot(filter, filter_ui, plot_widget, data):
  if not isinstance(plot_widget,slicer.qMRMLPlotWidget):
    raise TypeError("Invalid plot widget")
  
  plot_view = plot_widget.plotView()

  raise NotImplementedError("Function not iplemented")

  
def clearPlot(filter,filter_ui, plot_widget):
  pass


def addOrUpdateHistogram(filter, filter_ui, plot_widget, input_image, bins = 50, logscale = False):
  if not isinstance(plot_widget,slicer.qMRMLPlotWidget):
    raise TypeError("Invalid plot widget")
  
  if not isinstance(input_image,slicer.vtkMRMLScalarVolumeNode):
    raise TypeError("Invalid input image")
  
  input_image_name = input_image.GetName()

  plot_widget.setMRMLScene(slicer.mrmlScene)
  
  # plot_view = plot_widget.plotView()
  
  if not hasattr(filter_ui,"vtk_plot_view_node"):
    filter_ui.vtk_plot_view_node = slicer.vtkMRMLPlotViewNode()
  
  if not hasattr(filter_ui,"histogram_table_node"):
    filter_ui.histogram_table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode",f"{input_image_name} histogram table")
  else:
    slicer.mrmlScene.RemoveNode(filter_ui.histogram_table_node)
    filter_ui.histogram_table_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode",f"{input_image_name} histogram table")
  
  count,val = np.histogram(slicer.util.arrayFromVolume(input_image), bins=bins)
  if logscale:
    log_count = np.clip(np.log10(count),0,np.inf)
    slicer.util.updateTableFromArray(filter_ui.histogram_table_node, (log_count,val))
  else:
    slicer.util.updateTableFromArray(filter_ui.histogram_table_node, (count,val))
  
  filter_ui.histogram_table_node.GetTable().GetColumn(0).SetName(f"{'' if not logscale else 'log '}Count")
  filter_ui.histogram_table_node.GetTable().GetColumn(1).SetName("Intensity")
  
  if not hasattr(filter_ui,"histogram_plot_series_node"):
    filter_ui.histogram_plot_series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",f"{input_image_name} histogram")
  else:
    slicer.mrmlScene.RemoveNode(filter_ui.histogram_plot_series_node)
    filter_ui.histogram_plot_series_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotSeriesNode",f"{input_image_name} histogram")

  
  filter_ui.histogram_plot_series_node.SetAndObserveTableNodeID(filter_ui.histogram_table_node.GetID())
  filter_ui.histogram_plot_series_node.SetXColumnName("Intensity")
  filter_ui.histogram_plot_series_node.SetYColumnName(f"{'' if not logscale else 'log '}Count")
  
  filter_ui.histogram_plot_series_node.SetPlotType(slicer.vtkMRMLPlotSeriesNode.PlotTypeScatterBar)
  filter_ui.histogram_plot_series_node.SetLineStyle(slicer.vtkMRMLPlotSeriesNode.LineStyleSolid)
  filter_ui.histogram_plot_series_node.SetMarkerStyle(slicer.vtkMRMLPlotSeriesNode.MarkerStyleNone)  
  
  filter_ui.histogram_plot_series_node.SetColor(0,153,153)

  
  if not hasattr(filter_ui,"histogram_plot_chart_node"):
    filter_ui.histogram_plot_chart_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode",f"{input_image_name} histogram chart")
  else:
    slicer.mrmlScene.RemoveNode(filter_ui.histogram_plot_chart_node)
    filter_ui.histogram_plot_chart_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLPlotChartNode",f"{input_image_name} histogram chart")

  
  filter_ui.histogram_plot_chart_node.SetYAxisLogScale(False)
  filter_ui.histogram_plot_chart_node.AddAndObservePlotSeriesNodeID(filter_ui.histogram_plot_series_node.GetID())
  if logscale:
    filter_ui.histogram_plot_chart_node.SetTitle("Input image's 'log10' histogram")
  else:
    filter_ui.histogram_plot_chart_node.SetTitle("Input image's histogram")
  
  filter_ui.vtk_plot_view_node.SetPlotChartNodeID(filter_ui.histogram_plot_chart_node.GetID())
  plot_widget.setMRMLPlotViewNode(filter_ui.vtk_plot_view_node)
