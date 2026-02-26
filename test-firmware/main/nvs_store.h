#pragma once

#include "esp_err.h"
#include <stdbool.h>

esp_err_t nvs_store_init(void);
esp_err_t nvs_store_set_wifi(const char *ssid, const char *password);
bool      nvs_store_get_wifi(char *ssid, size_t ssid_len, char *password, size_t pass_len);
esp_err_t nvs_store_erase_wifi(void);
