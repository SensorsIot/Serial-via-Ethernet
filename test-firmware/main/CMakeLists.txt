idf_component_register(SRCS "app_main.c"
                            "nvs_store.c"
                            "udp_log.c"
                            "wifi_prov.c"
                            "ble_nus.c"
                            "ota_update.c"
                            "http_server.c"
                       INCLUDE_DIRS "."
                       EMBED_FILES "portal.html")
