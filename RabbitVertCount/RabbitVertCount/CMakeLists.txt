cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(RabbitVertCount)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/RabbitVertCount")
set(EXTENSION_CATEGORY "Segmentation")
set(EXTENSION_CONTRIBUTORS "Daniel Fajtai (-)")
set(EXTENSION_DESCRIPTION "This is a custom module for Rabbit CT segemntation.")
set(EXTENSION_ICONURL "https://www.example.com/Slicer/Extensions/RabbitVertCount.png")
set(EXTENSION_SCREENSHOTURLS "https://www.example.com/Slicer/Extensions/RabbitVertCount/Screenshots/1.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(RabbitVertCount)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
