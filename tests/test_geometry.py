import importlib.util
import math
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / 'bevy_components' / 'geometry.py'
spec = importlib.util.spec_from_file_location('bevy_geometry', MODULE)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class TestGeometry(unittest.TestCase):
    def test_cuboid_has_twelve_edges_and_correct_bevy_axes(self):
        lines = g.cuboid_lines((2, 4, 6))
        self.assertEqual(len(lines), 12)
        coords = [point for segment in lines for point in segment]
        self.assertEqual((min(p[0] for p in coords), max(p[0] for p in coords)), (-1.0, 1.0))
        self.assertEqual((min(p[1] for p in coords), max(p[1] for p in coords)), (-3.0, 3.0))
        self.assertEqual((min(p[2] for p in coords), max(p[2] for p in coords)), (-2.0, 2.0))

    def test_sphere_rings_reach_radius(self):
        coords = [p for s in g.sphere_lines(3, 12) for p in s]
        self.assertTrue(all(abs(math.dist((0, 0, 0), p) - 3) < 1e-5 for p in coords))

    def test_capsule_z_length(self):
        segments = g.capsule_lines(0.5, 2.0)
        zs = [p[2] for line in segments for p in line]
        self.assertAlmostEqual(max(zs), 1.5)
        self.assertAlmostEqual(min(zs), -1.5)

    def test_circles_in_3_planes(self):
        for plane in ('XY', 'XZ', 'YZ'):
            segments = g.circle_lines(4.5, plane=plane, segments=24)
            self.assertEqual(len(segments), 24)

    def test_spawn_forward(self):
        lines = g.spawn_marker_lines()
        self.assertIn(((0, 0, 0), (0, 0.9, 0)), lines)


if __name__ == '__main__':
    unittest.main()
