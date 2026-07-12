"""
3D Scene Setup and Room Geometry

Handles creation of building geometry, rooms, and visual elements.
Uses procedural geometry with GeomVertexWriter (Panda3D 1.10+ compatible).

Overhaul: proper normals, semi-transparent shell, cutaway roof,
improved trees, selected-room highlight, professional materials.
"""

from panda3d.core import (
    CardMaker, Vec3, Vec4, DirectionalLight,
    AmbientLight, PointLight, Geom, GeomNode, GeomVertexData,
    GeomVertexFormat, GeomVertexWriter, GeomTriangles,
    TransparencyAttrib, TextNode, AntialiasAttrib,
    GeomEnums
)
from direct.showbase.ShowBase import ShowBase
from typing import List, Dict, Optional
import math

from panda3d_simulation.materials_manager import MaterialsManager, GLASS_COLOR, EXTERIOR_COLORS
from panda3d_simulation.lighting_manager import RoomLight


# ─────────────────────────────────────────────────────────────
# Professional color palette for room types
# ─────────────────────────────────────────────────────────────
ROOM_WALL_COLORS = {
    "office":   (0.80, 0.84, 0.90, 1.0),   # Distinct cool blue-gray
    "meeting":  (0.78, 0.86, 0.80, 1.0),   # Distinct soft teal-green
    "corridor": (0.86, 0.83, 0.76, 1.0),   # Warm sandy tone
    "lobby":    (0.90, 0.85, 0.78, 1.0),   # Richer warm beige
    "storage":  (0.75, 0.75, 0.75, 1.0),   # Solid gray
    "kitchen":  (0.85, 0.88, 0.82, 1.0),   # Warm white/pistachio
    "bathroom": (0.75, 0.90, 0.92, 1.0),   # Clean light cyan/teal
    "default":  (0.82, 0.82, 0.82, 1.0),   
}

ROOM_FLOOR_COLORS = {
    "office":   (0.42, 0.45, 0.50, 1.0),   # Darker carpet/concrete
    "meeting":  (0.45, 0.42, 0.38, 1.0),   # Dark wood/warm carpet
    "corridor": (0.50, 0.48, 0.42, 1.0),   # Mid-tone tile
    "lobby":    (0.55, 0.50, 0.40, 1.0),   # Rich stone tile
    "storage":  (0.35, 0.35, 0.35, 1.0),   # Dark industrial
    "kitchen":  (0.60, 0.55, 0.50, 1.0),   # Terracotta/Tile
    "bathroom": (0.45, 0.55, 0.60, 1.0),   # Blue-gray tile
    "default":  (0.45, 0.45, 0.45, 1.0),   
}

ROOM_CEILING_COLORS = {
    "office":   (0.98, 0.98, 0.98, 1.0),   # Brilliant white for contrast
    "meeting":  (0.98, 0.98, 0.98, 1.0),   
    "corridor": (0.98, 0.98, 0.98, 1.0),   
    "lobby":    (0.98, 0.98, 0.98, 1.0),   
    "storage":  (0.92, 0.92, 0.92, 1.0),   
    "kitchen":  (0.98, 0.98, 0.98, 1.0),   
    "bathroom": (0.95, 0.95, 0.95, 1.0),   
    "default":  (0.96, 0.96, 0.96, 1.0),   
}


# ─────────────────────────────────────────────────────────────
# Geometry helper: quad with proper face normal
# ─────────────────────────────────────────────────────────────

def _compute_normal(v0, v1, v2):
    """Compute face normal from 3 vertices (counter-clockwise winding)."""
    edge1 = v1 - v0
    edge2 = v2 - v0
    normal = edge1.cross(edge2)
    normal.normalize()
    return normal


def _make_quad(name, vertices, color, parent):
    """
    Create a quad (2-triangle plane) with proper normals for per-pixel lighting.
    Uses V3n3c4 format (vertex + normal + color).

    Args:
        name: GeomNode name
        vertices: List of 4 Vec3 corner positions (counter-clockwise)
        color: RGBA tuple
        parent: NodePath to attach to

    Returns:
        NodePath of the created quad
    """
    fmt = GeomVertexFormat.getV3n3c4()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(4)

    vertex_writer = GeomVertexWriter(vdata, "vertex")
    normal_writer = GeomVertexWriter(vdata, "normal")
    color_writer = GeomVertexWriter(vdata, "color")

    # Compute face normal from first three vertices
    normal = _compute_normal(vertices[0], vertices[1], vertices[2])

    for v in vertices:
        vertex_writer.addData3f(v)
        normal_writer.addData3f(normal)
        color_writer.addData4f(Vec4(*color))

    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2)
    tris.addVertices(0, 2, 3)

    geom = Geom(vdata)
    geom.addPrimitive(tris)

    geom_node = GeomNode(name)
    geom_node.addGeom(geom)

    np = parent.attachNewNode(geom_node)
    return np


def _make_box(name, center, half_extents, color, parent):
    """
    Create a box with 6 faces, each with correct outward-facing normals.

    Args:
        name: Node name
        center: Vec3 center position
        half_extents: Vec3(half_width, half_depth, half_height)
        color: RGBA tuple
        parent: NodePath to attach to

    Returns:
        NodePath of the box
    """
    box_node = parent.attachNewNode(f"{name}_group")
    hw, hd, hh = half_extents.getX(), half_extents.getY(), half_extents.getZ()
    cx, cy, cz = center.getX(), center.getY(), center.getZ()

    # Top face (+Z)
    _make_quad(f"{name}_top", [
        Vec3(cx - hw, cy + hd, cz + hh), Vec3(cx + hw, cy + hd, cz + hh),
        Vec3(cx + hw, cy - hd, cz + hh), Vec3(cx - hw, cy - hd, cz + hh),
    ], color, box_node)

    # Bottom face (-Z)
    _make_quad(f"{name}_bottom", [
        Vec3(cx - hw, cy - hd, cz - hh), Vec3(cx + hw, cy - hd, cz - hh),
        Vec3(cx + hw, cy + hd, cz - hh), Vec3(cx - hw, cy + hd, cz - hh),
    ], color, box_node)

    # Front face (+Y)
    _make_quad(f"{name}_front", [
        Vec3(cx - hw, cy + hd, cz - hh), Vec3(cx + hw, cy + hd, cz - hh),
        Vec3(cx + hw, cy + hd, cz + hh), Vec3(cx - hw, cy + hd, cz + hh),
    ], color, box_node)

    # Back face (-Y)
    _make_quad(f"{name}_back", [
        Vec3(cx + hw, cy - hd, cz - hh), Vec3(cx - hw, cy - hd, cz - hh),
        Vec3(cx - hw, cy - hd, cz + hh), Vec3(cx + hw, cy - hd, cz + hh),
    ], color, box_node)

    # Left face (-X)
    _make_quad(f"{name}_left", [
        Vec3(cx - hw, cy - hd, cz - hh), Vec3(cx - hw, cy + hd, cz - hh),
        Vec3(cx - hw, cy + hd, cz + hh), Vec3(cx - hw, cy - hd, cz + hh),
    ], color, box_node)

    # Right face (+X)
    _make_quad(f"{name}_right", [
        Vec3(cx + hw, cy + hd, cz - hh), Vec3(cx + hw, cy - hd, cz - hh),
        Vec3(cx + hw, cy - hd, cz + hh), Vec3(cx + hw, cy + hd, cz + hh),
    ], color, box_node)

    return box_node


