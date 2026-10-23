# The 26 rooms

Generated from `twin/building_config.py` and `twin/spec.py` (`python -c "from twin.spec import build_spec"`).
Room numbers are labels: 101 is the real room, 102-126 the simulated rooms in configuration order. The room id is the
key used by the code, the API, the store and the 3D twin.

| Room | Id | Name | Floor | Type | Area m2 | Capacity | Source | AC kW | Lighting W | Design set-point C | Operating hours |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 101 | `f2_office_a` | Office A | 2 Operations (AI Monitored) | office | 168 | 10 | **real (ESP32-S3)** | 24.6 | 1344 | 24 | 7.5-18.5 weekdays |
| 102 | `f0_lobby` | Main Lobby | 0 Retail & Lobby | lobby | 180 | 15 | simulated | 26.4 | 1800 | 24 | 7-22 daily |
| 103 | `f0_cafe` | Coffee Shop | 0 Retail & Lobby | shop | 180 | 15 | simulated | 26.4 | 2520 | 23 | 9-21 daily |
| 104 | `f0_retail_a` | Retail Store A | 0 Retail & Lobby | shop | 80 | 10 | simulated | 11.7 | 1120 | 23 | 9-21 daily |
| 105 | `f0_retail_b` | Retail Store B | 0 Retail & Lobby | shop | 80 | 10 | simulated | 11.7 | 1120 | 23 | 9-21 daily |
| 106 | `f0_bathroom` | Public Restrooms | 0 Retail & Lobby | bathroom | 80 | 5 | simulated | 11.7 | 480 | 24 | 7-22 daily |
| 107 | `f1_gym` | Fitness Center | 1 Health & Recreation | gym | 240 | 20 | simulated | 35.2 | 1920 | 22 | 5-22 daily |
| 108 | `f1_spa` | Spa & Wellness | 1 Health & Recreation | lounge | 120 | 10 | simulated | 17.6 | 840 | 24 | 8-21 daily |
| 109 | `f1_studio` | Yoga Studio | 1 Health & Recreation | gym | 120 | 12 | simulated | 17.6 | 960 | 22 | 5-22 daily |
| 110 | `f1_lockers` | Locker Rooms | 1 Health & Recreation | bathroom | 120 | 10 | simulated | 17.6 | 720 | 24 | 7-22 daily |
| 111 | `f2_meeting_b` | Meeting Room B | 2 Operations (AI Monitored) | meeting | 80 | 8 | simulated | 11.7 | 800 | 24 | 7.5-18.5 weekdays |
| 112 | `f2_kitchen` | Kitchen | 2 Operations (AI Monitored) | kitchen | 48 | 4 | simulated | 7.0 | 384 | 22 | 7.5-18.5 weekdays |
| 113 | `f2_corridor` | Main Corridor | 2 Operations (AI Monitored) | corridor | 64 | 5 | simulated | 9.4 | 320 | 24 | 7-22 daily |
| 114 | `f2_office_b2` | Office B2 | 2 Operations (AI Monitored) | office | 112 | 8 | simulated | 16.4 | 896 | 24 | 7.5-18.5 weekdays |
| 115 | `f2_server` | Server Room | 2 Operations (AI Monitored) | server | 128 | 2 | simulated | 18.8 | 768 | 24 | 7.5-18.5 weekdays |
| 116 | `f3_apt1_living` | Apt 1 - Living | 3 Residential Apartments | residential | 120 | 4 | simulated | 17.6 | 720 | 24 | 17-8 daily |
| 117 | `f3_apt1_bed` | Apt 1 - Bedroom | 3 Residential Apartments | residential | 60 | 2 | simulated | 8.8 | 360 | 24 | 17-8 daily |
| 118 | `f3_apt2_living` | Apt 2 - Living | 3 Residential Apartments | residential | 120 | 4 | simulated | 17.6 | 720 | 24 | 17-8 daily |
| 119 | `f3_apt2_bed` | Apt 2 - Bedroom | 3 Residential Apartments | residential | 60 | 2 | simulated | 8.8 | 360 | 24 | 17-8 daily |
| 120 | `f3_apt1_bath` | Apt 1 - Bathroom | 3 Residential Apartments | bathroom | 40 | 1 | simulated | 5.9 | 240 | 24 | 17-8 daily |
| 121 | `f3_hallway` | Hallway | 3 Residential Apartments | corridor | 160 | 3 | simulated | 23.4 | 800 | 24 | 17-8 daily |
| 122 | `f3_apt2_bath` | Apt 2 - Bathroom | 3 Residential Apartments | bathroom | 40 | 1 | simulated | 5.9 | 240 | 24 | 17-8 daily |
| 123 | `f4_lounge` | Penthouse Lounge | 4 Penthouse Suite | residential | 240 | 8 | simulated | 35.2 | 1440 | 24 | 17-8 daily |
| 124 | `f4_master` | Master Bedroom | 4 Penthouse Suite | residential | 120 | 2 | simulated | 17.6 | 720 | 24 | 17-8 daily |
| 125 | `f4_terrace` | Roof Terrace | 4 Penthouse Suite | lobby | 160 | 15 | simulated | 23.4 | 1600 | 24 | 17-8 daily |
| 126 | `f4_bath` | Luxury Bath | 4 Penthouse Suite | bathroom | 80 | 2 | simulated | 11.7 | 480 | 24 | 17-8 daily |
