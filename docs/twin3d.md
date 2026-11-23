# Smart Hub — the 3D digital twin

The 3D view of the dashboard (`dashboard/fyp-research-twin/public/twin3d/`) shows the
building of this project — 25 simulated rooms and 1 live room (Office A on the ESP32) —
as a modern five-storey building on a city site, with three ways to look at it:
the whole **building**, one **floor**, and one **room**. Everything it shows comes from the
edge brain (the same data as the panels); the 3D view has no connection of its own.

## 1. Architectural concept

A 30 m × 20 m, five-storey mixed-use building ("Smart Hub"), 3.5 m floor to floor — the plate,
floor heights and every room rectangle are those of `twin/building_config.py`, which the
edge brain sends to the 3D view (`CONFIG` message), so the model cannot drift from the simulation.

| Element | Design |
|---|---|
| Ground floor (retail & lobby) | Full-height shopfront glazing on a dark stone plinth; cantilevered entrance canopy (4.6 m) with timber soffit, downlights and the building sign over the lobby doors; café terrace on the forecourt |
| Levels 1–2 (health, offices) | Curtain wall with angled bronze fins on the sunny south and west; horizontal aluminium blades on the north; white slab-edge bands projecting 0.9 m (south) as sunshades |
| Levels 3–4 (apartments, penthouse) | Deep south balconies (2.1 m) with glass balustrades, timber soffits, planters and outdoor furniture; white vertical panels framing the west glazing |
| East elevation | Vertical timber louvre screen; stone-clad stair/lift core with a glazed stair slot |
| West elevation | Living green wall (levels 1–3) |
| Roof | Solar canopy (PV modules on a steel frame) over a roof garden; screened HVAC condensers whose fans turn with the building's actual mean cooling output |
| Facade per room | Generated from the rooms: frosted glass in front of restrooms, louvred metal in front of the server room, clear glass elsewhere |

**Site** (x = east, z = south; context only, no data meaning): a four-lane boulevard on the
entrance side with a planted median of coconut palms, lane markings, zebra crossings on all four
arms of a signalised junction with the side street (cars drive on the left and stop at the
lights), a drop-off lay-by, sidewalks with street trees and LED street lights, a bus shelter,
a forecourt with café seating, reflecting pool, planters and bike racks, a parking lot with EV
chargers, a garden with paths and benches on the north, and neighbouring buildings (low-rise
along the streets, towers behind, a skyline fading into the haze). Pedestrians walk the sidewalks.

**Light**: a physical sky; "Live" places the sun for Colombo (6.93 N, 79.85 E) at the
simulated date and time and greys the sky with the simulated cloud cover. Day / Golden hour /
Night presets change only the picture (the toolbar says so), never the simulation. Reflections
come from the same sky; at night the street lights, neighbouring windows and the building's own
lit rooms glow.

## 2. The three views

| View | What you see | How to get there |
|---|---|---|
| **Building** | The exterior and site from a three-quarter view. Hover a room for its name and values; click to select (the panels follow); double-click for its floor. Floor tags on the facade open floor views. The live room has a pulsing cyan frame and a "LIVE · Office A" beacon with the board's real status (red when the board is not connected). "Reveal floor" hides the floors above one floor to see into it from outside. | Start page, **Building** button, Esc from a floor |
| **Floor** | The selected floor alone (floors above removed), walls cut at 1.55 m, furniture, people, light pools, a card per room with people, temperature, lights and AC. Click a card to select the room, click again (or double-click) to enter it. | **Floor** button, floor pills G–L4, floor name in the building list, double-click in building view |
| **Room** | Only the selected room on its floor plate: its own windows, walls (the walls between you and the room drop to 0.95 m automatically as you orbit), furniture, people, ceiling AC units on a see-through ceiling, thermostat, light fixtures and area lights, daylight and shadows. Hotspots point at the thermostat, the AC, the lights and (in Office A) the ESP32 sensor node. **Eye level** puts the camera inside the room. | **Room** button, room picker, double-click a room in the building list or in 3D, **Enter room** in the context panel |

Camera: smooth flights through a raised midpoint (never through slabs), orbit/zoom/pan limits
per view, the target is kept inside the current building/floor/room, **Reset** returns to the
view's default camera, and presets per view (building: hero, street level, corner, garden,
aerial; floor: isometric, plan, low, east; room: cutaway overview, side, top, eye level).
Esc goes up one level. Resizing the window resizes the canvas and camera.