def _make_octahedron(name, center, radius, color, parent):
    """
    Create a low-poly octahedron (diamond/sphere substitute).
    Safe to pass degenerate 4th vertex for triangles.
    """
    node = parent.attachNewNode(f"{name}_group")
    cx, cy, cz = center.getX(), center.getY(), center.getZ()
    
    top = Vec3(cx, cy, cz + radius)
    bottom = Vec3(cx, cy, cz - radius)
    
    # 4 equator points
    e1 = Vec3(cx + radius, cy, cz)
    e2 = Vec3(cx, cy + radius, cz)
    e3 = Vec3(cx - radius, cy, cz)
    e4 = Vec3(cx, cy - radius, cz)
    
    # Top 4 faces (degenerate 4th vertex acts as a triangle)
    _make_quad(f"{name}_t1", [e1, e2, top, top], color, node)
    _make_quad(f"{name}_t2", [e2, e3, top, top], color, node)
    _make_quad(f"{name}_t3", [e3, e4, top, top], color, node)
    _make_quad(f"{name}_t4", [e4, e1, top, top], color, node)
    
    # Bottom 4 faces (reversed winding)
    _make_quad(f"{name}_b1", [e2, e1, bottom, bottom], color, node)
    _make_quad(f"{name}_b2", [e3, e2, bottom, bottom], color, node)
    _make_quad(f"{name}_b3", [e4, e3, bottom, bottom], color, node)
    _make_quad(f"{name}_b4", [e1, e4, bottom, bottom], color, node)
    
    return node


