cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(RTCompare)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/RTCompare")
set(EXTENSION_CATEGORY "Examples")
set(EXTENSION_CONTRIBUTORS "Daniel Fajtai (all by me)")
set(EXTENSION_DESCRIPTION "This is a simple extension for comparing RT segmentations on multiple subjects.")
set(EXTENSION_ICONURL "https://www.example.com/Slicer/Extensions/RTCompare.png")
set(EXTENSION_SCREENSHOTURLS "https://www.example.com/Slicer/Extensions/RTCompare/Screenshots/1.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(RTCompare)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
