cmake_minimum_required(VERSION 3.20)
project(TangerineShell LANGUAGES CXX)
include(CTest)

if(NOT WIN32)
    message(FATAL_ERROR "TangerineShell is a Windows-only COM shell extension")
endif()

if(BUILD_TESTING)
    add_executable(ValidateShell tests/ValidateShell.cpp)
    target_compile_features(ValidateShell PRIVATE cxx_std_17)
    target_link_libraries(ValidateShell PRIVATE ole32 shell32 uuid user32)
    if(MSVC)
        set_property(TARGET ValidateShell PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
        target_compile_options(ValidateShell PRIVATE /W4 /WX /permissive- /utf-8)
    else()
        target_compile_options(ValidateShell PRIVATE -Wall -Wextra -Werror)
        target_link_options(ValidateShell PRIVATE -static -municode)
    endif()
    add_test(NAME shell_selection_contract COMMAND ValidateShell $<TARGET_FILE:TangerineShell>)
endif()

add_library(TangerineShell SHARED TangerineShell.cpp TangerineShell.def)
target_compile_features(TangerineShell PRIVATE cxx_std_17)
target_link_libraries(TangerineShell PRIVATE ole32 shell32 advapi32 user32)
set_target_properties(TangerineShell PROPERTIES
    PREFIX ""
    OUTPUT_NAME "TangerineShell"
    CXX_EXTENSIONS OFF)

if(MSVC)
    set_property(TARGET TangerineShell PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    target_compile_options(TangerineShell PRIVATE /W4 /WX /permissive- /utf-8)
    target_link_options(TangerineShell PRIVATE /INCREMENTAL:NO)
else()
    target_compile_options(TangerineShell PRIVATE -Wall -Wextra -Werror)
    target_link_options(TangerineShell PRIVATE -static)
endif()
