"""
HUD Chart Rendering System

Renders real-time charts showing historical data (temperature, occupancy, energy).
Uses text-based ASCII charts with smooth updates.
"""

from typing import List, Optional, Tuple


class ChartRenderer:
    """
    Renders ASCII-based charts for displaying time-series data.
    Supports line charts with current value markers and axis labels.
    """

    def __init__(self, width: int = 40, height: int = 3):
        """
        Initialize chart renderer.

        Args:
            width: Chart width in characters
            height: Chart height in lines
        """
        self.width = max(10, width)  # Minimum 10 chars wide
        self.height = max(2, height)  # Minimum 2 lines tall

    def render_chart(self, data: List[float], title: str, unit: str = "",
                    min_val: Optional[float] = None,
                    max_val: Optional[float] = None) -> str:
        """
        Render a time-series chart as ASCII text.

        Args:
            data: List of values (most recent at end)
            title: Chart title
            unit: Unit label (e.g., "°C", "W", "%")
            min_val: Manual minimum (auto if None)
            max_val: Manual maximum (auto if None)

        Returns:
            Multi-line ASCII chart as string
        """
        # Handle empty/insufficient data
        if not data or len(data) < 2:
            return f"{title}: Waiting for data..."

        # Calculate value range for normalization
        if min_val is None:
            min_val = min(data)
        if max_val is None:
            max_val = max(data)

        value_range = max_val - min_val
        if value_range < 0.001:  # Avoid division by zero
            value_range = 1.0
            min_val = max_val - 0.5

        # Get recent data (fit to chart width)
        recent_data = data[-self.width:] if len(data) > self.width else data

        # Normalize data to [0, 1]
        normalized = []
        for val in recent_data:
            norm = (val - min_val) / value_range
            normalized.append(max(0.0, min(1.0, norm)))  # Clamp to 0-1

        # Create chart grid
        chart_grid = [[' ' for _ in range(self.width)] for _ in range(self.height)]

        # Plot points as histogram bars
        for i, norm_val in enumerate(normalized):
            # Determine which row(s) to fill
            col = i
            fill_height = int(norm_val * self.height * 2)  # 0 to height*2

            for row in range(self.height):
                # Row 0 is top, row height-1 is bottom
                row_threshold = (self.height - 1 - row) * 2
                if fill_height > row_threshold:
                    chart_grid[row][col] = '█'
                elif fill_height > row_threshold - 1:
                    # Partial fill for smoother visual
                    chart_grid[row][col] = '▄'

        # Add current value marker (rightmost)
        if normalized:
            current_norm = normalized[-1]
            current_row = int((1.0 - current_norm) * (self.height - 1) + 0.5)
            if 0 <= current_row < self.height:
                chart_grid[current_row][self.width - 1] = '•'

        # Extract current value
        current_value = recent_data[-1]

        # Build header with title and current value
        header = f"{title}: {current_value:.1f}{unit} (min:{min_val:.1f}, max:{max_val:.1f})"

        # Build chart display
        lines = [header]
        lines.append('┌' + '─' * self.width + '┐')

        for row_idx, row in enumerate(chart_grid):
            lines.append('│' + ''.join(row) + '│')

        lines.append('└' + '─' * self.width + '┘')

        return '\n'.join(lines)

    def render_metric_bar(self, value: float, max_value: float, title: str,
                         unit: str = "", width: int = 20) -> str:
        """
        Render a simple horizontal progress/value bar.

        Args:
            value: Current value
            max_value: Maximum value for scaling
            title: Metric title
            unit: Unit label
            width: Bar width in characters

        Returns:
            Single-line metric bar
        """
        if max_value <= 0:
            max_value = 1.0

        fraction = min(1.0, value / max_value)
        filled = int(fraction * width)

        bar = '█' * filled + '░' * (width - filled)
        percentage = fraction * 100

        return f"{title}: [{bar}] {value:.1f}{unit} ({percentage:.0f}%)"

    @staticmethod
    def format_metric_summary(room_state: dict) -> str:
        """
        Format a room's current metrics as readable text.

        Args:
            room_state: Room state dict with sensor readings

        Returns:
            Formatted metrics string
        """
        lines = [
            f"  Occupancy: {room_state.get('occupancy', 0.0):.0%}",
            f"  Temperature: {room_state.get('temperature', 20.0):.1f}°C",
            f"  Humidity: {room_state.get('humidity', 50.0):.0f}%",
            f"  Light: {'ON' if room_state.get('light_on', False) else 'OFF'}",
            f"  Energy: {room_state.get('energy_use', 0.0):.0f}W",
            f"  CO₂: {room_state.get('co2', 400.0):.0f}ppm",
        ]
        return '\n'.join(lines)