class Room:
    """
    Represents a room in the 3D scene with proper wall, floor, ceiling, and doors.

    Z=0 is floor level, ceiling is at Z=height.
    Rooms have clearly defined geometry with optional door openings.
    """

    # Door dimensions (standardized)
    DOOR_WIDTH = 0.9
    DOOR_HEIGHT = 2.1

    def __init__(self, parent_node, room_id: int, x: float, y: float, z: float,
                 width: float = 4.0, depth: float = 4.0, height: float = 3.0,
                 zone_type: str = "default", doors: dict = None):
        """
        Create a room with walls, floor, ceiling, and optional doors.

        Args:
            parent_node: Panda3D node to attach room to
            room_id: Unique room identifier
            x, y, z: Room position (corner, not center)
            width: Room width (X-axis)
            depth: Room depth (Y-axis)
            height: Room height (Z-axis)
            zone_type: Room type for styling
            doors: Dict with door positions: {"front": bool, ...}
        """
        self.id = room_id
        self.width = width
        self.depth = depth
        self.height = height
        self.position = (x, y, z)
        self.zone_type = zone_type
        self.doors = doors or {}

        # Colors from professional palette
        self.wall_color = ROOM_WALL_COLORS.get(zone_type, ROOM_WALL_COLORS["default"])
        self.floor_color = ROOM_FLOOR_COLORS.get(zone_type, ROOM_FLOOR_COLORS["default"])
        self.ceiling_color = ROOM_CEILING_COLORS.get(zone_type, ROOM_CEILING_COLORS["default"])

        # Room center position (rooms are placed by corner in config)
        cx = x + width / 2
        cy = y + depth / 2
        cz = z  # z=0 is floor

        # Create room node at CENTER of room footprint, floor at z
        self.node = parent_node.attachNewNode(f"room_{room_id}")
        self.node.setPos(cx, cy, cz)

        # Store geometry nodes for visual effects
        self.wall_nodes = []
        self.window_nodes = []
        self.floor_node = None
        self.ceiling_node = None
        self.light_glow_factor = 0.0
        self.highlight_node = None  # For room selection

        # Create geometry (floor at z=0, ceiling at z=height, walls span 0..height)
        self._create_floor()
        self._create_ceiling()
        self._create_walls()
        self._create_windows()
        self._create_room_light()
        self._create_room_label()

        # Occupancy visualization nodes
        self.occupant_nodes = []

        # Visualization state
        self.occupancy = 0.0
        self.temperature = 20.0

    def _create_walls(self):
        """Create wall geometry with door openings. Walls span Z=0 to Z=height."""
        hw = self.width / 2
        hd = self.depth / 2
        h = self.height
        door_w = self.DOOR_WIDTH / 2
        door_h = self.DOOR_HEIGHT
        
        c = self.wall_color
        # Fake ambient occlusion shading for depth distinction
        c_front = (c[0]*0.90, c[1]*0.90, c[2]*0.90, 1.0)
        c_back  = (c[0]*1.00, c[1]*1.00, c[2]*1.00, 1.0)
        c_left  = (c[0]*0.95, c[1]*0.95, c[2]*0.95, 1.0)
        c_right = (c[0]*0.80, c[1]*0.80, c[2]*0.80, 1.0)

        # Front wall (+Y direction)
        if self.doors.get("front", False):
            self.wall_nodes.append(_make_quad("wall_front_left", [
                Vec3(-hw, hd, 0), Vec3(-door_w, hd, 0),
                Vec3(-door_w, hd, h), Vec3(-hw, hd, h)
            ], c_front, self.node))
            self.wall_nodes.append(_make_quad("wall_front_right", [
                Vec3(door_w, hd, 0), Vec3(hw, hd, 0),
                Vec3(hw, hd, h), Vec3(door_w, hd, h)
            ], c_front, self.node))
            self.wall_nodes.append(_make_quad("wall_front_header", [
                Vec3(-door_w, hd, door_h), Vec3(door_w, hd, door_h),
                Vec3(door_w, hd, h), Vec3(-door_w, hd, h)
            ], c_front, self.node))
        else:
            self.wall_nodes.append(_make_quad("wall_front", [
                Vec3(-hw, hd, 0), Vec3(hw, hd, 0),
                Vec3(hw, hd, h), Vec3(-hw, hd, h)
            ], c_front, self.node))

        # Back wall (-Y direction)
        if self.doors.get("back", False):
            self.wall_nodes.append(_make_quad("wall_back_left", [
                Vec3(hw, -hd, 0), Vec3(door_w, -hd, 0),
                Vec3(door_w, -hd, h), Vec3(hw, -hd, h)
            ], c_back, self.node))
            self.wall_nodes.append(_make_quad("wall_back_right", [
                Vec3(-door_w, -hd, 0), Vec3(-hw, -hd, 0),
                Vec3(-hw, -hd, h), Vec3(-door_w, -hd, h)
            ], c_back, self.node))
            self.wall_nodes.append(_make_quad("wall_back_header", [
                Vec3(door_w, -hd, door_h), Vec3(-door_w, -hd, door_h),
                Vec3(-door_w, -hd, h), Vec3(door_w, -hd, h)
            ], c_back, self.node))
        else:
            self.wall_nodes.append(_make_quad("wall_back", [
                Vec3(hw, -hd, 0), Vec3(-hw, -hd, 0),
                Vec3(-hw, -hd, h), Vec3(hw, -hd, h)
            ], c_back, self.node))

        # Left wall (-X direction)
        if self.doors.get("left", False):
            self.wall_nodes.append(_make_quad("wall_left_front", [
                Vec3(-hw, -hd, 0), Vec3(-hw, -door_w, 0),
                Vec3(-hw, -door_w, h), Vec3(-hw, -hd, h)
            ], c_left, self.node))
            self.wall_nodes.append(_make_quad("wall_left_back", [
                Vec3(-hw, door_w, 0), Vec3(-hw, hd, 0),
                Vec3(-hw, hd, h), Vec3(-hw, door_w, h)
            ], c_left, self.node))
            self.wall_nodes.append(_make_quad("wall_left_header", [
                Vec3(-hw, -door_w, door_h), Vec3(-hw, door_w, door_h),
                Vec3(-hw, door_w, h), Vec3(-hw, -door_w, h)
            ], c_left, self.node))
        else:
            self.wall_nodes.append(_make_quad("wall_left", [
                Vec3(-hw, -hd, 0), Vec3(-hw, hd, 0),
                Vec3(-hw, hd, h), Vec3(-hw, -hd, h)
            ], c_left, self.node))

        # Right wall (+X direction)
        if self.doors.get("right", False):
            self.wall_nodes.append(_make_quad("wall_right_back", [
                Vec3(hw, -hd, 0), Vec3(hw, -door_w, 0),
                Vec3(hw, -door_w, h), Vec3(hw, -hd, h)
            ], c_right, self.node))
            self.wall_nodes.append(_make_quad("wall_right_front", [
                Vec3(hw, door_w, 0), Vec3(hw, hd, 0),
                Vec3(hw, hd, h), Vec3(hw, door_w, h)
            ], c_right, self.node))
            self.wall_nodes.append(_make_quad("wall_right_header", [
                Vec3(hw, -door_w, door_h), Vec3(hw, door_w, door_h),
                Vec3(hw, door_w, h), Vec3(hw, -door_w, h)
            ], c_right, self.node))
        else:
            self.wall_nodes.append(_make_quad("wall_right", [
                Vec3(hw, hd, 0), Vec3(hw, -hd, 0),
                Vec3(hw, -hd, h), Vec3(hw, hd, h)
            ], c, self.node))

    def _create_windows(self):
        """Create window panes on exterior-facing walls."""
        hw = self.width / 2
        hd = self.depth / 2

        window_width = min(1.2, self.width * 0.25)
        window_height = 1.2
        window_bottom_z = 0.9  # ~desk height
        window_y = hd + 0.02  # Slightly in front of front wall

        # Only create windows if room is wide enough
        if self.width < 3.0:
            return

        # Left window - opaque light/glass color section 
        left_x = -hw + self.width * 0.22
        window_color = Vec4(0.65, 0.85, 0.95, 1.0) # Light blue wall section
        np = _make_quad("window_left", [
            Vec3(left_x, window_y, window_bottom_z),
            Vec3(left_x + window_width, window_y, window_bottom_z),
            Vec3(left_x + window_width, window_y, window_bottom_z + window_height),
            Vec3(left_x, window_y, window_bottom_z + window_height),
        ], window_color, self.node)
        # Opaque overlay on the wall to act as the window representation
        self.window_nodes.append(np)

        # Right window
        right_x = hw - self.width * 0.22 - window_width
        np = _make_quad("window_right", [
            Vec3(right_x, window_y, window_bottom_z),
            Vec3(right_x + window_width, window_y, window_bottom_z),
            Vec3(right_x + window_width, window_y, window_bottom_z + window_height),
            Vec3(right_x, window_y, window_bottom_z + window_height),
        ], window_color, self.node)
        self.window_nodes.append(np)

    def _create_floor(self):
        """Create floor geometry at Z=0."""
        hw = self.width / 2
        hd = self.depth / 2

        self.floor_node = _make_quad("floor_geom", [
            Vec3(-hw, -hd, 0.0), Vec3(hw, -hd, 0.0),
            Vec3(hw, hd, 0.0), Vec3(-hw, hd, 0.0),
        ], self.floor_color, self.node)

    def _create_ceiling(self):
        """Create ceiling geometry at Z=height."""
        hw = self.width / 2
        hd = self.depth / 2
        cz = self.height

        self.ceiling_node = _make_quad("ceiling_geom", [
            Vec3(-hw, hd, cz), Vec3(hw, hd, cz),
            Vec3(hw, -hd, cz), Vec3(-hw, -hd, cz),
        ], self.ceiling_color, self.node)

    def _create_room_light(self):
        """Create an interior ceiling light."""
        self.room_light = RoomLight(
            self.node, self.height, self.width, self.depth
        )
        self.light_np = self.room_light.get_node()
        self.light_on = False

    def _create_room_label(self):
        """Create a text label floating inside the room, facing camera."""
        text_node = TextNode(f"room_{self.id}_label")

        # Base structure is established here, actual dynamic text set in update()
        text_node.setText(f"Room {self.id}")
        text_node.setTextColor(1.0, 1.0, 1.0, 0.95)
        text_node.setAlign(TextNode.ACenter)
        text_node.setTextScale(0.38)  

        # Create a card (background) behind the text for high contrast readability
        text_node.setCardColor(0.08, 0.08, 0.12, 0.85)
        text_node.setCardAsMargin(0.12, 0.12, 0.06, 0.06)
        text_node.setCardDecal(True)

        text_np = self.node.attachNewNode(text_node)
        # Position clearly above the room roof, avoiding geometric overlap
        text_np.setPos(0, 0, self.height + 0.5)
        text_np.setScale(1.2)
        # Billboard: always face camera
        text_np.setBillboardPointEye()
        self.label_np = text_np
        self._last_label_text = ""
        self._last_label_color = None

    def create_highlight(self):
        """Create a glowing highlight border for selected room."""
        if self.highlight_node:
            self.highlight_node.removeNode()

        hw = self.width / 2 + 0.12
        hd = self.depth / 2 + 0.12
        h = self.height

        highlight_color = (0.0, 1.0, 1.0, 0.95)  # Much stronger electric cyan glow
        hn = self.node.attachNewNode(f"highlight_{self.id}")

        # Bottom border (floor level)
        border_h = 0.22
        for name, verts in [
            ("hl_front", [Vec3(-hw, hd, 0), Vec3(hw, hd, 0), Vec3(hw, hd, border_h), Vec3(-hw, hd, border_h)]),
            ("hl_back", [Vec3(hw, -hd, 0), Vec3(-hw, -hd, 0), Vec3(-hw, -hd, border_h), Vec3(hw, -hd, border_h)]),
            ("hl_left", [Vec3(-hw, -hd, 0), Vec3(-hw, hd, 0), Vec3(-hw, hd, border_h), Vec3(-hw, -hd, border_h)]),
            ("hl_right", [Vec3(hw, hd, 0), Vec3(hw, -hd, 0), Vec3(hw, -hd, border_h), Vec3(hw, hd, border_h)]),
        ]:
            q = _make_quad(name, verts, highlight_color, hn)
            q.setTransparency(TransparencyAttrib.MAlpha)
            q.setDepthWrite(False)

        # Top border (ceiling level)
        for name, verts in [
            ("hl_top_front", [Vec3(-hw, hd, h - border_h), Vec3(hw, hd, h - border_h), Vec3(hw, hd, h), Vec3(-hw, hd, h)]),
            ("hl_top_back", [Vec3(hw, -hd, h - border_h), Vec3(-hw, -hd, h - border_h), Vec3(-hw, -hd, h), Vec3(hw, -hd, h)]),
            ("hl_top_left", [Vec3(-hw, -hd, h - border_h), Vec3(-hw, hd, h - border_h), Vec3(-hw, hd, h), Vec3(-hw, -hd, h)]),
            ("hl_top_right", [Vec3(hw, hd, h - border_h), Vec3(hw, -hd, h - border_h), Vec3(hw, -hd, h), Vec3(hw, hd, h)]),
        ]:
            q = _make_quad(name, verts, highlight_color, hn)
            q.setTransparency(TransparencyAttrib.MAlpha)
            q.setDepthWrite(False)

        # Vertical corner pillars
        pillar_w = 0.12
        corners = [
            (-hw, -hd), (-hw, hd), (hw, -hd), (hw, hd)
        ]
        for i, (cx, cy) in enumerate(corners):
            q = _make_quad(f"hl_pillar_{i}_a", [
                Vec3(cx - pillar_w, cy, 0), Vec3(cx + pillar_w, cy, 0),
                Vec3(cx + pillar_w, cy, h), Vec3(cx - pillar_w, cy, h)
            ], highlight_color, hn)
            q.setTransparency(TransparencyAttrib.MAlpha)
            q.setDepthWrite(False)

        self.highlight_node = hn
        
        # Turn label electric cyan to match
        if hasattr(self, 'label_np'):
            self.label_np.node().setTextColor(0.0, 0.85, 1.0, 1.0)
            self.label_np.node().setCardColor(0.0, 0.15, 0.25, 0.8)

    def remove_highlight(self):
        """Remove selection highlight."""
        if self.highlight_node:
            self.highlight_node.removeNode()
            self.highlight_node = None
            
        # Reset label color
        if hasattr(self, 'label_np'):
            # It will be reset perfectly on the next update call by set_occupancy, 
            # but we can do a quick reset here:
            is_occupied = self.occupancy > 0.5
            if is_occupied:
                self.label_np.node().setTextColor(0.4, 1.0, 0.5, 0.95)
            else:
                self.label_np.node().setTextColor(0.85, 0.85, 0.85, 0.8)
            self.label_np.node().setCardColor(0.15, 0.15, 0.2, 0.7)

    def set_light_state(self, is_on: bool):
        """Turn room light on or off with visible floor/wall brightness change."""
        self.light_on = is_on
        self.room_light.set_on(is_on)

    def _update_occupant_geometry(self, current_count: int):
        """Add or remove 3D occupants to match current count with random spawn positions."""
        import random
        
        hw = (self.width / 2) - 0.6
        hd = (self.depth / 2) - 0.6

        # Add nodes if needed
        while len(self.occupant_nodes) < current_count:
            x = random.uniform(-hw, hw)
            y = random.uniform(-hd, hd)
            
            # Faster random velocity for highly noticeable wandering
            vx = random.uniform(-1.5, 1.5)
            vy = random.uniform(-1.5, 1.5)
            
            radius = 0.45 # Larger glowing sphere for obvious visibility
            hover_z = 1.4 # Float prominently above floor
            
            i = len(self.occupant_nodes)
            node = self.node.attachNewNode(f"occupant_{i}")
            node.setPos(x, y, hover_z)
            
            # Disable lighting on occupant so it acts emissively/glows
            node.setLightOff()
            
            # Store random phase offset for bobbing
            phase_offset = random.uniform(0.0, 10.0)
            node.setPythonTag("velocity", [vx, vy, phase_offset])
            
            # Vivid neon glowing green for maximum contrast
            color = (0.1, 1.0, 0.3, 1.0) 
            _make_octahedron(f"occ_{i}", Vec3(0, 0, 0), radius, color, node)
            
            self.occupant_nodes.append(node)

        # Remove nodes if needed
        while len(self.occupant_nodes) > current_count:
            node = self.occupant_nodes.pop()
            node.removeNode()

    def _update_occupants_motion(self, dt: float):
        """Apply simple idle wandering logic constrained to room bounds."""
        from panda3d.core import ClockObject
        import math
        
        hw = (self.width / 2) - 0.5
        hd = (self.depth / 2) - 0.5
        time = ClockObject.getGlobalClock().getFrameTime()
        
        for node in self.occupant_nodes:
            pos = node.getPos()
            tag_data = node.getPythonTag("velocity")
            vx, vy, phase = tag_data[0], tag_data[1], tag_data[2]
            
            # Calculate new position
            nx = pos.x + vx * dt
            ny = pos.y + vy * dt
            
            # Bounce off walls softly
            if nx < -hw or nx > hw:
                vx *= -1
                nx = max(-hw, min(hw, nx))
            if ny < -hd or ny > hd:
                vy *= -1
                ny = max(-hd, min(hd, ny))
                
            # Floating spherical bobbing on the Z axis (exaggerated)
            hover_z = 1.4
            nz = hover_z + math.sin(time * 5.0 + phase) * 0.25
                
            node.setPos(nx, ny, nz)
            
            # Throbbing pulse effect to make it jump out visually
            pulse = 0.85 + 0.15 * math.sin(time * 8.0 + phase)
            node.setScale(pulse)
            node.setColorScale(1.0, 1.0, 1.0, pulse)
            
            node.setPythonTag("velocity", [vx, vy, phase])

    def set_occupancy(self, count: float, occupancy_max: float = 2.0):
        """Update occupancy representation based on direct human headcount."""
        self.occupancy = count
        actual_count = int(round(count))
        self._update_occupant_geometry(actual_count)

    def set_temperature(self, temperature: float):
        """Store temperature state for visual tinting."""
        self.temperature = temperature

    def _update_light(self, dt: float = 0.016):
        """Update visual state combinatorics: Lights, Temperature, Occupancy."""
        self.room_light.update_brightness(dt)

        b = self.room_light.brightness
        
        # 1. Base lighting tint directly scaling geometry for strong VISUAL clarity
        # (Satisfies requirement to not rely solely on physics/ambient light)
        dim_color = Vec4(0.35, 0.35, 0.45, 1.0)      # Noticeably darker off-state
        lit_color = Vec4(1.4, 1.35, 1.0, 1.0)        # Clearly bright warm-yellow
        
        base_color = Vec4(
            dim_color.getX() + b * (lit_color.getX() - dim_color.getX()),
            dim_color.getY() + b * (lit_color.getY() - dim_color.getY()),
            dim_color.getZ() + b * (lit_color.getZ() - dim_color.getZ()),
            1.0
        )
        
        # 2. Temperature Tint
        temp = self.temperature
        temp_tint = Vec4(1.0, 1.0, 1.0, 1.0)
        if temp < 20.0:   # Cool -> Blue tint
            t = min(1.0, (20.0 - temp) / 4.0)
            temp_tint = Vec4(1.0 - t*0.15, 1.0 - t*0.05, 1.0 + t*0.25, 1.0)
        elif temp > 24.0: # Hot -> Red tint
            t = min(1.0, (temp - 24.0) / 6.0)
            temp_tint = Vec4(1.0 + t*0.25, 1.0 - t*0.10, 1.0 - t*0.15, 1.0)
            
        # 3. Occupancy Tint
        occ_tint = Vec4(1.0, 1.0, 1.0, 1.0)
        if self.occupancy > 0.5:
            # Subtle green/blue highlight when occupied
            occ_tint = Vec4(0.85, 1.15, 1.10, 1.0)
            
        # 4. Daylighting (Sunlight through windows)
        daylight_tint = Vec4(1.0, 1.0, 1.0, 1.0)
        has_windows = len(self.window_nodes) > 0
        if has_windows:
            sun = getattr(self, "sunlight", 0.0)
            # Add bright natural light contribution during the day
            daylight_tint = Vec4(1.0 + sun*0.35, 1.0 + sun*0.4, 1.0 + sun*0.45, 1.0)
            
        final_color = Vec4(
            base_color.getX() * temp_tint.getX() * occ_tint.getX() * daylight_tint.getX(),
            base_color.getY() * temp_tint.getY() * occ_tint.getY() * daylight_tint.getY(),
            base_color.getZ() * temp_tint.getZ() * occ_tint.getZ() * daylight_tint.getZ(),
            1.0
        )
        
        # Performance cache: Only apply to geometry if color actually changed significantly
        if not hasattr(self, "_last_applied_wall_color") or \
           abs(self._last_applied_wall_color.getX() - final_color.getX()) > 0.01 or \
           abs(self._last_applied_wall_color.getY() - final_color.getY()) > 0.01 or \
           abs(self._last_applied_wall_color.getZ() - final_color.getZ()) > 0.01:
               
            self._last_applied_wall_color = final_color
            for wall_node in self.wall_nodes:
                wall_node.setColorScale(final_color)
                
            if self.floor_node:
                self.floor_node.setColorScale(final_color)
                
            if self.ceiling_node:
                self.ceiling_node.setColorScale(final_color)

    def update(self, room_state: dict, dt: float = 0.016):
        """Update room based on simulation state."""
        self.sunlight = room_state.get("sunlight", 0.0)
        
        # Build dynamic 3D Label text (Minimalist & Clean)
        zone_names = {
            "office": "Office", "meeting": "Meeting",
            "corridor": "Corridor", "lobby": "Lobby",
            "storage": "Storage", "kitchen": "Kitchen",
            "bathroom": "Bathroom", "default": "Room"
        }
        display_name = zone_names.get(self.zone_type, "Room")
        lines = [f"{display_name}"]
        
        # Cause-Effect Indicator & Energy Bar
        light_on = room_state.get("light_on", False)
        occupancy = room_state.get("occupancy", 0.0)
        energy = room_state.get("energy_use", 0.0)
        
        # Calculate energy blocks first
        energy_blocks = min(5, int(max(0, energy) / 18))
        
        new_color = None
        status_parts = []
        if not light_on and occupancy <= 0:
            status_parts.append("Eco")
            new_color = (0.4, 0.95, 0.5, 0.95)
        elif not light_on:
            status_parts.append("Off")
            new_color = (0.7, 0.7, 0.7, 0.9)
        else:
            # Light is ON: Map energy to color (Low=Green/Dim, Med=Yellow, High=Red/Bright)
            if energy_blocks <= 1:
                new_color = (0.5, 0.95, 0.5, 0.90)  # Low energy -> Dim Green
            elif energy_blocks <= 3:
                new_color = (1.0, 0.85, 0.3, 0.95)  # Moderate -> Yellow
            else:
                new_color = (1.0, 0.3, 0.3, 1.00)   # High energy -> Brighter Red
            
        if self._last_label_color != new_color:
            self.label_np.node().setTextColor(*new_color)
            self._last_label_color = new_color
            
        # Tiny energy bar using universally safe ASCII to prevent Unicode font warnings 
        bar = "#" * energy_blocks + "-" * (5 - energy_blocks)
        status_parts.append(f"PWR [{bar}]")
        
        new_text = "\n".join(lines)
        if new_text != self._last_label_text:
            self.label_np.node().setText(new_text)
            self._last_label_text = new_text
            
        if "light_on" in room_state:
            self.set_light_state(room_state["light_on"])
        if "occupancy" in room_state:
            self.set_occupancy(occupancy, room_state.get("occupancy_max", 2.0))
        if "temperature" in room_state:
            self.set_temperature(room_state["temperature"])
            
        # Add dynamic pulse to the highlight selection marker if it exists
        if self.highlight_node:
            from panda3d.core import ClockObject
            import math
            time = ClockObject.getGlobalClock().getFrameTime()
            pulse = 0.65 + 0.35 * math.sin(time * 4.0)
            self.highlight_node.setColorScale(1.0, 1.0, 1.0, pulse)
            
        # Smooth-ramp the room light each frame
        self._update_light(dt)
        self._update_occupants_motion(dt)

    def set_wall_color(self, color: 'Vec4'):
        """Set wall color (for HVAC/comfort tinting)."""
        for wall_node in self.wall_nodes:
            wall_node.setColorScale(color)

    def set_window_color(self, color: 'Vec4'):
        """Set window pane color (for shading effects)."""
        for window_node in self.window_nodes:
            window_node.setColorScale(color)

    def set_floor_color(self, color: 'Vec4'):
        """Set floor color."""
        if self.floor_node:
            self.floor_node.setColorScale(color)

    def set_ceiling_color(self, color: 'Vec4'):
        """Set ceiling color."""
        if self.ceiling_node:
            self.ceiling_node.setColorScale(color)

    def set_light_glow(self, glow_factor: float):
        """Set light glow factor (wall brightness boost)."""
        self.light_glow_factor = max(0.0, min(1.0, glow_factor))


