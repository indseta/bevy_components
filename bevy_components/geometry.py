"""Pure-Python wireframe geometry for Blender-to-Bevy component previews.

Coordinates here are BLENDER LOCAL coordinates (Z up). Primitive dimension
fields in component metadata are BEVY LOCAL coordinates (Y up):
    (bevy_x, bevy_y, bevy_z) -> (blender_x, -bevy_z, bevy_y)
This mirrors the Blender glTF exporter's +Y-up axis conversion.
"""

from math import cos, pi, sin


def lines_from_points(points, closed=False):
    return [(points[i], points[i + 1]) for i in range(len(points) - 1)] + ([(points[-1], points[0])] if closed and len(points) > 2 else [])


def cuboid_lines(size):
    x, y, z = [float(v) / 2 for v in size]
    corners = [
        (sx * x, sy * z, sz * y)
        for sz in (-1, 1)
        for sy in (-1, 1)
        for sx in (-1, 1)
    ]
    edges = ((0, 1), (0, 2), (1, 3), (2, 3),
             (4, 5), (4, 6), (5, 7), (6, 7),
             (0, 4), (1, 5), (2, 6), (3, 7))
    return [(corners[a], corners[b]) for a, b in edges]


def circle_lines(radius, plane="XY", segments=48, center=(0, 0, 0), start_angle=0.0, end_angle=2 * pi):
    """A full circle, or an arc for start_angle != 0 or end_angle != 2*pi."""
    if radius <= 0:
        return []
    count = max(4, int(segments))
    cx, cy, cz = center
    points = []
    for i in range(count + 1):
        theta = start_angle + (end_angle - start_angle) * i / count
        a, b = radius * cos(theta), radius * sin(theta)
        if plane == "XY":
            points.append((cx + a, cy + b, cz))
        elif plane == "XZ":
            points.append((cx + a, cy, cz + b))
        elif plane == "YZ":
            points.append((cx, cy + a, cz + b))
        else:
            raise ValueError(f"Unsupported circle plane: {plane}")
    return lines_from_points(points)


def sphere_lines(radius, segments=40):
    lines = []
    for plane in ("XY", "XZ", "YZ"):
        lines.extend(circle_lines(radius, plane=plane, segments=segments))
    return lines


def capsule_lines(radius, height, segments=32):
    """Y-axis capsule in Bevy => Z-axis capsule in Blender; height excludes caps."""
    r, h = max(0.0, float(radius)), max(0.0, float(height))
    half = h / 2
    lines = []
    for z in (-half, half):
        lines.extend(circle_lines(r, "XY", segments, (0, 0, z)))
    for a in (0, pi / 2, pi, 3 * pi / 2):
        x, y = r * cos(a), r * sin(a)
        lines.append(((x, y, -half), (x, y, half)))
    arc_segments = max(6, segments // 4)
    for plane in ("XZ", "YZ"):
        lines.extend(circle_lines(r, plane, arc_segments, (0, 0, half), 0, pi))
        lines.extend(circle_lines(r, plane, arc_segments, (0, 0, -half), pi, 2 * pi))
    return lines


def spawn_marker_lines(scale=1.0):
    """Arrow is Blender local +Y, which becomes Bevy local -Z (forward)."""
    s = scale
    lines = circle_lines(0.30 * s, segments=24)
    lines.extend([
        ((0, 0, -0.3 * s), (0, 0, 0.4 * s)),
        ((-0.2 * s, 0, 0), (0.2 * s, 0, 0)),
        ((0, -0.2 * s, 0), (0, 0.2 * s, 0)),
        ((0, 0, 0), (0, 0.9 * s, 0)),
        ((0, 0.9 * s, 0), (-0.16 * s, 0.68 * s, 0)),
        ((0, 0.9 * s, 0), (0.16 * s, 0.68 * s, 0)),
    ])
    return lines
