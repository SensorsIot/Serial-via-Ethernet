#pragma once

#include "esp_err.h"

esp_err_t udp_log_init(const char *host, uint16_t port);
