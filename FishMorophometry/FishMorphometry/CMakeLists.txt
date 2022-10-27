cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(JackalCraniometry)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/JackalCraniometry")
set(EXTENSION_CATEGORY "Quantification")
set(EXTENSION_CONTRIBUTORS "Daniel Fajtai (-)")
set(EXTENSION_DESCRIPTION "This is a simple extension for jackall craniometry.")
set(EXTENSION_ICONURL "https://www.example.com/Slicer/Extensions/JackalCraniometry.png")
set(EXTENSION_SCREENSHOTURLS "https://www.example.com/Slicer/Extensions/JackalCraniometry/Screenshots/1.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(JackalCraniometry)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
