cmake_minimum_required(VERSION 3.13.4)

project(deer_segmentor)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/deer_segmentor")
set(EXTENSION_CATEGORY "Segmentation")
set(EXTENSION_CONTRIBUTORS "Daniel Fajtai (Medicopus Nonprofit Ltd.)")
set(EXTENSION_DESCRIPTION "This is a helper extension for the local deer liver project.")
set(EXTENSION_ICONURL "http://www.example.com/Slicer/Extensions/deer_segmentor.png")
set(EXTENSION_SCREENSHOTURLS "http://www.example.com/Slicer/Extensions/deer_segmentor/Screenshots/1.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(DeerSegmentor)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
