#pragma once

#include "esp_err.h"

#define OTA_DEFAULT_URL "http://192.168.0.87:8080/firmware/test-firmware/wb-test-firmware.bin"

esp_err_t ota_update_start(void);
