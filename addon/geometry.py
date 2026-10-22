from math import cos, pi, sin


def lines_from_points(points, closed=False):
    return [(points[index], points[index + 1]) for index in range(len(points) - 1)] + ([(points[-1], points[0])] if closed and len(points) > 2 else [])


def cuboid_lines(size):
    x, y, z = [float(value) / 2 for value in size]
    corners = [(sign_x * x, sign_y * z, sign_z * y) for sign_z in (-1, 1) for sign_y in (-1, 1) for sign_x in (-1, 1)]
    edges = ((0, 1), (0, 2), (1, 3), (2, 3), (4, 5), (4, 6), (5, 7), (6, 7), (0, 4), (1, 5), (2, 6), (3, 7))
    return [(corners[start], corners[end]) for start, end in edges]


def box_lines(minimum, maximum):
    corners = [(x, y, z) for z in (minimum[2], maximum[2]) for y in (minimum[1], maximum[1]) for x in (minimum[0], maximum[0])]
    edges = ((0, 1), (0, 2), (1, 3), (2, 3), (4, 5), (4, 6), (5, 7), (6, 7), (0, 4), (1, 5), (2, 6), (3, 7))
    return [(corners[start], corners[end]) for start, end in edges]


def circle_lines(radius, plane="XY", segments=48, center=(0, 0, 0), start_angle=0.0, end_angle=2 * pi):
    if radius <= 0:
        return []
    count = max(4, int(segments))
    center_x, center_y, center_z = center
    points = []
    for index in range(count + 1):
        theta = start_angle + (end_angle - start_angle) * index / count
        first, second = radius * cos(theta), radius * sin(theta)
        if plane == "XY":
            points.append((center_x + first, center_y + second, center_z))
        elif plane == "XZ":
            points.append((center_x + first, center_y, center_z + second))
        elif plane == "YZ":
            points.append((center_x, center_y + first, center_z + second))
        else:
            raise ValueError(f"Unsupported circle plane: {plane}")
    return lines_from_points(points)


def sphere_lines(radius, segments=40):
    lines = []
    for plane in ("XY", "XZ", "YZ"):
        lines.extend(circle_lines(radius, plane=plane, segments=segments))
    return lines


def capsule_lines(radius, height, segments=32):
    radius, height = max(0.0, float(radius)), max(0.0, float(height))
    half = height / 2
    lines = []
    for z in (-half, half):
        lines.extend(circle_lines(radius, "XY", segments, (0, 0, z)))
    for angle in (0, pi / 2, pi, 3 * pi / 2):
        x, y = radius * cos(angle), radius * sin(angle)
        lines.append(((x, y, -half), (x, y, half)))
    arc_segments = max(6, segments // 4)
    for plane in ("XZ", "YZ"):
        lines.extend(circle_lines(radius, plane, arc_segments, (0, 0, half), 0, pi))
        lines.extend(circle_lines(radius, plane, arc_segments, (0, 0, -half), pi, 2 * pi))
    return lines