**Presentation mode** fills the screen with the 3D view, adds a top bar (simulated clock, the AI
master switch, power with AI vs AI off, saving now, people) and enlarges the labels. **Auto tour**
flies building → street → floor L2 → live room → gym (airflow on) → café → penthouse (eye level)
→ aerial, and stops as soon as you touch the camera.

## 3. What drives what (no invented values)

| In 3D | Source in the edge-brain state |
|---|---|
| People in a simulated room | `ground_truth.true_occupancy` (the simulator's truth; the panels label it as such). People walk in from a door when the number rises and walk out when it falls, then do what the room is for (desk work, meetings, cooking, running on a treadmill, yoga, sleeping, browsing…). |
| People in the live room | `presence.fused_presence` from the board (PIR + mmWave): one person while presence is reported, none otherwise — the sensor cannot count people, so no count is shown. Nobody while the board is not connected. |
| Lights (fixtures, light pools, glowing windows at night) | `device_state.light_level` (simulated rooms) / LED PWM ÷ 255 from the board (live room) |
| Screens at desks | on while the room has people |
| AC units: status LED, flap, airflow amount and speed | `device_state.hvac_mode` and `hvac_speed` (cooling fraction of the AC in the simulation) / fan PWM ÷ 255 from the board. OFF/ECO → no supply air. Ventilation boost (`control.vent_boost`) adds a green fresh-air stream. |
| Thermostat display and hotspot | `sensors.Temperature`, `device_state.setpoint`, `control.hvac_action` |
| Temperature layer | the existing temperature overlay colours: one colour per room from its average temperature (the model has one temperature per room, so no spatial field is drawn) |
| Other overlays (comfort, power density, AI vs truth) | the existing overlay colours from the dashboard |
| Roof condenser fans | mean cooling fraction of the simulated rooms |
| LIVE frame / beacon colour | `hardware.connected` / `hardware.state` |

The airflow layer is labelled **qualitative — not CFD**: particles leave each unit's outlets,
run along the ceiling and fall as cool air, and room air returns to the unit's grille; only the
amount and speed come from data. The number of AC units drawn in a room is a visual choice — the
simulation models one AC (with its capacity) per room.

## 4. Room mapping (25 simulated + 1 live)

Plan rectangles are metres from the building's south-west corner (x east, z north), exactly as in
`twin/building_config.py`. Floors: 0 = ground … 4 = penthouse.

| Floor | Room ID | Name | Type | Plan rectangle (m) | Data | Interior | AC shown |
|---|---|---|---|---|---|---|---|
| 0 | `f0_lobby` | Main Lobby | lobby | x 0–15, z 0–12 | simulated | reception desk, feature wall, lounge seating, security gates | ceiling cassettes ×4 |
| 0 | `f0_cafe` | Coffee Shop | shop | x 15–30, z 0–12 | simulated | café: counter, espresso bar, display case, tables, window bar | ceiling cassettes ×4 |
| 0 | `f0_retail_a` | Retail Store A | shop | x 0–10, z 12–20 | simulated | fashion store: clothes rails, shelving, display table, checkout | ceiling cassettes ×2 |
| 0 | `f0_retail_b` | Retail Store B | shop | x 10–20, z 12–20 | simulated | tech store: demo tables with devices, wall screen, checkout | ceiling cassettes ×2 |
| 0 | `f0_bathroom` | Public Restrooms | bathroom | x 20–30, z 12–20 | simulated | WC cubicles, vanity with basins, hand dryer | wall split unit |
| 1 | `f1_gym` | Fitness Center | gym | x 0–20, z 0–12 | simulated | treadmills, bikes, benches, free weights, mirror wall | ceiling cassettes ×5 |
| 1 | `f1_spa` | Spa & Wellness | lounge | x 20–30, z 0–12 | simulated | spa: treatment beds, relaxation loungers, reception | ceiling cassettes ×3 |
| 1 | `f1_studio` | Yoga Studio | gym | x 0–15, z 12–20 | simulated | yoga studio: mats, mirror wall, barre | ceiling cassettes ×3 |
| 1 | `f1_lockers` | Locker Rooms | bathroom | x 15–30, z 12–20 | simulated | lockers, benches, showers, vanity | ceiling cassettes ×3 |
| 2 | `f2_office_a` | Office A | office | x 0–14, z 0–12 | **LIVE (ESP32)** | open-plan desk benches with monitors, break-out sofa, storage | ceiling cassettes ×4 |
| 2 | `f2_meeting_b` | Meeting Room B | meeting | x 14–24, z 0–8 | simulated | meeting table for 8, display wall, whiteboard | ceiling cassettes ×2 |
| 2 | `f2_kitchen` | Kitchen | kitchen | x 24–30, z 0–8 | simulated | kitchen run, high table with stools, water dispenser | wall split unit |
| 2 | `f2_corridor` | Main Corridor | corridor | x 14–30, z 8–12 | simulated | art, plants, bench; walking people | ceiling cassettes ×1 |
| 2 | `f2_office_b2` | Office B2 | office | x 0–14, z 12–20 | simulated | open-plan desk benches with monitors, break-out sofa, storage | ceiling cassettes ×2 |
| 2 | `f2_server` | Server Room | server | x 14–30, z 12–20 | simulated | two rack rows with cold aisle, CRAC units | ceiling cassettes ×3 |
| 3 | `f3_apt1_living` | Apt 1 - Living | residential | x 0–10, z 0–12 | simulated | sofa + TV, dining, open kitchen with island, bookshelf | ceiling cassettes ×3 |
| 3 | `f3_apt1_bed` | Apt 1 - Bedroom | residential | x 10–15, z 0–12 | simulated | bed, wardrobe, desk | wall split unit |
| 3 | `f3_apt2_living` | Apt 2 - Living | residential | x 15–25, z 0–12 | simulated | sofa + TV, dining, open kitchen with island, bookshelf | ceiling cassettes ×3 |
| 3 | `f3_apt2_bed` | Apt 2 - Bedroom | residential | x 25–30, z 0–12 | simulated | bed, wardrobe, desk | wall split unit |
| 3 | `f3_apt1_bath` | Apt 1 - Bathroom | bathroom | x 0–5, z 12–20 | simulated | bathtub, shower, vanity, WC | wall split unit |
| 3 | `f3_hallway` | Hallway | corridor | x 5–25, z 12–20 | simulated | art, plants, bench; walking people | ceiling cassettes ×4 |
| 3 | `f3_apt2_bath` | Apt 2 - Bathroom | bathroom | x 25–30, z 12–20 | simulated | bathtub, shower, vanity, WC | wall split unit |
| 4 | `f4_lounge` | Penthouse Lounge | residential | x 0–20, z 0–12 | simulated | sofa + TV, dining, open kitchen with island, bookshelf, grand piano | ceiling cassettes ×5 |
| 4 | `f4_master` | Master Bedroom | residential | x 20–30, z 0–12 | simulated | bed, wardrobe, desk, armchair | ceiling cassettes ×3 |
| 4 | `f4_terrace` | Roof Terrace | lobby | x 0–20, z 12–20 | simulated | winter-garden terrace: planters, loungers, dining | ceiling cassettes ×4 |
| 4 | `f4_bath` | Luxury Bath | bathroom | x 20–30, z 12–20 | simulated | bathtub, shower, vanity, WC (luxury) | wall split unit |

Doors are placed automatically where two rooms share an edge: into corridors, lobbies and the
terrace, within an apartment, between the wellness rooms (floor 1 has no corridor), and every
room gets at least one door. Glass partitions are used between offices, meeting room and corridor.

## 5. Messages between the dashboard and the 3D view

Page → 3D: `CONFIG {config}` (once), `SYNC_STATE {rooms, clock, system, hardware, ai_enabled, seq}`
(every update), `LINK_STATUS`, `PING`, and `UI_COMMAND` with `setView {mode, floor, room, eye, preset}`,
`selectRoom`, `isolateFloor`, `setOverlay`, `setLayers {people, airflow, labels}`, `setLighting`,
`setQuality`, `cameraPreset`, `resetCamera`, `setPresentation`, `tour`.

3D → page: `TWIN_READY {hasConfig}` (repeated until the configuration arrives), `ROOM_SELECTED`,
`VIEW_CHANGED {mode, floor, room, eye, preset, isolated}`, `TWIN_SYNC_REPORT` (rooms matched, shown
in the footer as "3D rooms 26/26"), `TWIN_STATS {fps, calls, triangles, quality}`, `TOUR_STEP`.

`twin3d/index.html?standalone=1` runs the 3D view on its own against the edge brain
(`&edge=http://host:8001`), for testing without the dashboard.

## 6. Performance

- Static geometry is merged per material; plain-coloured materials share a few vertex-colour
  materials, so a furnished room costs about ten draw calls.
- Trees, palms, shrubs, cars and people are instanced (people: 11 draw calls in total, posed on
  the CPU through a small joint hierarchy; only the used slots are drawn).
- Airflow is computed in the vertex shader (no per-particle CPU work), one draw call per room.
- Room view builds the focused room's walls and windows on demand and disposes them when you leave;
  area lights exist only for the room being viewed.
- Shadows update at about 20 Hz; quality "High" (2× pixel ratio, 4096 shadow map, ambient
  occlusion) drops to "Fast" automatically when the frame rate stays below 26 fps.
- Measured on the test machine (software WebGL, so frame rates are not meaningful there):
  about 1,200 draw calls / 1.2 M triangles per frame in building view, 630 in floor view,
  330 in room view (shadow pass included).

## 7. Files

| File | What |
|---|---|
| `public/twin3d/index.html`, `main.js` | App: renderer, post-processing, views, camera, picking, labels, protocol |
| `public/twin3d/scene/environment.js` | Sky, sun for Colombo, reflections, day/golden/night |
| `public/twin3d/scene/site.js`, `vegetation.js`, `cars.js` | Streets, junction, parking, plaza, landscape, neighbours, traffic |
| `public/twin3d/scene/building.js` | Envelope generated from the configuration |
| `public/twin3d/scene/interiors.js`, `furniture.js` | Walls, doors, finishes, ceilings, lights, furnished layouts and people spots |
| `public/twin3d/scene/people.js` | Occupants: poses, walking in and out, matching the data |
| `public/twin3d/scene/hvac.js` | AC units, thermostat, ESP32 node, airflow layer |
| `public/twin3d/lib/materials.js`, `batch.js` | Procedural textures and materials; geometry merging |
| `public/twin3d/vendor/three/` | three.js r170 and the add-ons used (served locally, no internet needed) |
| `src/components/3d/VanillaTwinWrapper.tsx` | Hosts the 3D view, forwards data, follows selections |
| `src/components/3d/TwinControls.tsx`, `TwinContext.tsx`, `PresentationHud.tsx` | View navigator, scene toolbar, context panel, presentation bar |

The earlier 3D app (`public/3d-twin/`) was replaced by this one and is not part of the release.

## 8. Known limitations

- Furniture, people's activities and the number of AC units are a visual interpretation of the
  room type; occupancy numbers, lighting levels, AC state and temperatures are data.
- People walk straight lines between a door, an aisle point and their place; in tightly furnished
  rooms a walker can brush furniture while entering or leaving.
- The outdoor scene (traffic, pedestrians, parked cars) is ambience and not linked to any data.
- Lighting presets other than "Live" do not change the simulation, so at a "Night" preset the
  building's lights still follow the simulated time of day.
- Frame rates could only be checked on a machine without a GPU; on a laptop without a dedicated
  GPU use "Fast" quality (it is chosen automatically when needed).

## 9. Viva demonstration sequence (about 5 minutes)

1. Open http://localhost:3000, click **Presentation** (top-right of the 3D view). Building view:
   point out the architecture, the site, the LIVE beacon on Office A and its real status.
2. Switch **AI CONTROL** off and on in the top bar: power with AI vs AI off and the saving update.
3. Click floor pill **L2**: the floor cutaway with a card per room; Office A carries LIVE.
4. Click **Meeting Room B** twice: inside, people at the table, the AC hotspot, the thermostat.
   Turn on **Airflow** (wind icon): supply jets and return air follow the AC's real output.
   Turn on **Temperature**. Use the eye icon for eye level, then Esc back to the floor.
5. Open **Office A**: with the board (or the test sender) it shows the measured CO₂, light,
   humidity, the fan PWM as AC airflow and presence; unplug it and within 10 s the room shows
   "board not connected" and no values.
6. Run **Viva demo** step 1 or 2 (header button): the 3D view goes into the room while the
   scenario plays, and the AI decisions appear in the decision log.
7. Press Esc twice to return to the building, or start **Auto tour** for a hands-free close.
