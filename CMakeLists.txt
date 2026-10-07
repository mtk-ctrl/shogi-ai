cmake_minimum_required(VERSION 3.16)
project(shogi_ai_wrapper NONE)

find_package(Python3 REQUIRED COMPONENTS Interpreter)

add_custom_target(shogi-ai ALL
  COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/scripts/build.py --output ${CMAKE_BINARY_DIR}/shogi-ai
  WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
  COMMENT "Build shogi-ai with the repository build script"
  VERBATIM
)
