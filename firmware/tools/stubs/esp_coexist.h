#pragma once
// Host-side stub of ESP-IDF esp_coexist.h for the firmware syntax check.
#include <stdint.h>
typedef int esp_err_t;
typedef enum { ESP_COEX_PREFER_WIFI = 0, ESP_COEX_PREFER_BT, ESP_COEX_PREFER_BALANCE, ESP_COEX_PREFER_NUM } esp_coex_prefer_t;
inline esp_err_t esp_coex_preference_set(esp_coex_prefer_t) { return 0; }
