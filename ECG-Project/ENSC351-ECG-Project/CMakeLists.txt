cmake_minimum_required(VERSION 3.18)
project(ECG-Project VERSION 1.0 DESCRIPTION "ECG Project" LANGUAGES C)


set(CMAKE_C_STANDARD 11)
# add_compile_options(-Wall -Werror -Wpendatic -Wextra)
# add_compile_options(-fdiagonstics-color)
set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
add_compile_options(-O0 -g3 -ggdb -fno-omit-frame-pointer)

add_subdirectory(hal)
add_subdirectory(app)