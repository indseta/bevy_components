import importlib.util
import math
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "addon" / "geometry.py"
spec = importlib.util.spec_from_file_location("bevy_geometry", MODULE)
geometry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geometry)


class TestGeometry(unittest.TestCase):
    def test_cuboid_has_twelve_edges_and_correct_bevy_axes(self):
        lines = geometry.cuboid_lines((2, 4, 6))
        self.assertEqual(len(lines), 12)
        points = [point for segment in lines for point in segment]
        self.assertEqual((min(point[0] for point in points), max(point[0] for point in points)), (-1.0, 1.0))
        self.assertEqual((min(point[1] for point in points), max(point[1] for point in points)), (-3.0, 3.0))
        self.assertEqual((min(point[2] for point in points), max(point[2] for point in points)), (-2.0, 2.0))

    def test_box_spans_its_corners(self):
        lines = geometry.box_lines((-1, -2, -3), (1, 2, 3))
        self.assertEqual(len(lines), 12)
        self.assertEqual({point for line in lines for point in line}, {(x, y, z) for x in (-1, 1) for y in (-2, 2) for z in (-3, 3)})
        self.assertTrue(all(sum(start != end for start, end in zip(*line)) == 1 for line in lines))

    def test_sphere_rings_reach_radius(self):
        points = [point for segment in geometry.sphere_lines(3, 12) for point in segment]
        self.assertTrue(all(abs(math.dist((0, 0, 0), point) - 3) < 1e-5 for point in points))

    def test_capsule_z_length(self):
        segments = geometry.capsule_lines(0.5, 2.0)
        heights = [point[2] for line in segments for point in line]
        self.assertAlmostEqual(max(heights), 1.5)
        self.assertAlmostEqual(min(heights), -1.5)

    def test_cone_points_down_negative_z_within_its_angle(self):
        lines = geometry.cone_lines(10, math.radians(30))
        points = [point for line in lines for point in line]
        self.assertAlmostEqual(max(math.dist((0, 0, 0), point) for point in points), 10)
        self.assertTrue(all(point[2] <= 1e-9 for point in points))
        self.assertTrue(all(math.acos(-point[2] / math.dist((0, 0, 0), point)) <= math.radians(30) + 1e-9 for point in points if math.dist((0, 0, 0), point) > 1e-9))
        self.assertAlmostEqual(max(math.hypot(point[0], point[1]) for point in points), 5)
        self.assertEqual(geometry.cone_lines(0, 0.5), [])

    def test_circles_in_3_planes(self):
        for plane in ("XY", "XZ", "YZ"):
            segments = geometry.circle_lines(4.5, plane=plane, segments=24)
            self.assertEqual(len(segments), 24)

    def test_rotate_follows_the_right_hand_rule(self):
        rotated = geometry.rotate((1, 0, 0), (0, 0, 1), math.pi / 2)
        self.assertEqual(tuple(round(value, 6) for value in rotated), (0.0, 1.0, 0.0))

    def test_perpendicular_prefers_the_given_direction(self):
        self.assertEqual(geometry.perpendicular((0, 0, 1), (3, 0, 5)), (1.0, 0.0, 0.0))
        self.assertEqual(geometry.perpendicular((1, 0, 0), (2, 0, 0)), (0.0, 1.0, 0.0))
        self.assertEqual(geometry.perpendicular((0, 0, 1), (0, 0, 0)), (1.0, 0.0, 0.0))

    def test_arcs_span_their_angles(self):
        lines = geometry.arc_lines((0, 0, 1), (1, 0, 0), 2.0, 0.0, math.pi / 2)
        self.assertEqual(tuple(round(value, 6) for value in lines[0][0]), (2.0, 0.0, 0.0))
        self.assertEqual(tuple(round(value, 6) for value in lines[-1][1]), (0.0, 2.0, 0.0))
        self.assertTrue(all(abs(math.dist((0, 0, 0), point) - 2) < 1e-6 for line in lines for point in line))

    def test_arrow_has_a_shaft_and_head(self):
        lines = geometry.arrow_lines((0, 0, 0), (0, 0, 2))
        self.assertEqual(lines[0], ((0, 0, 0), (0, 0, 2)))
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(line[0] == (0, 0, 2) and line[1][2] < 2 for line in lines[1:]))
        self.assertEqual(geometry.arrow_lines((1, 1, 1), (1, 1, 1)), [])

    def test_hinge_limits_sweep_from_min_to_max(self):
        lines = geometry.joint_lines("REVOLUTE", (0, 0, 1), (1, 0, 0), 1.0, (0.0, math.pi / 2))
        points = {tuple(round(value, 6) for value in point) for line in lines for point in line}
        self.assertIn((0.0, 0.0, 1.0), points)
        self.assertIn((0.0, 1.0, 0.0), points)
        self.assertNotIn((0.0, -1.0, 0.0), points)
        free = geometry.joint_lines("REVOLUTE", (0, 0, 1), (1, 0, 0), 1.0)
        self.assertIn((0.0, -1.0, 0.0), {tuple(round(value, 6) for value in point) for line in free for point in line})

    def test_slider_limits_span_the_axis(self):
        lines = geometry.joint_lines("PRISMATIC", (1, 0, 0), (0, 1, 0), 0.5, (-0.25, 1.5))
        self.assertEqual(lines[0], ((-0.25, 0.0, 0.0), (1.5, 0.0, 0.0)))
        extent = [point[0] for line in geometry.joint_lines("PRISMATIC", (1, 0, 0), (0, 1, 0), 0.5) for point in line]
        self.assertEqual((min(extent), max(extent)), (-1.0, 1.0))

    def test_ball_swing_cone_opens_around_the_axis(self):
        lines = geometry.joint_lines("SPHERICAL", (0, 0, 1), (1, 0, 0), 1.0, None, math.pi / 4)
        tips = [line[1] for line in lines[-4:]]
        self.assertTrue(all(abs(math.degrees(math.acos(point[2] / math.dist((0, 0, 0), point))) - 45) < 1e-6 for point in tips))

    def test_fixed_joint_is_a_small_box(self):
        lines = geometry.joint_lines("FIXED", (0, 1, 0), (1, 0, 0), 1.0)
        self.assertEqual(len(lines), 12)
        self.assertEqual(max(abs(value) for line in lines for point in line for value in point), 0.15)

    def test_spin_arrow_circles_the_axis(self):
        lines = geometry.spin_lines((0, 0, 2), 0.5, (1, 1, 1))
        arc = lines[:-4]
        self.assertTrue(all(abs(point[2] - 1) < 1e-6 and abs(math.dist((1, 1, 1), point) - 0.5) < 1e-6 for line in arc for point in line))
        self.assertTrue(all(line[0] == arc[-1][1] for line in lines[-4:]))


if __name__ == "__main__":
    unittest.main()
