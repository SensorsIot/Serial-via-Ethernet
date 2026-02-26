#include "wifi_prov.h"
#include "nvs_store.h"
#include "esp_wifi.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "lwip/inet.h"
#include "dns_server.h"
#include "cJSON.h"
#include <string.h>

static const char *TAG = "wifi_prov";

#define AP_SSID        "WB-Test-Setup"
#define STA_MAX_RETRY  10

extern const char portal_html_start[] asm("_binary_portal_html_start");
extern const char portal_html_end[]   asm("_binary_portal_html_end");

static int s_retry_count = 0;
static bool s_sta_connected = false;
static httpd_handle_t s_server = NULL;

/* ── Event handlers ────────────────────────────────────────────── */

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    if (base == WIFI_EVENT) {
        switch (id) {
        case WIFI_EVENT_STA_START:
            esp_wifi_connect();
            break;
        case WIFI_EVENT_STA_DISCONNECTED:
            s_sta_connected = false;
            if (s_retry_count < STA_MAX_RETRY) {
                s_retry_count++;
                ESP_LOGW(TAG, "STA disconnect, retry %d/%d", s_retry_count, STA_MAX_RETRY);
                esp_wifi_connect();
            } else {
                ESP_LOGE(TAG, "STA failed after %d retries", STA_MAX_RETRY);
            }
            break;
        case WIFI_EVENT_AP_STACONNECTED: {
            wifi_event_ap_staconnected_t *e = data;
            ESP_LOGI(TAG, "AP: station " MACSTR " joined", MAC2STR(e->mac));
            break;
        }
        default:
            break;
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = data;
        ESP_LOGI(TAG, "STA got IP: " IPSTR, IP2STR(&e->ip_info.ip));
        s_sta_connected = true;
        s_retry_count = 0;
    }
}

/* ── Captive portal HTTP handlers ──────────────────────────────── */

static esp_err_t portal_get_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, portal_html_start, portal_html_end - portal_html_start);
    return ESP_OK;
}

static esp_err_t connect_post_handler(httpd_req_t *req)
{
    char buf[256];
    int len = httpd_req_recv(req, buf, sizeof(buf) - 1);
    if (len <= 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "No body");
        return ESP_FAIL;
    }
    buf[len] = '\0';

    cJSON *json = cJSON_Parse(buf);
    if (!json) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid JSON");
        return ESP_FAIL;
    }

    const char *ssid = cJSON_GetStringValue(cJSON_GetObjectItem(json, "ssid"));
    const char *pass = cJSON_GetStringValue(cJSON_GetObjectItem(json, "password"));

    if (!ssid || strlen(ssid) == 0) {
        cJSON_Delete(json);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing SSID");
        return ESP_FAIL;
    }

    nvs_store_set_wifi(ssid, pass ? pass : "");
    cJSON_Delete(json);

    httpd_resp_set_type(req, "application/json");
    httpd_resp_sendstr(req, "{\"status\":\"ok\",\"message\":\"Rebooting...\"}");

    ESP_LOGI(TAG, "Credentials saved, rebooting in 1s...");
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
    return ESP_OK;
}

static esp_err_t redirect_handler(httpd_req_t *req, httpd_err_code_t err)
{
    httpd_resp_set_status(req, "302 Temporary Redirect");
    httpd_resp_set_hdr(req, "Location", "/");
    httpd_resp_send(req, "Redirect to captive portal", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
}

static void start_portal_server(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_open_sockets = 7;
    config.lru_purge_enable = true;

    if (httpd_start(&s_server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server");
        return;
    }

    static const httpd_uri_t portal_get = {
        .uri = "/", .method = HTTP_GET, .handler = portal_get_handler
    };
    static const httpd_uri_t connect_post = {
        .uri = "/connect", .method = HTTP_POST, .handler = connect_post_handler
    };

    httpd_register_uri_handler(s_server, &portal_get);
    httpd_register_uri_handler(s_server, &connect_post);
    httpd_register_err_handler(s_server, HTTPD_404_NOT_FOUND, redirect_handler);

    ESP_LOGI(TAG, "Portal HTTP server started");
}

/* ── STA mode ──────────────────────────────────────────────────── */

static esp_err_t start_sta(const char *ssid, const char *password)
{
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL));

    wifi_config_t wifi_cfg = {};
    strncpy((char *)wifi_cfg.sta.ssid, ssid, sizeof(wifi_cfg.sta.ssid) - 1);
    strncpy((char *)wifi_cfg.sta.password, password, sizeof(wifi_cfg.sta.password) - 1);

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "STA mode, connecting to '%s'", ssid);
    return ESP_OK;
}

/* ── AP mode with captive portal ───────────────────────────────── */

static esp_err_t start_ap(void)
{
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL));

    wifi_config_t wifi_cfg = {
        .ap = {
            .ssid = AP_SSID,
            .ssid_len = strlen(AP_SSID),
            .max_connection = 4,
            .authmode = WIFI_AUTH_OPEN,
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    /* DHCP Option 114 for iOS captive portal detection */
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
    if (netif) {
        esp_netif_ip_info_t ip_info;
        esp_netif_get_ip_info(netif, &ip_info);
        char ip_str[16];
        inet_ntoa_r(ip_info.ip.addr, ip_str, sizeof(ip_str));

        char uri[32];
        snprintf(uri, sizeof(uri), "http://%s", ip_str);

        esp_netif_dhcps_stop(netif);
        esp_netif_dhcps_option(netif, ESP_NETIF_OP_SET,
                               ESP_NETIF_CAPTIVEPORTAL_URI, uri, strlen(uri));
        esp_netif_dhcps_start(netif);
    }

    /* Suppress noisy HTTP server warnings from captive portal redirects */
    esp_log_level_set("httpd_uri", ESP_LOG_ERROR);
    esp_log_level_set("httpd_txrx", ESP_LOG_ERROR);
    esp_log_level_set("httpd_parse", ESP_LOG_ERROR);

    start_portal_server();

    dns_server_config_t dns_cfg = DNS_SERVER_CONFIG_SINGLE("*", "WIFI_AP_DEF");
    start_dns_server(&dns_cfg);

    ESP_LOGI(TAG, "AP mode: SSID='%s', portal at 192.168.4.1", AP_SSID);
    return ESP_OK;
}

/* ── Public API ────────────────────────────────────────────────── */

esp_err_t wifi_prov_init(void)
{
    char ssid[33] = {0};
    char pass[65] = {0};

    if (nvs_store_get_wifi(ssid, sizeof(ssid), pass, sizeof(pass))) {
        ESP_LOGI(TAG, "Found stored WiFi credentials");
        return start_sta(ssid, pass);
    }

    ESP_LOGI(TAG, "No WiFi credentials, starting AP provisioning");
    return start_ap();
}

void wifi_prov_reset(void)
{
    ESP_LOGW(TAG, "WiFi reset requested, erasing credentials and rebooting...");
    nvs_store_erase_wifi();
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}

bool wifi_prov_is_connected(void)
{
    return s_sta_connected;
}
