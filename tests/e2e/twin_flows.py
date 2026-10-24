"""
End-to-end check of the 3D digital twin inside the real dashboard (interaction flows A-G of
the redesign brief: exterior to room, direct room navigation, HVAC inspection, comparing
rooms, the live room, resize and recovery).

Needs the edge brain (port 8001) and the dashboard (npm run dev, port 3000) running, with
simulated people in the building (e.g. fast-forward to a weekday morning first), and
Playwright for Python:  pip install playwright && playwright install chromium

    python tests/e2e/twin_flows.py

Flow E starts raspberry_pi/esp32_test_sender.py for ~30 s (shown as TEST SENDER, never as
the board). Results are printed and written to twin_flows_results.json; screenshots to
flow_*.png in the current folder.
"""
import asyncio, json, os, sys, time, subprocess
from playwright.async_api import async_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = []
def check(flow, name, ok, detail=""):
    RESULTS.append((flow, name, bool(ok), detail))
    print(("PASS" if ok else "FAIL"), flow, "-", name, ("· " + str(detail))[:160] if detail != "" else "")

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"])
        pg = await b.new_page(viewport={"width": 1600, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text[:200]}") if m.type == "error" else None)
        pg.on("requestfailed", lambda r: errs.append(f"requestfailed: {r.url[:120]} {r.failure}") if "/api/stream" not in r.url else None)
        NAV = {"t": time.time()}
        def onnav(f):
            NAV["t"] = time.time()
            print("navigated:", f.url[:80], round(time.time() - T0, 1))
        pg.on("framenavigated", onnav)
        T0 = time.time()
        await pg.goto("http://127.0.0.1:3000/", wait_until="load")
        fr = None
        for i in range(240):
            fr = next((f for f in pg.frames if "twin3d" in f.url), None)
            if fr:
                try:
                    if await fr.evaluate("() => !!(window.twin && window.twin.ready && window.twin.state)"): break
                except Exception: pass
            await pg.wait_for_timeout(500)
        for i in range(400):
            fr = next((f for f in pg.frames if "twin3d" in f.url), None)
            ok = False
            try:
                ok = await fr.evaluate("() => !!(window.twin && window.twin.ready && window.twin.state && window.twin.interiors)")
            except Exception: pass
            if ok and time.time() - NAV["t"] > 10: break
            await pg.wait_for_timeout(500)
        print("frames:", [f.url[:60] for f in pg.frames])
        await fr.evaluate("() => twin.command('setQuality','balanced')")
        T = lambda js: fr.evaluate(js)
        S = lambda js: pg.evaluate(js)
        async def tv(): return await T("() => ({...twin.view})")
        async def bc(): return (await S("() => document.querySelector('[data-testid=breadcrumb]')?.innerText || ''")).replace("\n", " ")
        async def panel_name(): return await S("() => document.querySelector('aside:last-of-type h2, aside:last-of-type h3')?.innerText || ''")
        async def wait_view(mode, timeout=20000, **kw):
            t0 = time.time()
            while time.time() - t0 < timeout / 1000:
                v = await tv()
                if v["mode"] == mode and all(v.get(k) == val for k, val in kw.items()) and not await T("() => !!twin.camTween"): return v
                await pg.wait_for_timeout(300)
            return await tv()
        WAITS = []
        async def click(testid, dbl=False):
            """Click a dashboard element; wait (up to 20 s) if it is not rendered yet - the navigation is hidden
            while the dashboard has had no data for > 3 s (a stalled tab under software WebGL)."""
            t0 = time.time()
            while time.time() - t0 < 20:
                if await S(f"() => !!document.querySelector('[data-testid={testid}]')"):
                    break
                await pg.wait_for_timeout(250)
            waited = time.time() - t0
            if waited > 0.3:
                WAITS.append((testid, round(waited, 1)))
            ev = "dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))" if dbl else "click()"
            await S(f"() => document.querySelector('[data-testid={testid}]').{ev}")
        async def shot(name):
            await pg.wait_for_timeout(2500)
            await pg.screenshot(path=f"flow_{name}.png", timeout=300000)

        # ---------------- Flow A — exterior to room
        v = await tv(); check("A", "opens on the building view", v["mode"] == "building", v)
        n_rooms = await T("() => twin.interiors.rooms.size"); n_live = await T("() => [...twin.interiors.rooms.values()].filter(r => r.live).length")
        check("A", "26 rooms in 3D (25 simulated + 1 live)", n_rooms == 26 and n_live == 1, f"{n_rooms} rooms, {n_live} live")
        await shot("A1_building")
        await click("pill-floor-2")
        v = await wait_view("floor", floor=2); check("A", "floor pill opens the floor view (L2)", v["mode"] == "floor" and v["floor"] == 2, v)
        cards = await T("() => [...twin.cards.values()].filter(c => c.obj.visible).length")
        check("A", "floor view shows a card for each room on the floor", cards == 6, f"{cards} cards")
        await shot("A2_floor")
        await T("() => twin.cards.get('f2_meeting_b').el.click()")
        await pg.wait_for_timeout(1500)
        sel = await S("() => document.querySelector('[data-testid=nav-room-f2_meeting_b]')?.className.includes('ring-1')")
        check("A", "clicking a room card selects it in the dashboard", sel)
        await T("() => twin.cards.get('f2_meeting_b').el.click()")
        v = await wait_view("room", room="f2_meeting_b"); check("A", "second click enters the room", v["mode"] == "room" and v["room"] == "f2_meeting_b", v)
        info = await T("""() => { const r = twin.interiors.rooms.get('f2_meeting_b'); return { furniture: r.furniture.children.length, units: r.hvac.units.length, people3d: twin.occupants.get(r.id).persons.filter(p => p.state !== 'leave').length, truth: r.data.ground_truth.true_occupancy, walls: twin.interiors.focus ? twin.interiors.focus.walls.length : 0 }; }""")
        check("A", "room has furniture, HVAC units and its own walls/windows", info["furniture"] > 3 and info["units"] >= 1 and info["walls"] >= 3, info)
        check("A", "people drawn = simulated true occupancy", info["people3d"] == min(info["truth"], 99), info)
        await shot("A3_room")
        await pg.keyboard.press("Escape")
        v = await wait_view("floor", floor=2); check("A", "Esc returns to the floor", v["mode"] == "floor" and v["floor"] == 2, v)
        await pg.keyboard.press("Escape")
        v = await wait_view("building"); check("A", "Esc again returns to the building", v["mode"] == "building", v)

        # ---------------- Flow B — direct room navigation
        await click("nav-floor-4")
        await wait_view("floor", floor=4)
        await pg.wait_for_timeout(1200)
        if not await S("() => !!document.querySelector('[data-testid=nav-room-f4_lounge]')"):
            # a late view message from the twin (the previous floor) can re-select that floor under heavy load
            WAITS.append(("nav-floor-4 clicked again", 0))
            await click("nav-floor-4")
            await pg.wait_for_timeout(1200)
        await click("nav-room-f4_lounge", dbl=True)
        v = await wait_view("room", room="f4_lounge"); check("B", "double-click in the room list opens that room", v["mode"] == "room" and v["room"] == "f4_lounge" and v["floor"] == 4, v)
        crumb = await bc(); check("B", "breadcrumb shows floor and room", "Level 4" in crumb and "Penthouse Lounge" in crumb, crumb)
        rp = await S("() => document.body.innerText.includes('Penthouse Lounge')")
        truth = await T("() => twin.interiors.rooms.get('f4_lounge').data.ground_truth.true_occupancy")
        ctx = await S("() => document.querySelector('[data-testid=twin-context]')?.innerText || ''")
        check("B", "panels show the selected room", rp, "")
        await click("view-up")
        v = await wait_view("floor", floor=4); check("B", "'up' returns to the room's floor", v["mode"] == "floor" and v["floor"] == 4, v)

        await click("nav-floor-1")
        await wait_view("floor", floor=1)
        # what the viva demo does: select a room on another floor and ask for its room view
        await S("() => { const st = window.__buildingStore.getState(); st.selectRoom('f2_kitchen'); st.requestTwinView({ mode: 'room', room: 'f2_kitchen' }); }")
        await pg.wait_for_timeout(4000)
        v = await wait_view("room", room="f2_kitchen")
        check("B", "selecting + opening a room on another floor from a floor view lands in that room", v["mode"] == "room" and v["room"] == "f2_kitchen", v)

        # ---------------- Flow C — inspect HVAC
        occ_room = await T("() => { const c = [...twin.interiors.rooms.values()].filter(r => !r.live && r.data && r.data.ground_truth && r.data.ground_truth.true_occupancy > 0 && r.hvacState && r.hvacState.mode === 'cool').sort((a,b) => b.data.ground_truth.true_occupancy - a.data.ground_truth.true_occupancy); return c.length ? c[0].id : null; }")
        check("C", "an occupied, cooled room exists", occ_room is not None, occ_room)
        await S(f"() => {{ const s = document.querySelector('[data-testid=nav-room-{occ_room}]'); }}")
        await T("() => twin.setView('floor', 3)")
        await wait_view("floor", floor=3)
        await T(f"() => twin.setView('room', null, '{occ_room}')")
        v = await wait_view("room", room=occ_room)
        await click("layer-airflow")
        await pg.wait_for_timeout(1500)
        af = await T(f"() => twin.interiors.rooms.get('{occ_room}').hvac.flowGroup.visible")
        check("C", "airflow layer toggles on in the room", af)
        vals = await T(f"""() => {{ const r = twin.interiors.rooms.get('{occ_room}'); const ds = r.data.device_state; return {{ temp3d: r.hvacState.temp, tempData: r.data.sensors.Temperature, inten: r.hvacState.intensity, cool: ds.hvac_speed, sp3d: r.hvacState.setpoint, sp: ds.setpoint, label: r.hvacState.label, act: r.data.control.hvac_action, hot: twin.hotspots.map(h => h.txt.innerText) }}; }}""")
        check("C", "3D temperature = room's simulated temperature", vals["temp3d"] == vals["tempData"], vals["temp3d"])
        check("C", "airflow intensity follows the AC cooling output", abs(vals["inten"] - max(0.12, vals["cool"] / 100)) < 1e-6, f"{vals['inten']:.2f} vs {vals['cool']}%")
        check("C", "set-point and AC action shown = controller state", vals["sp3d"] == vals["sp"] and vals["act"] in vals["label"], vals["label"])
        check("C", "thermostat hotspot shows the room temperature", any(f"{vals['tempData']:.1f}" in h for h in vals["hot"]), vals["hot"][:2])
        await click("layer-temperature")
        await pg.wait_for_timeout(1500)
        tint = await T(f"() => twin.interiors.rooms.get('{occ_room}').tintFloor.visible")
        check("C", "temperature layer colours the room (room average)", tint)
        await shot("C_hvac")
        await click("layer-temperature")

        # ---------------- Flow D — compare rooms
        await click("pill-floor-2")
        v = await wait_view("floor", floor=2)
        live_badge = await T("() => twin.cards.get('f2_office_a').el.innerHTML.includes('LIVE')")
        sim_badge = await T("() => !twin.cards.get('f2_kitchen').el.innerHTML.includes('LIVE')")
        check("D", "live room card carries LIVE, simulated rooms do not", live_badge and sim_badge)
        okall = True
        for rid in ["f2_kitchen", "f2_server", "f2_office_b2", "f2_office_a"]:
            await T(f"() => twin.cards.get('{rid}').el.click()")
            await pg.wait_for_timeout(1200)
            same = await T(f"() => twin.selected === '{rid}'")
            name = await T(f"() => twin.interiors.rooms.get('{rid}').cfg.name")
            panel = await S(f"() => document.body.innerText.includes({json.dumps(name)})")
            okall = okall and same and panel
        check("D", "each selection updates the 3D highlight and the panels", okall)
        floors_ok = await T("() => [0,1,2,3,4].map(f => [...twin.interiors.rooms.values()].filter(r => r.f === f).length)")
        check("D", "rooms per floor = configuration (5, 4, 6, 7, 4)", floors_ok == [5, 4, 6, 7, 4], floors_ok)

        # ---------------- Flow E — live room
        sender = subprocess.Popen([sys.executable, os.path.join(ROOT, "raspberry_pi", "esp32_test_sender.py"), "--count", "15", "--interval", "2"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await pg.wait_for_timeout(6000)
        await S("() => document.querySelector('[data-testid=ctx-enter-room]') && null")
        await T("() => twin.setView('room', 2, 'f2_office_a')")
        v = await wait_view("room", room="f2_office_a")
        st = await T("() => { const r = twin.interiors.rooms.get('f2_office_a'); return { connected: r.connected, co2: r.data.sensors.CO2, node: (twin.hotspots.find(h => h.kind === 'node') || {}).txt?.innerText, people: twin.occupants.get(r.id).target, presence: r.data.presence && r.data.presence.fused_presence, source: r.data.hardware.sender }; }")
        check("E", "live room connected via the existing pipeline (test sender)", st["connected"] and st["source"] == "test_sender", st)
        check("E", "sensor node hotspot shows the measured CO2", st["node"] and f"{st['co2']}" in st["node"], st["node"])
        check("E", "occupants follow the presence sensor (0/1, never a count)", st["people"] == (1 if st["presence"] else 0), st)
        await shot("E_live_connected")
        sender.wait(timeout=60)
        await pg.wait_for_timeout(14000)
        st2 = await T("() => { const r = twin.interiors.rooms.get('f2_office_a'); return { connected: r.connected, temp: r.data.sensors.Temperature, node: (twin.hotspots.find(h => h.kind === 'node') || {}).txt?.innerText, people: twin.occupants.get(r.id).target }; }")
        check("E", "after the board stops: disconnected, no values, no people", (not st2["connected"]) and st2["temp"] is None and st2["people"] == 0 and "not connected" in (st2["node"] or ""), st2)
        await shot("E_live_lost")

        # ---------------- Flow F — resize and recover
        for w, h in [(1100, 700), (1700, 950), (1366, 768)]:
            await pg.set_viewport_size({"width": w, "height": h})
            await pg.wait_for_timeout(1500)
        await pg.wait_for_timeout(5000)
        sz = await T("() => { const c = twin.renderer.domElement; const s = document.getElementById('stage'); return [c.clientWidth, c.clientHeight, s.clientWidth, s.clientHeight, Math.abs(twin.camera.aspect - s.clientWidth / s.clientHeight) < 1e-3]; }")
        check("F", "canvas and camera follow the resized viewport", sz[0] == sz[2] and sz[1] == sz[3] and sz[4], sz)
        # rapid switching
        for js in ["twin.setView('building')", "twin.setView('floor', 1)", "twin.setView('room', null, 'f1_gym')", "twin.setView('floor', 3)", "twin.setView('room', null, 'f3_apt2_living')", "twin.setView('building')", "twin.setView('room', null, 'f0_lobby')"]:
            await T("() => " + js)
            await pg.wait_for_timeout(250)
        v = await wait_view("room", room="f0_lobby", timeout=30000)
        vis = await T("() => [...twin.interiors.rooms.values()].filter(r => r.group.visible).map(r => r.id)")
        floors_vis = await T("() => twin.building.floors.map(f => f.group.visible)")
        check("F", "rapid switching ends in the last requested view, only that room shown", v["mode"] == "room" and v["room"] == "f0_lobby" and vis == ["f0_lobby"] and floors_vis == [True, False, False, False, False], {"vis": vis, "floors": floors_vis})
        await click("camera-reset")
        await pg.wait_for_timeout(3000)
        cam = await T("() => { const t = twin.controls.target; const b = twin.interiors.rooms.get('f0_lobby').box; return t.x >= b.x0 - 1.01 && t.x <= b.x1 + 1.01 && t.z >= b.z0 - 1.01 && t.z <= b.z1 + 1.01; }")
        check("F", "camera reset keeps the target on the room", cam)
        sv = await S("() => document.querySelector('[data-testid=breadcrumb]').innerText.includes('Main Lobby')")
        check("F", "dashboard and 3D agree on the view after all of this", sv)
        await click("presentation")
        await pg.wait_for_timeout(2500)
        pres = await S("() => !!document.querySelector('[data-testid=presentation-hud]')")
        await shot("F_presentation")
        await pg.keyboard.press("Escape")
        await pg.wait_for_timeout(1500)
        back = await S("() => !document.querySelector('[data-testid=presentation-hud]')")
        check("F", "presentation mode opens and Esc returns to the dashboard", pres and back)
        # ---------------- Flow G — data provenance, room numbers, models panel (master prompt sections 12-13)
        await click("nav-room-f2_office_b2")
        await pg.wait_for_timeout(2500)
        num = await S("() => document.querySelector('[data-testid=room-number]')?.innerText || ''")
        prov = await S("() => document.querySelector('[data-testid=room-provenance]')?.innerText || ''")
        check("G", "simulated room shows its room number", num.startswith("Room 1"), num)
        check("G", "simulated room labels readings as simulated and P(occupied) as an estimate",
              "simulated" in prov and "estimate" in prov, prov[:120])
        await click("nav-room-f2_office_a")
        await pg.wait_for_timeout(2500)
        num101 = await S("() => document.querySelector('[data-testid=room-number]')?.innerText || ''")
        board = await S("() => document.querySelector('[data-testid=board-status]')?.innerText || ''")
        check("G", "the real room is Room 101 and shows its board status (no invented values)",
              num101 == "Room 101" and board != "", f"{num101} / {board}")
        await click("tab-models")
        for _ in range(40):
            ok = await S("() => !!document.querySelector('[data-testid=models-live]')")
            if ok: break
            await pg.wait_for_timeout(500)
        live_txt = await S("() => document.querySelector('[data-testid=models-live]')?.innerText || ''")
        prov_txt = await S("() => document.querySelector('[data-testid=models-provenance]')?.innerText || ''")
        check("G", "models panel lists the models running in the system", "thermal_h30" in live_txt, live_txt[:160])
        check("G", "models panel states where the numbers come from", "simulated" in prov_txt and "measured" in prov_txt, prov_txt[:160])
        await shot("G_models")
        await T("() => twin.setView('building')")
        await pg.wait_for_timeout(2000)
        crit = [e for e in errs if "favicon" not in e]
        check("ALL", "no page errors / console errors / failed requests", len(crit) == 0, crit[:5])
        print("waited for elements (dashboard briefly without data):", WAITS or "never")
        await b.close()
    passed = sum(1 for r in RESULTS if r[2])
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    json.dump([{"flow": f, "check": n, "pass": ok, "detail": str(d)[:300]} for f, n, ok, d in RESULTS], open("twin_flows_results.json", "w"), indent=1)
    if passed < len(RESULTS):
        sys.exit(1)
asyncio.run(main())
