"""
Camera Control System

Professional isometric-like camera with smooth interpolation.
Auto-centers on building, proper clipping, zoom/orbit support.
"""

from panda3d.core import Vec3, Point3
import math


class CameraControl:
    """
    Manages camera view and controls in the 3D scene.

    Features:
    - Smooth interpolated movement
    - Auto-centered on building geometry
    - Isometric-style default view
    - Zoom (wheel/keys), pan (WASD), orbit (arrows)
    - Proper near/far clipping
    """

    def __init__(self, app):
        """
        Initialize camera control.

        Args:
            app: ShowBase application instance
        """
        self.app = app
        self.camera = app.camera

        # Get building center from scene if available
        building_center = Point3(-1, -2, 1.5)  # Default fallback
        if hasattr(app, 'scene') and hasattr(app.scene, 'get_building_center'):
            bc = app.scene.get_building_center()
            building_center = Point3(bc.getX(), bc.getY(), bc.getZ())

        # Camera state
        self.distance = 42.0
        self.height = 12.0
        self.target = building_center

        # Target state for smooth interpolation
        self.target_distance = self.distance
        self.target_height = self.height
        self.target_target = Point3(building_center)
        self.target_azimuth = 235.0    # More dramatic southwest angle
        self.target_elevation = 32.0   # Slightly lower isometric angle

        # Zoom limits
        self.min_distance = 10.0
        self.max_distance = 80.0
        self.zoom_speed = 2.0

        # Control speeds
        self.pan_speed = 2.5
        self.rotate_speed = 8.0

        # Current angles
        self.azimuth = 235.0
        self.elevation = 32.0

        # Interpolation
        self.interpolation_speed = 0.10

        # Setup
        self._setup_camera_clipping()
        self._update_camera()
        self._setup_input()

    def _setup_camera_clipping(self):
        """Configure clipping planes and FOV."""
        if hasattr(self.camera, 'node') and len(self.camera.getChildren()) > 0:
            camera_node = self.camera.getChild(0)
            if hasattr(camera_node, 'getLens'):
                lens = camera_node.getLens()
                lens.setNearFar(0.1, 400.0)
                lens.setFov(50.0)  # Slightly narrower for more isometric feel

    def _update_camera(self):
        """Update camera position from angles and distance."""
        # Smooth interpolation
        self.distance += (self.target_distance - self.distance) * self.interpolation_speed
        self.height += (self.target_height - self.height) * self.interpolation_speed
        self.azimuth += self._angle_diff(self.target_azimuth, self.azimuth) * self.interpolation_speed
        self.elevation += (self.target_elevation - self.elevation) * self.interpolation_speed

        # Interpolate target position
        self.target.setX(self.target.getX() + (self.target_target.getX() - self.target.getX()) * self.interpolation_speed)
        self.target.setY(self.target.getY() + (self.target_target.getY() - self.target.getY()) * self.interpolation_speed)
        self.target.setZ(self.target.getZ() + (self.target_target.getZ() - self.target.getZ()) * self.interpolation_speed)

        # Calculate camera position from spherical coordinates
        az_rad = math.radians(self.azimuth)
        el_rad = math.radians(self.elevation)

        x = self.target.getX() + self.distance * math.cos(az_rad) * math.cos(el_rad)
        y = self.target.getY() + self.distance * math.sin(az_rad) * math.cos(el_rad)
        z = self.target.getZ() + self.distance * math.sin(el_rad) + self.height

        self.camera.setPos(x, y, z)
        self.camera.lookAt(self.target)

    @staticmethod
    def _angle_diff(target, current):
        """Calculate wrapped angle difference."""
        diff = target - current
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        return diff

    def _setup_input(self):
        """Setup keyboard and mouse input handlers."""
        self.app.accept("w", self._move_forward)
        self.app.accept("s", self._move_backward)
        self.app.accept("a", self._move_left)
        self.app.accept("d", self._move_right)
        self.app.accept("q", self._move_up)
        self.app.accept("e", self._move_down)

        self.app.accept("arrow_up", self._rotate_up)
        self.app.accept("arrow_down", self._rotate_down)
        self.app.accept("arrow_left", self._rotate_left)
        self.app.accept("arrow_right", self._rotate_right)

        self.app.accept("=", self._zoom_in)
        self.app.accept("+", self._zoom_in)
        self.app.accept("-", self._zoom_out)
        self.app.accept("_", self._zoom_out)
        self.app.accept("wheel_up", self._zoom_in)
        self.app.accept("wheel_down", self._zoom_out)

        self.app.accept("space", self.app.toggle_pause)
        self.app.accept("r", self._reset_view)
        self.app.accept("escape", self.app._app_shutdown)

        self.app.taskMgr.add(self._update_mouse_camera, "mouse_camera")

    def _move_forward(self):
        self.target_distance = max(self.min_distance, self.target_distance - 2.5)

    def _move_backward(self):
        self.target_distance = min(self.max_distance, self.target_distance + 2.5)

    def _move_left(self):
        self.target_target.setX(self.target_target.getX() - self.pan_speed)

    def _move_right(self):
        self.target_target.setX(self.target_target.getX() + self.pan_speed)

    def _move_up(self):
        self.target_target.setZ(self.target_target.getZ() + self.pan_speed)

    def _move_down(self):
        self.target_target.setZ(max(0.0, self.target_target.getZ() - self.pan_speed))

    def _zoom_in(self):
        self.target_distance = max(self.min_distance, self.target_distance - self.zoom_speed)

    def _zoom_out(self):
        self.target_distance = min(self.max_distance, self.target_distance + self.zoom_speed)

    def _rotate_up(self):
        self.target_elevation = min(80.0, self.target_elevation + 5.0)

    def _rotate_down(self):
        self.target_elevation = max(5.0, self.target_elevation - 5.0)

    def _rotate_left(self):
        self.target_azimuth -= 8.0
        if self.target_azimuth < 0:
            self.target_azimuth += 360.0

    def _rotate_right(self):
        self.target_azimuth += 8.0
        if self.target_azimuth >= 360.0:
            self.target_azimuth -= 360.0

    def _reset_view(self):
        """Reset to default view."""
        building_center = Point3(-1, -2, 1.5)
        if hasattr(self.app, 'scene') and hasattr(self.app.scene, 'get_building_center'):
            bc = self.app.scene.get_building_center()
            building_center = Point3(bc.getX(), bc.getY(), bc.getZ())

        self.target_distance = 42.0
        self.target_height = 12.0
        self.target_target = building_center
        self.target_azimuth = 235.0
        self.target_elevation = 32.0

    def _update_mouse_camera(self, task):
        """Placeholder for future mouse-based camera control."""
        return task.cont

    def update(self):
        """Called each frame to update camera position."""
        self._update_camera()
