"""Unit tests for the risk rules. Run: python3 -m unittest pipelines/test_risk_job.py  (stdlib only)."""
import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from risk_job import score_fleet, score_shipment  # noqa: E402

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
H = lambda h: NOW + timedelta(hours=h)

# Three legs along the equator: A(0,0)->B(0,10)->C(0,20)->D(0,30). Leg 1 is in progress at NOW.
POINTS = [("A", 0, 0), ("B", 0, 10), ("C", 0, 20), ("D", 0, 30)]


def legs(starts=(-6, 30, 80)):
    out = []
    for i, (a, b) in enumerate(zip(POINTS, POINTS[1:])):
        out.append({"shipment_id": "S", "seq": i + 1, "mode": "truck", "from_name": a[0], "from_lat": a[1], "from_lon": a[2],
                    "to_name": b[0], "to_lat": b[1], "to_lon": b[2], "geometry": [[a[1], a[2]], [b[1], b[2]]],
                    "planned_start": iso(H(starts[i])), "planned_end": iso(H(starts[i] + 24))})
    return out


def event(lon, status, start, end, lat=0.0, radius=30, eid="E"):
    return {"event_id": eid, "type": "strike", "status": status, "location": "X", "lat": lat, "lon": lon,
            "radius_km": radius, "window_start": iso(H(start)), "window_end": iso(H(end))}


def level(ev, starts=(-6, 30, 80)):
    return score_shipment(legs(starts), [ev] if ev else [], NOW)[0]


class Rules(unittest.TestCase):
    def test_1_clear_without_events(self):
        self.assertEqual(level(None), 1)

    def test_1_event_far_from_route(self):
        self.assertEqual(level(event(5, "confirmed", -1, 48, lat=40)), 1)

    def test_5_confirmed_on_current_leg(self):
        self.assertEqual(level(event(5, "confirmed", 0, 20)), 5)

    def test_5_confirmed_on_next_leg(self):
        self.assertEqual(level(event(15, "confirmed", 30, 50)), 5)

    def test_4_confirmed_on_later_leg_over_24h(self):
        self.assertEqual(level(event(25, "confirmed", 80, 100)), 4)

    def test_5_confirmed_later_leg_starting_within_24h(self):
        # third leg starts in 10 h, so it is not "more than 24 h away"
        self.assertEqual(level(event(25, "confirmed", 10, 40), starts=(-6, 5, 10)), 5)

    def test_3_suspected_within_72h(self):
        self.assertEqual(level(event(15, "suspected", 30, 50)), 3)

    def test_2_suspected_over_72h(self):
        self.assertEqual(level(event(25, "suspected", 80, 100)), 2)

    def test_3_confirmed_near_but_not_on_route(self):
        self.assertEqual(level(event(5, "confirmed", 0, 20, lat=1.0, radius=30)), 3)  # ~111 km off, inside radius+100

    def test_1_suspected_near_but_not_on_route(self):
        self.assertEqual(level(event(5, "suspected", 0, 20, lat=1.0, radius=30)), 1)

    def test_event_outside_leg_time_window_is_ignored(self):
        self.assertEqual(level(event(25, "confirmed", 200, 220)), 1)

    def test_finished_event_is_ignored(self):
        self.assertEqual(level(event(5, "confirmed", -40, -10)), 1)

    def test_finished_leg_does_not_count(self):
        # the event sits on leg 1 but leg 1 is the current leg; move it to a leg that already ended
        st = (-60, -30, 10)  # legs 1 and 2 finished before NOW, leg 3 current
        self.assertEqual(level(event(5, "confirmed", -60, 50), starts=st), 1)

    def test_max_wins_and_ids_are_top_level_only(self):
        evs = [event(25, "suspected", 80, 100, eid="E-low"), event(5, "confirmed", 0, 20, eid="E-high")]
        lvl, _, ids = score_shipment(legs(), evs, NOW)
        self.assertEqual((lvl, ids), (5, ["E-high"]))

    def test_all_legs_finished_is_clear(self):
        self.assertEqual(score_shipment(legs((-100, -80, -60)), [event(5, "confirmed", -100, 50)], NOW)[0], 1)

    def test_fleet_rows_match_contract_shape(self):
        rows = score_fleet([{"shipment_id": "S"}], legs(), [event(5, "confirmed", 0, 20)], NOW)
        self.assertEqual(set(rows[0]), {"shipment_id", "level", "reason", "event_ids"})

    def test_deterministic(self):
        a = score_fleet([{"shipment_id": "S"}], legs(), [event(15, "suspected", 30, 50)], NOW)
        self.assertEqual(a, score_fleet([{"shipment_id": "S"}], legs(), [event(15, "suspected", 30, 50)], NOW))


if __name__ == "__main__":
    unittest.main()