class BuildingExterior:
    """
    Creates the exterior ground, building shell, and outdoor context.
    Shell is semi-transparent so rooms are visible from outside.
    Roof is hidden for cutaway isometric view.
    """

    def __init__(self, parent_node, room_configs=None, materials_manager=None):
        """
        Create building exterior elements.

        Args:
            parent_node: Panda3D node to attach to
            room_configs: Optional list of room config objects
            materials_manager: Optional MaterialsManager for colors
        """
        self.node = parent_node.attachNewNode("building_exterior")
        self.room_configs = room_configs
        self.materials_manager = materials_manager

        # Compute building bounds from room configs
        self._compute_bounds()

        # Create elements
        self._create_ground()
        self._create_building_shell()
        self._create_outdoor_elements()

    def _compute_bounds(self):
        """Compute building bounding box from room configurations."""
        margin = 0.5  # Margin around rooms

        if self.room_configs:
            xs, ys = [], []
            for rc in self.room_configs:
                x = rc.position.get("x", 0) if isinstance(rc.position, dict) else rc.position["x"]
                y = rc.position.get("y", 0) if isinstance(rc.position, dict) else rc.position["y"]
                w = rc.dimensions.get("width", 6) if isinstance(rc.dimensions, dict) else rc.dimensions["width"]
                d = rc.dimensions.get("depth", 6) if isinstance(rc.dimensions, dict) else rc.dimensions["depth"]
                h = rc.dimensions.get("height", 3) if isinstance(rc.dimensions, dict) else rc.dimensions["height"]
                xs.extend([x, x + w])
                ys.extend([y, y + d])
                self.building_height = h  # Assume uniform height

            self.min_x = min(xs) - margin
            self.max_x = max(xs) + margin
            self.min_y = min(ys) - margin
            self.max_y = max(ys) + margin
        else:
            # Fallback defaults
            self.min_x, self.max_x = -12.0, 10.0
            self.min_y, self.max_y = -12.0, 4.0
            self.building_height = 3.0

        self.center_x = (self.min_x + self.max_x) / 2
        self.center_y = (self.min_y + self.max_y) / 2
        self.roof_z = self.building_height + 0.1  # Slightly above room ceilings

    def _create_ground(self):
        """Create outdoor ground plane with landscaping zones."""
        size = 80.0

        if self.materials_manager:
            ground_color = self.materials_manager.get_exterior_color_with_variation("ground", position_seed=42)
            pavement_color = self.materials_manager.get_exterior_color_with_variation("pavement", position_seed=43)
        else:
            ground_color = EXTERIOR_COLORS["ground"]
            pavement_color = EXTERIOR_COLORS["pavement"]

        # Large grass area
        _make_quad("ground_geom", [
            Vec3(-size, -size, -0.05), Vec3(size, -size, -0.05),
            Vec3(size, size, -0.05), Vec3(-size, size, -0.05),
        ], ground_color, self.node)

        # Paved area around the building
        pad = 3.0
        _make_quad("pavement_geom", [
            Vec3(self.min_x - pad, self.min_y - pad, -0.03),
            Vec3(self.max_x + pad, self.min_y - pad, -0.03),
            Vec3(self.max_x + pad, self.max_y + pad, -0.03),
            Vec3(self.min_x - pad, self.max_y + pad, -0.03),
        ], pavement_color, self.node)

    def _create_building_shell(self):
        """Create semi-transparent building shell — walls visible, no roof."""
        shell_node = self.node.attachNewNode("building_shell")

        floor_z = -0.02
        roof_z = self.roof_z

        if self.materials_manager:
            outer_wall_color_base = self.materials_manager.get_exterior_color_with_variation("building_wall", position_seed=100)
            trim_color = self.materials_manager.get_exterior_color_with_variation("foundation", position_seed=102)
        else:
            outer_wall_color_base = EXTERIOR_COLORS["building_wall"]
            trim_color = EXTERIOR_COLORS["foundation"]

        # Semi-transparent walls (alpha = 0.18 for glass-like effect)
        alpha = 0.18
        wall_color = (
            outer_wall_color_base.getX() if hasattr(outer_wall_color_base, 'getX') else outer_wall_color_base[0],
            outer_wall_color_base.getY() if hasattr(outer_wall_color_base, 'getY') else outer_wall_color_base[1],
            outer_wall_color_base.getZ() if hasattr(outer_wall_color_base, 'getZ') else outer_wall_color_base[2],
            alpha
        )

        mn_x, mx_x = self.min_x, self.max_x
        mn_y, mx_y = self.min_y, self.max_y

        # Outer walls (semi-transparent)
        for name, verts in [
            ("shell_front", [
                Vec3(mn_x, mx_y, floor_z), Vec3(mx_x, mx_y, floor_z),
                Vec3(mx_x, mx_y, roof_z), Vec3(mn_x, mx_y, roof_z)]),
            ("shell_back", [
                Vec3(mx_x, mn_y, floor_z), Vec3(mn_x, mn_y, floor_z),
                Vec3(mn_x, mn_y, roof_z), Vec3(mx_x, mn_y, roof_z)]),
            ("shell_left", [
                Vec3(mn_x, mn_y, floor_z), Vec3(mn_x, mx_y, floor_z),
                Vec3(mn_x, mx_y, roof_z), Vec3(mn_x, mn_y, roof_z)]),
            ("shell_right", [
                Vec3(mx_x, mx_y, floor_z), Vec3(mx_x, mn_y, floor_z),
                Vec3(mx_x, mn_y, roof_z), Vec3(mx_x, mx_y, roof_z)]),
        ]:
            q = _make_quad(name, verts, wall_color, shell_node)
            q.setTransparency(TransparencyAttrib.MAlpha)
            q.setDepthWrite(False)

        # Foundation trim (opaque, thin strip at base)
        trim_h = 0.25
        trim_c = (
            trim_color.getX() if hasattr(trim_color, 'getX') else trim_color[0],
            trim_color.getY() if hasattr(trim_color, 'getY') else trim_color[1],
            trim_color.getZ() if hasattr(trim_color, 'getZ') else trim_color[2],
            0.85
        )
        for i, face in enumerate([
            [Vec3(mn_x, mx_y, floor_z), Vec3(mx_x, mx_y, floor_z),
             Vec3(mx_x, mx_y, floor_z + trim_h), Vec3(mn_x, mx_y, floor_z + trim_h)],
            [Vec3(mx_x, mn_y, floor_z), Vec3(mn_x, mn_y, floor_z),
             Vec3(mn_x, mn_y, floor_z + trim_h), Vec3(mx_x, mn_y, floor_z + trim_h)],
            [Vec3(mn_x, mn_y, floor_z), Vec3(mn_x, mx_y, floor_z),
             Vec3(mn_x, mx_y, floor_z + trim_h), Vec3(mn_x, mn_y, floor_z + trim_h)],
            [Vec3(mx_x, mx_y, floor_z), Vec3(mx_x, mn_y, floor_z),
             Vec3(mx_x, mn_y, floor_z + trim_h), Vec3(mx_x, mx_y, floor_z + trim_h)],
        ]):
            q = _make_quad(f"trim_{i}", face, trim_c, shell_node)
            q.setTransparency(TransparencyAttrib.MAlpha)
            q.setDepthWrite(False)

        # NO ROOF — cutaway view for isometric camera

        # Roof parapet (low opaque border at top, architectural detail)
        parapet_h = 0.3
        parapet_c = (trim_c[0], trim_c[1], trim_c[2], 0.6)
        for i, face in enumerate([
            [Vec3(mn_x, mx_y, roof_z), Vec3(mx_x, mx_y, roof_z),
             Vec3(mx_x, mx_y, roof_z + parapet_h), Vec3(mn_x, mx_y, roof_z + parapet_h)],
            [Vec3(mx_x, mn_y, roof_z), Vec3(mn_x, mn_y, roof_z),
             Vec3(mn_x, mn_y, roof_z + parapet_h), Vec3(mx_x, mn_y, roof_z + parapet_h)],
            [Vec3(mn_x, mn_y, roof_z), Vec3(mn_x, mx_y, roof_z),
             Vec3(mn_x, mx_y, roof_z + parapet_h), Vec3(mn_x, mn_y, roof_z + parapet_h)],
            [Vec3(mx_x, mx_y, roof_z), Vec3(mx_x, mn_y, roof_z),
             Vec3(mx_x, mn_y, roof_z + parapet_h), Vec3(mx_x, mx_y, roof_z + parapet_h)],
        ]):
            q = _make_quad(f"parapet_{i}", face, parapet_c, shell_node)
            q.setTransparency(TransparencyAttrib.MAlpha)
            q.setDepthWrite(False)

    def _create_outdoor_elements(self):
        """Create outdoor elements — trees and walkway."""
        elements_node = self.node.attachNewNode("outdoor_elements")

        if self.materials_manager:
            walkway_color = self.materials_manager.get_exterior_color_with_variation("walkway", position_seed=50)
        else:
            walkway_color = EXTERIOR_COLORS["walkway"]

        # Walkway from building front to "entrance"
        wk_cx = self.center_x
        _make_quad("walkway_geom", [
            Vec3(wk_cx - 1.5, self.max_y + 0.5, -0.02),
            Vec3(wk_cx + 1.5, self.max_y + 0.5, -0.02),
            Vec3(wk_cx + 1.5, self.max_y + 15, -0.02),
            Vec3(wk_cx - 1.5, self.max_y + 15, -0.02),
        ], walkway_color, elements_node)

        # Trees placed around the perimeter
        tree_positions = []
        for offset in [-4, 4, 12]:
            tree_positions.append((self.min_x - 3, self.min_y + offset, -0.05))
            tree_positions.append((self.max_x + 3, self.min_y + offset, -0.05))
        tree_positions.append((wk_cx - 5, self.max_y + 5, -0.05))
        tree_positions.append((wk_cx + 5, self.max_y + 5, -0.05))

        for i, (tx, ty, tz) in enumerate(tree_positions):
            self._create_tree(elements_node, tx, ty, tz, seed=1000 + i)

    def _create_tree(self, parent, x, y, z, seed=None):
        """Create a multi-tier conifer-style tree (professional look)."""
        import random as _random
        rng = _random.Random(seed)

        tree_node = parent.attachNewNode(f"tree_{x:.0f}_{y:.0f}")
        tree_node.setPos(x, y, z)

        # Get colors
        if self.materials_manager:
            trunk_color = self.materials_manager.get_exterior_color_with_variation("tree_trunk", position_seed=seed)
            canopy_color = self.materials_manager.get_exterior_color_with_variation("tree_canopy", position_seed=(seed + 1) if seed else None)
        else:
            trunk_color = EXTERIOR_COLORS["tree_trunk"]
            canopy_color = EXTERIOR_COLORS["tree_canopy"]

        trunk_c = (
            trunk_color.getX() if hasattr(trunk_color, 'getX') else trunk_color[0],
            trunk_color.getY() if hasattr(trunk_color, 'getY') else trunk_color[1],
            trunk_color.getZ() if hasattr(trunk_color, 'getZ') else trunk_color[2],
            1.0
        )
        canopy_c = (
            canopy_color.getX() if hasattr(canopy_color, 'getX') else canopy_color[0],
            canopy_color.getY() if hasattr(canopy_color, 'getY') else canopy_color[1],
            canopy_color.getZ() if hasattr(canopy_color, 'getZ') else canopy_color[2],
            1.0
        )

        # Trunk — slim rectangular prism
        trunk_hw = 0.12
        trunk_h = 1.8 + rng.uniform(0, 0.5)
        _make_box("trunk", Vec3(0, 0, trunk_h / 2), Vec3(trunk_hw, trunk_hw, trunk_h / 2),
                   trunk_c, tree_node)

        # Canopy — 3 stacked cones (pyramid approximation using quads)
        canopy_layers = [
            (trunk_h - 0.3, 1.4, 1.2),   # Bottom layer: z_base, radius, height
            (trunk_h + 0.6, 1.1, 1.0),   # Middle
            (trunk_h + 1.3, 0.8, 0.9),   # Top
        ]

        for li, (layer_z, radius, layer_h) in enumerate(canopy_layers):
            # 4-sided pyramid per layer
            apex = Vec3(0, 0, layer_z + layer_h)
            corners = [
                Vec3(radius, 0, layer_z),
                Vec3(0, radius, layer_z),
                Vec3(-radius, 0, layer_z),
                Vec3(0, -radius, layer_z),
            ]
            # Create 4 triangular faces
            for fi in range(4):
                v0 = corners[fi]
                v1 = corners[(fi + 1) % 4]
                v2 = apex

                # Use _make_quad with a degenerate 4th vertex (triangle)
                fmt = GeomVertexFormat.getV3n3c4()
                vdata = GeomVertexData(f"canopy_{li}_{fi}", fmt, Geom.UHStatic)
                vdata.setNumRows(3)

                vw = GeomVertexWriter(vdata, "vertex")
                nw = GeomVertexWriter(vdata, "normal")
                cw = GeomVertexWriter(vdata, "color")

                normal = _compute_normal(v0, v1, v2)

                for v in [v0, v1, v2]:
                    vw.addData3f(v)
                    nw.addData3f(normal)
                    cw.addData4f(Vec4(*canopy_c))

                tris = GeomTriangles(Geom.UHStatic)
                tris.addVertices(0, 1, 2)

                geom = Geom(vdata)
                geom.addPrimitive(tris)
                gn = GeomNode(f"canopy_{li}_{fi}_geom")
                gn.addGeom(geom)
                tree_node.attachNewNode(gn)

            # Bottom cap of each layer
            fmt = GeomVertexFormat.getV3n3c4()
            vdata = GeomVertexData(f"canopy_bottom_{li}", fmt, Geom.UHStatic)
            vdata.setNumRows(4)
            vw = GeomVertexWriter(vdata, "vertex")
            nw = GeomVertexWriter(vdata, "normal")
            cw = GeomVertexWriter(vdata, "color")
            down_normal = Vec3(0, 0, -1)
            for v in reversed(corners):
                vw.addData3f(v)
                nw.addData3f(down_normal)
                cw.addData4f(Vec4(*canopy_c))
            tris = GeomTriangles(Geom.UHStatic)
            tris.addVertices(0, 1, 2)
            tris.addVertices(0, 2, 3)
            geom = Geom(vdata)
            geom.addPrimitive(tris)
            gn = GeomNode(f"canopy_bottom_{li}_geom")
            gn.addGeom(geom)
            tree_node.attachNewNode(gn)


