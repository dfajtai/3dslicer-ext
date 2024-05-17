import numpy as np
import vtk
import qt
import ctk

import slicer


from numpy.lib.stride_tricks import as_strided

from .customFilter import CustomFilter, CustomFilterUI, sitk, sitkUtils




class DummyFilter(CustomFilter):
  filter_name = "Dummy Filter"
  short_description = "Just a dummy"
  tooltip = "Just a dummy"

  def __init__(self):
    super().__init__()
    self.filter_name = DummyFilter.filter_name
    self.short_description = DummyFilter.short_description
    self.tooltip = DummyFilter.tooltip
    self.input_image_range = [None,None]
    
    

  def createUI(self, parent):
    parametersFormLayout = super().createUI(parent)
    UI = CustomFilterUI(parent = parametersFormLayout)

    dummy_btn = qt.QPushButton("Dummy btn")
    UI.widgets.append(dummy_btn)
    
    UI.addWidgetWithToolTip(dummy_btn,{"tip":"Dummy btn clicked"})
    dummy_btn.connect('clicked(bool)', self.on_dummy_btn)
    UI.widgetConnections.append((dummy_btn, 'clicked(bool)'))
    
    # clip widget    
    UI.clip_widget = ctk.ctkRangeWidget()
    UI.widgets.append(UI.clip_widget)
    
    UI.addWidgetWithToolTipAndLabel(UI.clip_widget,{"tip":"Values outside the 'clip range' will be set to the given 'clip range'",
                      "label":"Input clip range"})
    UI.clip_widget.enabled = False
    
    UI.clip_widget.connect("valuesChanged(double,double)",
                                lambda min,max, widget=UI.clip_widget, name = 'clip': self.onRangeChanged(name,widget,min,max))
    UI.widgetConnections.append((UI.clip_widget, 'valuesChanged(double,double)'))
    
    self.UI = UI
    return UI
  
  
    
  def on_dummy_btn(self):
      print("Dummy btn clicked")
      
  def onRangeChanged(self, name, widget, min_val, max_val):
    if name == "clip":
      print(f"clip: {min_val} - {max_val}")
 
  def execute(self, ui = None):
    super().execute(ui = ui)