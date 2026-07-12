"""
Materials Manager

Realistic material and color system with:
- Room type color palettes (professional, realistic tones)
- Material specular properties and shininess
- Procedural color variation (avoids flat appearance)
- Surface property definitions
- Dynamic color updates based on occupancy/comfort

Phase 8+: Enhanced Visual Quality
"""

from panda3d.core import Material, Vec3, Vec4
import random
import math


# ─────────────────────────────────────────────────────────────────────
# MATERIAL COLOR DEFINITIONS - Realistic Building Material Colors
# ─────────────────────────────────────────────────────────────────────

# Enhanced color palettes for different room types (more realistic, less saturated)
ROOM_COLORS = {
    "office": {
        "wall": Vec4(0.75, 0.82, 0.95, 1.0),      # Light professional blue
        "floor": Vec4(0.65, 0.65, 0.70, 1.0),     # Gray-blue floor
        "ceiling": Vec4(0.95, 0.95, 0.96, 1.0),   # Almost white ceiling
    },
    "meeting": {
        "wall": Vec4(0.78, 0.92, 0.80, 1.0),      # Soft green
        "floor": Vec4(0.70, 0.75, 0.60, 1.0),     # Gray-green
        "ceiling": Vec4(0.95, 0.97, 0.94, 1.0),   # Off-white
    },
    "corridor": {
        "wall": Vec4(0.90, 0.88, 0.75, 1.0),      # Neutral warm beige
        "floor": Vec4(0.65, 0.62, 0.55, 1.0),     # Warm gray
        "ceiling": Vec4(0.96, 0.96, 0.94, 1.0),   # Neutral white
    },
    "lobby": {
        "wall": Vec4(0.95, 0.92, 0.85, 1.0),      # Warm light beige
        "floor": Vec4(0.75, 0.70, 0.60, 1.0),     # Warm brown tones
        "ceiling": Vec4(0.97, 0.97, 0.95, 1.0),   # Warm white
    },
    "storage": {
        "wall": Vec4(0.88, 0.88, 0.88, 1.0),      # Neutral light gray
        "floor": Vec4(0.60, 0.60, 0.60, 1.0),     # Medium gray
        "ceiling": Vec4(0.93, 0.93, 0.93, 1.0),   # Light gray
    },
    "default": {
        "wall": Vec4(0.88, 0.88, 0.88, 1.0),      # Neutral gray
        "floor": Vec4(0.70, 0.70, 0.70, 1.0),     # Medium gray
        "ceiling": Vec4(0.95, 0.95, 0.95, 1.0),   # Light gray
    },
}

# Exterior material colors - realistic building materials
EXTERIOR_COLORS = {
    "building_wall": Vec4(0.78, 0.75, 0.70, 1.0),    # Warm tan/beige concrete
    "roof": Vec4(0.40, 0.38, 0.35, 1.0),              # Dark gray/brown roof
    "foundation": Vec4(0.45, 0.42, 0.40, 1.0),        # Foundation trim (gray)
    "ground": Vec4(0.40, 0.42, 0.38, 1.0),            # Realistic gray/earth tone
    "pavement": Vec4(0.55, 0.55, 0.52, 1.0),          # Concrete gray
    "walkway": Vec4(0.62, 0.60, 0.57, 1.0),           # Light gray walkway
    "tree_trunk": Vec4(0.45, 0.30, 0.15, 1.0),        # Brown wood
    "tree_canopy": Vec4(0.20, 0.50, 0.18, 1.0),       # Natural green foliage
}

# Window/glass colors
GLASS_COLOR = Vec4(0.75, 0.88, 1.0, 0.75)  # Slightly darker glass for realism

# Occupancy tint range
OCCUPANCY_MIN_COLOR = Vec4(0.90, 0.90, 0.90, 1.0)   # Neutral when empty
OCCUPANCY_MAX_COLOR = Vec4(1.05, 1.05, 1.05, 1.0)   # Slightly brighter occupied


