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

    def test_circles_in_3_planes(self):
        for plane in ("XY", "XZ", "YZ"):
            segments = geometry.circle_lines(4.5, plane=plane, segments=24)
            self.assertEqual(len(segments), 24)


if __name__ == "__main__":
    unittest.main()
