#include "ota_update.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ota_update";

static esp_err_t ota_http_event(esp_http_client_event_t *evt)
{
    switch (evt->event_id) {
    case HTTP_EVENT_ON_CONNECTED:
        ESP_LOGI(TAG, "HTTP connected");
        break;
    case HTTP_EVENT_ERROR:
        ESP_LOGE(TAG, "HTTP error");
        break;
    default:
        break;
    }
    return ESP_OK;
}

static void ota_task(void *arg)
{
    ESP_LOGI(TAG, "Starting OTA from %s", OTA_DEFAULT_URL);

    esp_http_client_config_t http_cfg = {
        .url = OTA_DEFAULT_URL,
        .event_handler = ota_http_event,
        .keep_alive_enable = true,
    };

    esp_https_ota_config_t ota_cfg = {
        .http_config = &http_cfg,
    };

    esp_err_t ret = esp_https_ota(&ota_cfg);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA succeeded, rebooting...");
        esp_restart();
    } else {
        ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(ret));
    }

    vTaskDelete(NULL);
}

esp_err_t ota_update_start(void)
{
    BaseType_t ret = xTaskCreate(ota_task, "ota_task", 8192, NULL, 5, NULL);
    return (ret == pdPASS) ? ESP_OK : ESP_ERR_NO_MEM;
}