class MaterialsManager:
    """
    Unified material property system.

    Provides consistent material properties, colors, and effects.
    Separates material data from rendering logic.
    """

    def __init__(self):
        """Initialize materials manager."""
        self.materials = {}
        self._init_materials()

    def _init_materials(self):
        """Initialize realistic material properties."""
        # Wall material - flat matte drywall/plaster
        wall_mat = Material("wall_material")
        wall_mat.setDiffuse(Vec4(0.8, 0.8, 0.8, 1.0))
        wall_mat.setSpecular(Vec4(0.08, 0.08, 0.08, 1.0))  # Very subtle
        wall_mat.setShininess(8.0)  # Matte drywall
        self.materials["wall"] = wall_mat

        # Floor material - polished concrete with slight sheen
        floor_mat = Material("floor_material")
        floor_mat.setDiffuse(Vec4(0.65, 0.65, 0.65, 1.0))
        floor_mat.setSpecular(Vec4(0.25, 0.25, 0.25, 1.0))  # Subtle reflect
        floor_mat.setShininess(25.0)  # Smooth concrete
        self.materials["floor"] = floor_mat

        # Ceiling material - acoustic tile/smooth plaster
        ceiling_mat = Material("ceiling_material")
        ceiling_mat.setDiffuse(Vec4(0.93, 0.93, 0.93, 1.0))
        ceiling_mat.setSpecular(Vec4(0.03, 0.03, 0.03, 1.0))  # Very matte
        ceiling_mat.setShininess(3.0)  # Acoustic tile
        self.materials["ceiling"] = ceiling_mat

        # Glass material - realistic windows
        glass_mat = Material("glass_material")
        glass_mat.setDiffuse(Vec4(0.75, 0.88, 1.0, 0.7))
        glass_mat.setSpecular(Vec4(0.6, 0.6, 0.6, 1.0))  # High specular
        glass_mat.setShininess(80.0)  # Very shiny
        self.materials["glass"] = glass_mat

        # Exterior ground material - natural earth tone
        ground_mat = Material("ground_material")
        ground_mat.setDiffuse(Vec4(0.40, 0.42, 0.38, 1.0))
        ground_mat.setSpecular(Vec4(0.05, 0.05, 0.05, 1.0))  # Almost matte
        ground_mat.setShininess(2.0)  # Very matte
        self.materials["ground"] = ground_mat

        # Roofing material - dark asphalt shingles
        roof_mat = Material("roof_material")
        roof_mat.setDiffuse(Vec4(0.35, 0.33, 0.30, 1.0))
        roof_mat.setSpecular(Vec4(0.15, 0.15, 0.15, 1.0))  # Slight weathered sheen
        roof_mat.setShininess(15.0)  # Slightly textured
        self.materials["roof"] = roof_mat

        # Concrete/trim material
        concrete_mat = Material("concrete_material")
        concrete_mat.setDiffuse(Vec4(0.50, 0.50, 0.48, 1.0))
        concrete_mat.setSpecular(Vec4(0.12, 0.12, 0.12, 1.0))
        concrete_mat.setShininess(12.0)
        self.materials["concrete"] = concrete_mat

    def get_room_color(self, room_type: str, surface_type: str) -> Vec4:
        """
        Get color for a room surface.

        Args:
            room_type: Room type ("office", "meeting", etc.)
            surface_type: Surface type ("wall", "floor", "ceiling")

        Returns:
            Vec4 RGBA color
        """
        colors = ROOM_COLORS.get(room_type, ROOM_COLORS["default"])
        return colors.get(surface_type, colors["wall"])

    def get_room_color_with_variation(self, room_type: str, surface_type: str,
                                       seed: int = None) -> Vec4:
        """
        Get room color with subtle procedural variation.

        Adds slight color variation to avoid flat appearance:
        - Walls: ±2% variation
        - Floors: ±3% variation
        - Ceilings: ±1% variation

        Args:
            room_type: Room type
            surface_type: Surface type
            seed: Optional random seed for reproducibility

        Returns:
            Vec4 RGBA color with variation
        """
        if seed is not None:
            rng = random.Random(seed)
        else:
            rng = random

        base_color = self.get_room_color(room_type, surface_type)

        # Amount of variation by surface type
        variation = {
            "wall": 0.02,      # ±2% for walls
            "floor": 0.03,     # ±3% for floors (more noticeable)
            "ceiling": 0.01,   # ±1% for ceilings (subtle)
        }

        var = variation.get(surface_type, 0.02)

        # Apply random variation to each RGB component
        r = base_color.getX() + rng.uniform(-var, var)
        g = base_color.getY() + rng.uniform(-var, var)
        b = base_color.getZ() + rng.uniform(-var, var)

        # Clamp to valid range
        return Vec4(
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
            base_color.getW()
        )

    def get_exterior_color(self, surface_type: str) -> Vec4:
        """
        Get realistic exterior material color.

        Args:
            surface_type: "building_wall", "roof", "ground", etc.

        Returns:
            Vec4 RGBA color
        """
        return EXTERIOR_COLORS.get(surface_type, EXTERIOR_COLORS["building_wall"])

    def get_exterior_color_with_variation(self, surface_type: str,
                                          position_seed: int = None) -> Vec4:
        """
        Get exterior color with natural variation.

        Simulates weathering and material irregularities:
        - Walls: ±3% variation (weathering)
        - Roof: ±4% variation (aging/wear)
        - Ground: ±5% variation (natural variation)

        Args:
            surface_type: Exterior surface type
            position_seed: Optional seed for consistent variation at same location

        Returns:
            Vec4 RGBA color with variation
        """
        if position_seed is not None:
            rng = random.Random(position_seed)
        else:
            rng = random

        base_color = self.get_exterior_color(surface_type)

        # Amount of variation by surface type
        variation = {
            "building_wall": 0.03,    # ±3% for weathering
            "roof": 0.04,              # ±4% for aging
            "ground": 0.05,            # ±5% for natural grass variation
            "pavement": 0.02,          # ±2% for concrete
            "walkway": 0.02,           # ±2% for paths
            "foundation": 0.03,        # ±3% for trim
            "tree_trunk": 0.04,        # ±4% for natural wood
            "tree_canopy": 0.06,       # ±6% for foliage variation
        }

        var = variation.get(surface_type, 0.03)

        # Apply variation
        r = base_color.getX() + rng.uniform(-var, var)
        g = base_color.getY() + rng.uniform(-var, var)
        b = base_color.getZ() + rng.uniform(-var, var)

        return Vec4(
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
            base_color.getW()
        )

    def get_material(self, material_type: str) -> Material:
        """
        Get material properties.

        Args:
            material_type: "wall", "floor", "ceiling", "glass"

        Returns:
            Panda3D Material object
        """
        return self.materials.get(material_type, self.materials["wall"])

    @staticmethod
    def apply_occupancy_tint(base_color: Vec4, occupancy: float) -> Vec4:
        """
        Apply occupancy-based color tint.

        Higher occupancy → slightly brighter walls (more lights on, more activity).

        Args:
            base_color: Base room color
            occupancy: Occupancy factor (0.0 to 1.0)

        Returns:
            Tinted color Vec4
        """
        # Occupancy increases brightness slightly
        brightness_boost = occupancy * 0.05  # 0-5% brightness increase

        return Vec4(
            min(1.0, base_color.getX() + brightness_boost),
            min(1.0, base_color.getY() + brightness_boost),
            min(1.0, base_color.getZ() + brightness_boost),
            base_color.getW()
        )

    @staticmethod
    def apply_temperature_tint(base_color: Vec4, temperature: float,
                               comfort: float = 0.5) -> Vec4:
        """
        Apply temperature-based color tint (warmer walls if cold).

        Args:
            base_color: Base room color
            temperature: Room temperature in Celsius
            comfort: Comfort index (0-1) for intensity

        Returns:
            Tinted color Vec4
        """
        # Very cold (<15°C) → slightly blue tint
        # Very hot (>28°C) → slightly red tint
        if temperature < 18:
            # Cold - add slight blue
            tint_strength = (18 - temperature) / 10  # 0 to ~0.8
            tint_strength = min(0.15, tint_strength * 0.2)
            return Vec4(
                base_color.getX() - tint_strength * 0.05,
                base_color.getY() - tint_strength * 0.05,
                base_color.getZ() + tint_strength,
                base_color.getW()
            )
        elif temperature > 25:
            # Hot - add slight red/yellow
            tint_strength = (temperature - 25) / 5  # 0 to ~0.6
            tint_strength = min(0.15, tint_strength * 0.25)
            return Vec4(
                base_color.getX() + tint_strength,
                base_color.getY() + tint_strength * 0.5,
                base_color.getZ() - tint_strength * 0.1,
                base_color.getW()
            )
        else:
            # Comfortable - no tint
            return base_color

    @staticmethod
    def get_glass_color() -> Vec4:
        """Get window/glass color with transparency."""
        return GLASS_COLOR


class SurfaceAppearance:
    """
    Encapsulates surface appearance properties.

    Separates data (colors, material) from rendering logic.
    """

    def __init__(self, base_color: Vec4, material_name: str = "wall"):
        """
        Initialize surface appearance.

        Args:
            base_color: Base RGBA color
            material_name: Material type for properties
        """
        self.base_color = base_color
        self.material_name = material_name
        self.occupancy = 0.0
        self.temperature = 20.0
        self.comfort = 0.5

    def set_occupancy(self, occupancy: float):
        """Update occupancy level."""
        self.occupancy = max(0.0, min(1.0, occupancy))

    def set_temperature(self, temperature: float):
        """Update temperature."""
        self.temperature = temperature

    def set_comfort(self, comfort: float):
        """Update comfort index."""
        self.comfort = max(0.0, min(1.0, comfort))

    def get_current_color(self) -> Vec4:
        """
        Get current color with all tints applied.

        Returns:
            Final Vec4 color
        """
        color = self.base_color

        # Apply occupancy tint
        color = MaterialsManager.apply_occupancy_tint(color, self.occupancy)

        # Apply temperature tint (if temperature varies from comfortable)
        color = MaterialsManager.apply_temperature_tint(
            color, self.temperature, self.comfort
        )

        return color
