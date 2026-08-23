import importlib.util
import pathlib
import unittest

P=pathlib.Path(__file__).with_name("verify_power_and_return_paths_v2.py")
S=importlib.util.spec_from_file_location("receiver_verifier",P); V=importlib.util.module_from_spec(S); S.loader.exec_module(V)

class PureGeometryTests(unittest.TestCase):
    def test_parallel_speaker_gap(self):
        p=[{"start":(0,0),"end":(10,0),"width_mm":.25}]; m=[{"start":(0,.5),"end":(10,.5),"width_mm":.25}]
        self.assertAlmostEqual(V.analyze_speaker_geometry(p,m)["minimum_copper_gap_mm"],.25)
    def test_speaker_crossing(self):
        p=[{"start":(0,0),"end":(2,2),"width_mm":.25}]; m=[{"start":(0,2),"end":(2,0),"width_mm":.25}]
        self.assertEqual(V.analyze_speaker_geometry(p,m)["crossing_count"],1)
    def test_branch_neck_uses_longest_shortest_path(self):
        got=V.shortest_neck_distances([("t","a",.934),("t","b",.934)],{"t"},{"A":{"a"},"B":{"b"}})
        self.assertAlmostEqual(max(got.values()),.934)
    def test_serial_neck_accumulates(self):
        got=V.shortest_neck_distances([("t","a",.6),("a","b",.6)],{"t"},{"B":{"b"}})
        self.assertAlmostEqual(got["B"],1.2)
    def test_orphan_wide_track_does_not_inflate_ratio(self):
        rows=[{"root":1,"width_mm":.25,"length_mm":1},{"root":1,"width_mm":.5,"length_mm":1},{"root":2,"width_mm":.5,"length_mm":100}]
        got=V.connected_wide_ratio(rows,1,.5); self.assertAlmostEqual(got["wide_ratio"],.5); self.assertEqual(got["disconnected_segment_count"],1)
    def test_bbox_edge(self):
        self.assertAlmostEqual(V.bbox_to_rect_edge_clearance((.3,1,2,2),(0,0,10,10)),.3)
    def test_kelvin_sense_only_skips_neck_threshold(self):
        self.assertFalse(V.neck_threshold_applies("3V3","U2","6"))
        self.assertTrue(V.neck_threshold_applies("3V3","U1","9"))
if __name__=="__main__": unittest.main()
