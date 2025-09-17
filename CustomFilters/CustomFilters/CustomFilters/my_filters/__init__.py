from .rankDownsampleFilter import *
from .linearIntensityTransformFilter import *
from .autocropFilter import *
from .differenceOfGaussiansFilter import *
from .paraview_preprocessing_filter import *
# from .dummyFilter import *
# implemented_filters = [RankDownsampleFilter, LinearIntensityTransformFilter, DummyFilter]
implemented_filters = [RankDownsampleFilter, LinearIntensityTransformFilter, AutocropFilter, DoGFilter, ParaviewPreprocessingFilter]