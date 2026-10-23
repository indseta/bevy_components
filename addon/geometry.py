from math import ceil, cos, dist, hypot, pi, sin, sqrt

FIT_DIGITS = 6


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


def _add(first, second):
    return tuple(a + b for a, b in zip(first, second))


def _scaled(vector, factor):
    return tuple(value * factor for value in vector)


def _dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def _cross(first, second):
    return (first[1] * second[2] - first[2] * second[1], first[2] * second[0] - first[0] * second[2], first[0] * second[1] - first[1] * second[0])


def normalized(vector):
    length = sqrt(_dot(vector, vector))
    return _scaled(vector, 1.0 / length) if length > 1e-9 else (0.0, 0.0, 0.0)


def perpendicular(axis, preferred=(1.0, 0.0, 0.0)):
    for candidate in (preferred, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)):
        projected = _add(candidate, _scaled(axis, -_dot(candidate, axis)))
        if _dot(projected, projected) > 1e-8:
            return normalized(projected)
    return (1.0, 0.0, 0.0)


def rotate(vector, axis, angle):
    return _add(_add(_scaled(vector, cos(angle)), _scaled(_cross(axis, vector), sin(angle))), _scaled(axis, _dot(axis, vector) * (1 - cos(angle))))


def arc_lines(axis, reference, radius, start_angle, end_angle, center=(0.0, 0.0, 0.0), segments=48):
    count = max(2, ceil(segments * abs(end_angle - start_angle) / (2 * pi)))
    points = [_add(center, _scaled(rotate(reference, axis, start_angle + (end_angle - start_angle) * index / count), radius)) for index in range(count + 1)]
    return lines_from_points(points)


def arrow_lines(start, end, head=None):
    direction = tuple(b - a for a, b in zip(start, end))
    length = sqrt(_dot(direction, direction))
    if length <= 1e-9:
        return []
    direction = _scaled(direction, 1.0 / length)
    head = min(length * 0.4, 0.15) if head is None else head
    side = perpendicular(direction)
    other = _cross(direction, side)
    back = _add(end, _scaled(direction, -head))
    return [(tuple(start), tuple(end))] + [(tuple(end), _add(back, _scaled(offset, head * 0.5))) for offset in (side, _scaled(side, -1), other, _scaled(other, -1))]


def spin_lines(axis, radius, center=(0.0, 0.0, 0.0), sweep=1.5 * pi):
    axis = normalized(axis)
    reference = perpendicular(axis)
    lines = arc_lines(axis, reference, radius, 0.0, sweep, center)
    tip = _add(center, _scaled(rotate(reference, axis, sweep), radius))
    tangent = _cross(axis, rotate(reference, axis, sweep))
    return lines + arrow_lines(_add(tip, _scaled(tangent, -radius * 0.3)), tip)[1:]


def joint_lines(kind, axis, reference, size, limits=None, swing=None):
    axis = normalized(axis)
    reference = normalized(reference)
    origin = (0.0, 0.0, 0.0)
    if kind == "FIXED":
        half = size * 0.15
        return box_lines((-half, -half, -half), (half, half, half))
    if kind == "REVOLUTE":
        lines = [(_scaled(axis, -size), _scaled(axis, size)), (origin, _scaled(reference, size))]
        if limits is None:
            return lines + arc_lines(axis, reference, size, 0.0, 2 * pi)
        return lines + arc_lines(axis, reference, size, limits[0], limits[1]) + [(origin, _scaled(rotate(reference, axis, angle), size)) for angle in limits]
    if kind == "PRISMATIC":
        if limits is None:
            return arrow_lines(origin, _scaled(axis, size * 2)) + arrow_lines(origin, _scaled(axis, -size * 2))
        side = _cross(axis, reference)
        lines = [(_scaled(axis, limits[0]), _scaled(axis, limits[1]))]
        for distance, tick in ((limits[0], size * 0.2), (limits[1], size * 0.2), (0.0, size * 0.1)):
            point = _scaled(axis, distance)
            lines.extend([(_add(point, _scaled(reference, -tick)), _add(point, _scaled(reference, tick))), (_add(point, _scaled(side, -tick)), _add(point, _scaled(side, tick)))])
        return lines
    if kind == "SPHERICAL":
        lines = sphere_lines(size * 0.15, segments=16) + [(origin, _scaled(axis, size))]
        if swing is not None:
            base = _scaled(axis, size * cos(swing))
            lines.extend(arc_lines(axis, reference, size * sin(swing), 0.0, 2 * pi, base))
            lines.extend((origin, _add(base, _scaled(rotate(reference, axis, angle), size * sin(swing)))) for angle in (0.0, pi / 2, pi, 3 * pi / 2))
        if limits is not None:
            tip = _scaled(axis, size)
            lines.extend(arc_lines(axis, reference, size * 0.4, limits[0], limits[1], tip))
            lines.extend((tip, _add(tip, _scaled(rotate(reference, axis, angle), size * 0.4))) for angle in limits)
        return lines
    raise ValueError(f"Unsupported joint type: {kind}")


def voxel_lines(size, counts, limit=4096):
    if counts is None or counts[0] * counts[1] * counts[2] > limit:
        return []
    marker = min(float(length) / count for length, count in zip(size, counts)) * 0.1
    lines = []
    for x in range(counts[0]):
        for y in range(counts[1]):
            for z in range(counts[2]):
                center_x, center_y, center_z = [((index + 0.5) / count - 0.5) * float(length) for index, count, length in zip((x, y, z), counts, size)]
                point = (center_x, -center_z, center_y)
                for axis in range(3):
                    start, end = list(point), list(point)
                    start[axis] -= marker
                    end[axis] += marker
                    lines.append((tuple(start), tuple(end)))
    return lines


def cone_lines(length, angle, segments=48):
    if length <= 0:
        return []
    depth, radius = -length * cos(angle), length * sin(angle)
    lines = circle_lines(radius, "XY", segments, (0, 0, depth))
    for theta in (0, pi / 2, pi, 3 * pi / 2):
        lines.append(((0, 0, 0), (radius * cos(theta), radius * sin(theta), depth)))
    arc_segments = max(4, segments // 4)
    for plane in ("XZ", "YZ"):
        lines.extend(circle_lines(length, plane, arc_segments, (0, 0, 0), 3 * pi / 2 - angle, 3 * pi / 2 + angle))
    return lines


def fit_shape(shape, points):
    points = [(x, z, -y) for x, y, z in points]
    minimum = [min(point[axis] for point in points) for axis in range(3)]
    maximum = [max(point[axis] for point in points) for axis in range(3)]
    center = _snapped((low + high) / 2 for low, high in zip(minimum, maximum))
    if shape == "SPHERE":
        return {"radius": round(max(dist(center, point) for point in points), FIT_DIGITS), "offset": center}
    if shape == "CAPSULE":
        radius = round(max(hypot(point[0] - center[0], point[2] - center[2]) for point in points), FIT_DIGITS)
        return {"radius": radius, "height": round(max(0.0, maximum[1] - minimum[1] - 2 * radius), FIT_DIGITS), "offset": center}
    return {"size": _snapped(high - low for low, high in zip(minimum, maximum)), "offset": center}


def _snapped(values):
    return tuple(round(value, FIT_DIGITS) + 0.0 for value in values)
