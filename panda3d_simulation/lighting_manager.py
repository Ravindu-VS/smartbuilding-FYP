"""
Lighting Manager

Centralized dynamic lighting system:
- Directional sun with time-of-day color (warm dawn, bright noon, blue night)
- Hemisphere ambient (sky fill + ground bounce)
- Per-room interior point lights that actually illuminate geometry
- Shadow casting from the sun
- Indoor/outdoor contrast via separate light scoping
"""

from panda3d.core import (
    DirectionalLight, AmbientLight, PointLight, Spotlight,
    Vec3, Vec4, LColor, NodePath
)
import math


# ── Colour presets for time-of-day ──────────────────────────────────
# Each tuple is (R, G, B) normalised to ~1.0 at peak
_SUN_COLORS = {
    "night":   (0.05, 0.05, 0.12),    # Deep blue moonlight
    "dawn":    (1.00, 0.55, 0.25),    # Warm orange sunrise
    "morning": (1.00, 0.90, 0.75),    # Soft warm white
    "noon":    (1.00, 0.98, 0.95),    # Neutral bright white
    "evening": (1.00, 0.60, 0.30),    # Golden hour
    "dusk":    (0.70, 0.35, 0.20),    # Deep orange sunset
}


def _lerp_color(a, b, t):
    """Linearly interpolate between two (r,g,b) tuples."""
    t = max(0.0, min(1.0, t))
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _sun_color_for_altitude(alt_deg):
    """
    Return (r, g, b, intensity) for the sun based on altitude in degrees.
    Produces warm colours at low sun, neutral at high sun, blue at night.
    """
    if alt_deg < -18:
        # Astronomical twilight / night
        return _SUN_COLORS["night"] + (0.04,)
    elif alt_deg < -6:
        # Civil-to-nautical twilight
        t = (alt_deg + 18) / 12  # 0..1
        rgb = _lerp_color(_SUN_COLORS["night"], _SUN_COLORS["dawn"], t)
        return rgb + (0.05 + t * 0.20,)
    elif alt_deg < 0:
        # Dawn / dusk
        t = (alt_deg + 6) / 6  # 0..1
        rgb = _lerp_color(_SUN_COLORS["dawn"], _SUN_COLORS["morning"], t)
        return rgb + (0.25 + t * 0.30,)
    elif alt_deg < 15:
        # Low morning / late afternoon
        t = alt_deg / 15  # 0..1
        rgb = _lerp_color(_SUN_COLORS["morning"], _SUN_COLORS["noon"], t)
        return rgb + (0.55 + t * 0.25,)
    elif alt_deg < 60:
        # Full daytime
        t = (alt_deg - 15) / 45  # 0..1
        rgb = _SUN_COLORS["noon"]
        return rgb + (0.80 + t * 0.20,)
    else:
        return _SUN_COLORS["noon"] + (1.0,)