class Scene:
    """
    Main scene manager.
    Handles all 3D geometry and visual updates.
    Supports dynamic room loading from RoomConfig.
    """

    def __init__(self, render_node, room_configs: Optional[List] = None):
        """
        Initialize the scene.

        Args:
            render_node: Panda3D root render node
            room_configs: List of RoomConfig objects.
        """
        self.render = render_node
        self.rooms = {}
        self.exterior = None
        self.room_configs = room_configs
        self.materials_manager = MaterialsManager()
        self.selected_room_id = 0

        self._create_building()

        # Highlight first room by default
        if 0 in self.rooms:
            self.rooms[0].create_highlight()

        print(f"  3D Scene created — {len(self.rooms)} rooms")

    def _create_building(self):
        """Create the building structure with rooms."""
        self.exterior = BuildingExterior(
            self.render,
            room_configs=self.room_configs,
            materials_manager=self.materials_manager
        )

        if self.room_configs:
            self._create_rooms_from_config()
        else:
            self._create_rooms_default()

    def _create_rooms_default(self):
        """Create default layout if no config loaded."""
        room_configs = [
            (0, -8.0, -8.0, 0, 6.0, 6.0, "office", {"right": True}),
            (1,  0.0, -8.0, 0, 6.0, 6.0, "office", {"left": True}),
            (2, -8.0,  0.0, 0, 6.0, 6.0, "meeting", {"right": True}),
            (3,  0.0,  0.0, 0, 6.0, 6.0, "corridor", {"left": True}),
        ]

        for room_id, x, y, z, width, depth, zone_type, doors in room_configs:
            room = Room(
                parent_node=self.render,
                room_id=room_id,
                x=x, y=y, z=z,
                width=width, depth=depth, height=3.0,
                zone_type=zone_type,
                doors=doors
            )
            self.rooms[room_id] = room

    def _create_rooms_from_config(self):
        """Create rooms from RoomConfig objects."""
        for room_config in self.room_configs:
            doors = getattr(room_config, 'doors', {})

            room = Room(
                parent_node=self.render,
                room_id=room_config.room_id,
                x=room_config.position["x"],
                y=room_config.position["y"],
                z=room_config.position["z"],
                width=room_config.dimensions["width"],
                depth=room_config.dimensions["depth"],
                height=room_config.dimensions["height"],
                zone_type=room_config.zone_type,
                doors=doors
            )
            self.rooms[room_config.room_id] = room

    def select_room(self, room_id: int):
        """Highlight a specific room and unhighlight others."""
        if room_id == self.selected_room_id and room_id in self.rooms:
            return  # Already selected

        # Remove old highlight
        if self.selected_room_id in self.rooms:
            self.rooms[self.selected_room_id].remove_highlight()

        # Add new highlight
        if room_id in self.rooms:
            self.rooms[room_id].create_highlight()
            self.selected_room_id = room_id

    def update(self, simulation_state: dict, dt: float = 0.016):
        """Update scene based on simulation state."""
        if "rooms" not in simulation_state:
            return

        # Calculate global daylight factor from sun altitude
        sun_alt = simulation_state.get("sun_altitude", -90.0)
        sunlight_factor = max(0.0, min(1.0, sun_alt / 45.0))

        room_states = simulation_state["rooms"]
        for room_id, room_state in room_states.items():
            if room_id in self.rooms:
                room_state["sunlight"] = sunlight_factor
                self.rooms[room_id].update(room_state, dt)

    def get_room(self, room_id: int) -> Room:
        """Get a room by ID."""
        return self.rooms.get(room_id)

    def get_building_center(self) -> Vec3:
        """Get center of the building for camera targeting."""
        if self.room_configs:
            xs, ys = [], []
            for rc in self.room_configs:
                x = rc.position["x"]
                y = rc.position["y"]
                w = rc.dimensions["width"]
                d = rc.dimensions["depth"]
                h = rc.dimensions["height"]
                xs.extend([x, x + w])
                ys.extend([y, y + d])
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            return Vec3(cx, cy, h / 2)
        return Vec3(0, 0, 1.5)
