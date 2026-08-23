# Reusable Zephyr source fragment for the receiver-effects application.
# The real receiver application must call add_subdirectory() after
# find_package(Zephyr); this fragment is deliberately not a standalone app.

if(NOT TARGET app)
    message(FATAL_ERROR
        "receiver-effects epoch storage must be added from a Zephyr app after find_package(Zephyr)"
    )
endif()

target_sources(app PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src/mw_epoch_record.c
    ${CMAKE_CURRENT_LIST_DIR}/src/mw_epoch_store.c
    ${CMAKE_CURRENT_LIST_DIR}/src/mw_epoch_nvs.c
)

target_include_directories(app PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/src
)
