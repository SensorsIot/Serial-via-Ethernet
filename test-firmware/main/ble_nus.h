#pragma once

#include "esp_err.h"
#include <stdbool.h>

esp_err_t ble_nus_init(void);
bool      ble_nus_is_connected(void);
