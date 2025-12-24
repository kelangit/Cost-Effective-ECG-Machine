file(GLOB MY_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/*.c")

add_library(hal STATIC ${MY_SOURCES})

target_include_directories(hal PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# --- Add libgpiod (via pkg-config) + pthread, and make them transitive ---
#find_package(PkgConfig REQUIRED)
#pkg_check_modules(GPIOD REQUIRED libgpiod)
find_package(Threads REQUIRED)

# Propagate gpiod’s include dirs to consumers (PUBLIC) so any hal headers
# that include <gpiod.h> are visible from the app too.
#target_include_directories(hal PUBLIC ${GPIOD_INCLUDE_DIRS})

# Link gpiod and pthread PUBLIC so executables that link hal get them automatically
target_link_libraries(hal PUBLIC Threads::Threads)