class LightingManager:
    """
    Central lighting controller.

    Owns the sun (DirectionalLight), hemisphere ambient, and an optional
    fill light.  Room lights are created and attached separately via
    create_room_light().
    """

    def __init__(self, parent_node):
        """
        Args:
            parent_node: root render NodePath
        """
        self.parent_node = parent_node
        self.last_sun_altitude = 0.0

        # Sun
        self.sun_light = None
        self.sun_node = None

        # Ambient (hemisphere approximation)
        self.ambient_light = None
        self.ambient_node = None

        # Secondary fill light (simulates ground bounce)
        self.fill_light = None
        self.fill_node = None

        self._setup_sunlight()
        self._setup_ambient()
        self._setup_fill_light()

    # ── Setup ───────────────────────────────────────────────────────

    def _setup_sunlight(self):
        """Strong directional light representing the sun."""
        self.sun_light = DirectionalLight("sun")
        self.sun_light.setColor(Vec4(1.0, 0.98, 0.95, 1.0))

        # High-quality shadows with soft falloff
        self.sun_light.setShadowCaster(True, 2048, 2048)
        self.sun_light.getLens().setFilmSize(50, 50)  # Larger area for better coverage
        self.sun_light.getLens().setNearFar(0.5, 120)  # Better near/far ratio

        # Add specular highlights from sun
        self.sun_light.setSpecularColor(Vec4(1.0, 0.98, 0.95, 1.0))

        self.sun_node = self.parent_node.attachNewNode(self.sun_light)
        self.sun_node.setPos(0, 0, 35)  # Higher position for better lighting
        self.sun_node.lookAt(0, 0, 0)
        self.parent_node.setLight(self.sun_node)

    def _setup_ambient(self):
        """Soft omni-directional fill (sky hemisphere) with day/night variation."""
        self.ambient_light = AmbientLight("ambient")
        self.ambient_light.setColor(Vec4(0.25, 0.27, 0.35, 1.0))

        self.ambient_node = self.parent_node.attachNewNode(self.ambient_light)
        self.parent_node.setLight(self.ambient_node)

    def _setup_fill_light(self):
        """Up-facing directional fill simulating ground bounce and skylight."""
        self.fill_light = DirectionalLight("ground_fill")
        self.fill_light.setColor(Vec4(0.10, 0.09, 0.07, 1.0))
        self.fill_light.setDirection(Vec3(0, 0, 1))  # Pointing upward
        # Add specular for ground reflections
        self.fill_light.setSpecularColor(Vec4(0.08, 0.07, 0.05, 1.0))

        self.fill_node = self.parent_node.attachNewNode(self.fill_light)
        self.parent_node.setLight(self.fill_node)

    # ── Per-frame update ────────────────────────────────────────────

    def update(self, sun_altitude: float, cloud_cover: float = 0.0):
        """
        Update all lights for the current time of day and weather.

        Args:
            sun_altitude: degrees, -90 (midnight) to +90 (noon)
            cloud_cover:  0.0 (clear) to 1.0 (overcast)
        """
        self.last_sun_altitude = sun_altitude
        alt = max(-90.0, min(90.0, sun_altitude))
        alt_rad = math.radians(alt)

        # ── Sun direction (east-to-west arc) ──
        # azimuth sweeps from east (alt<0 rising) through south to west
        sun_dir = Vec3(
            -math.cos(alt_rad) * 0.6,   # slight east–west sweep
            -0.7,                        # from south
            -max(0.05, math.sin(alt_rad))  # altitude; clamp so it shines at dusk
        ).normalized()

        self.sun_node.setPos(
            -sun_dir.getX() * 30,
            -sun_dir.getY() * 30,
            -sun_dir.getZ() * 30,
        )
        self.sun_node.lookAt(0, 0, 0)

        # ── Sun colour and intensity ──
        r, g, b, intensity = _sun_color_for_altitude(alt)

        # Cloud cover dims the sun
        cloud_dim = 1.0 - cloud_cover * 0.45
        intensity *= cloud_dim

        self.sun_light.setColor(Vec4(
            r * intensity,
            g * intensity,
            b * intensity,
            1.0,
        ))

        # Enable/disable shadows based on sun altitude
        self.sun_light.setShadowCaster(alt > -5, 2048, 2048)

        # ── Ambient ──
        # Night: dim blue, day: soft sky-white
        if alt < -10:
            # Deep night - very dim
            amb = Vec4(0.04, 0.05, 0.10, 1.0)
            spec = Vec4(0.02, 0.02, 0.04, 1.0)
        elif alt < 0:
            # Twilight - gradual transition
            t = (alt + 10) / 10
            amb = Vec4(
                0.06 + t * 0.16,
                0.07 + t * 0.15,
                0.12 + t * 0.12,
                1.0,
            )
            spec = Vec4(
                0.03 + t * 0.10,
                0.03 + t * 0.09,
                0.04 + t * 0.08,
                1.0,
            )
        else:
            # Daytime - bright and clear
            day_t = min(1.0, alt / 45)
            base = 0.25 + day_t * 0.25  # Stronger daytime ambient
            amb = Vec4(
                base * 0.95 * cloud_dim,
                base * 0.97 * cloud_dim,
                base * 1.10 * cloud_dim,  # sky blue tint
                1.0,
            )
            spec = Vec4(
                base * 0.60 * cloud_dim,
                base * 0.60 * cloud_dim,
                base * 0.65 * cloud_dim,
                1.0,
            )
        self.ambient_light.setColor(amb)

        # ── Fill (ground bounce) ──
        fill_i = max(0.0, intensity * 0.12)
        self.fill_light.setColor(Vec4(
            fill_i * 0.9,
            fill_i * 0.85,
            fill_i * 0.7,  # warm ground tint
            1.0,
        ))

    # ── Room light factory ──────────────────────────────────────────

    @staticmethod
    def create_room_light(parent_node, room_height: float,
                          room_width: float, room_depth: float):
        """Create a room interior light. Returns a RoomLight instance."""
        return RoomLight(parent_node, room_height, room_width, room_depth)


