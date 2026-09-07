idf_component_register(SRCS "single_csi_main.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_wifi esp_event esp_netif esp_timer nvs_flash lwip)
