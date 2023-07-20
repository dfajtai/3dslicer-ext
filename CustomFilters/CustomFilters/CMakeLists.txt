cmake_minimum_required(VERSION 3.16.3...3.19.7 FATAL_ERROR)

project(Custom Filters Filters)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://www.slicer.org/wiki/Documentation/Nightly/Extensions/CustomFilters")
set(EXTENSION_CATEGORY "Filtering")
set(EXTENSION_CONTRIBUTORS "Daniel Fajtai (-)")
set(EXTENSION_DESCRIPTION "This is a custom extension which iplements various custom filters.")
set(EXTENSION_ICONURL "https://www.example.com/Slicer/Extensions/CustomFilters.png")
set(EXTENSION_SCREENSHOTURLS "https://www.example.com/Slicer/Extensions/CustomFilters/Screenshots/1.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(CustomFilters)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