class RoomLight:
    """
    Interior room lighting with visible, realistic illumination.

    Uses PointLight with:
    - Warm white color (3200 K incandescent feel)
    - Extended range to properly illuminate rooms
    - Strong specular for visible highlights
    - Adaptive brightness based on occupancy
    """

    def __init__(self, parent_node, room_height: float,
                 room_width: float, room_depth: float):
        self.parent_node = parent_node
        self.room_height = room_height
        self.room_width = room_width
        self.room_depth = room_depth
        self.is_on = False
        self.brightness = 0.0  # smooth ramp 0..1
        
        # Subtle randomized limits so each room feels slightly unique
        import random
        self._target_on = random.uniform(2.5, 3.0)  # Boosted for night visibility
        self._target_off = random.uniform(0.12, 0.18)

        # Main ceiling light – warm white (3200K incandescent)
        self.light = PointLight("room_ceiling_light")
        self.light.setColor(Vec4(0, 0, 0, 1))  # start off

        # MINIMAL attenuation: Allows light to flood the walls aggressively
        self.light.setAttenuation((0.5, 0.02, 0.0005)) # Drop-off much slower

        # Strong specular highlights for realism
        self.light.setSpecularColor(Vec4(1.0, 0.90, 0.70, 1.0))

        self.light_node = parent_node.attachNewNode(self.light)
        # Position light at ceiling center for even illumination
        self.light_node.setPos(0, 0, room_height - 0.20)

        # Register light on the PARENT node so room geometry receives it
        parent_node.setLight(self.light_node)

        # Shadows off for indoor lights (performance and to avoid banding)
        self.light.setShadowCaster(False, 512, 512)

    def set_on(self, on: bool):
        """Turn light on or off."""
        self.is_on = on

    def update_brightness(self, dt: float = 0.016):
        """
        Smooth ramp toward target brightness.
        Lights fade on/off over ~0.25s for realism.
        Phase 10: Increased brightness for better visibility when light is on.
        """
        from panda3d.core import ClockObject
        import math
        
        target = self._target_on if self.is_on else self._target_off
        ramp_speed = 8.0  # full transition faster
        if self.brightness < target:
            self.brightness = min(target, self.brightness + ramp_speed * dt)
        elif self.brightness > target:
            self.brightness = max(target, self.brightness - ramp_speed * dt)

        b = self.brightness
        
        # Warm white with balanced intensity, drastically boosted so window shines at night
        self.light.setColor(Vec4(
            4.0 * b,       # Warm red
            3.5 * b,       # Green for warm mix
            2.5 * b,       # Low blue to keep it warm but clear
            1.0,
        ))

    def create_accent_light(self, offset_x: float, offset_y: float, offset_z: float):
        """
        Create a secondary accent light for corner/wall illumination.
        Less bright than main light but adds realism.

        Args:
            offset_x, offset_y, offset_z: Position offset from room center

        Returns:
            NodePath of the accent light
        """
        accent_light = PointLight("room_accent_light")
        accent_light.setColor(Vec4(0, 0, 0, 1))  # start off

        # Weaker attenuation (shorter range, more localized)
        accent_light.setAttenuation((1.0, 0.06, 0.015))

        # Less specular than main light
        accent_light.setSpecularColor(Vec4(0.6, 0.54, 0.40, 1.0))

        accent_node = self.parent_node.attachNewNode(accent_light)
        accent_node.setPos(offset_x, offset_y, offset_z)

        self.parent_node.setLight(accent_node)
        accent_light.setShadowCaster(False, 512, 512)

        return accent_node

    def get_node(self):
        return self.light_node


class OutdoorLighting:
    """
    Optional secondary outdoor fill (sky dome approximation).
    Kept for backward compatibility.
    """

    def __init__(self, parent_node):
        self.parent_node = parent_node
        self.sky_light = AmbientLight("sky_fill")
        self.sky_light.setColor(Vec4(0.4, 0.55, 0.75, 1.0))

        self.sky_node = parent_node.attachNewNode(self.sky_light)
        parent_node.setLight(self.sky_node)
        self.is_enabled = True

    def set_intensity(self, intensity: float):
        intensity = max(0.0, min(1.0, intensity))
        self.sky_light.setColor(Vec4(
            0.4 * intensity,
            0.55 * intensity,
            0.75 * intensity,
            1.0,
        ))
