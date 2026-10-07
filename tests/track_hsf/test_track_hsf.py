#!/usr/bin/env python3
"""Checks for tools/track_hsf.py, the attribution tracker for the pre-HF backfill.

The tracker decides which parsed High Seas Forecast low belongs to which archive
event. A wrong attribution puts a fabricated pressure fall into a published
statistic, so most tests here try to make it pick the wrong storm, or try to
make it flatter the deepening, and check that it refuses:

  * a nearer low that would require the storm to reverse course is not chosen
    (the nearest-neighbour failure the design exists to prevent);
  * a far-away "Greenland low" is not jumped to; the track ends instead;
  * the pressure cost is symmetric in sign (mirrored candidates cost the same),
    so the search cannot prefer whichever candidate deepens the storm most;
  * 90 kt and 25 hPa / 6 h are hard rejects;
  * two consecutive missing slots end the track and nothing beyond is emitted,
    even when consistent lows exist beyond; one missing slot is bridged and
    tagged medium; a clean seeded, verified track is tagged high;
  * a dreadful link cannot be bought with the credit of a long pleasant chain
    beyond it (the 'tail pull': the search used to bridge OVER a good candidate);
  * archive fixes are pinned, honoured, and never re-emitted;
  * ids are the ids the build uses (split events keep their suffix; the same id
    in two basins is two events), and the file the tracker writes is accepted by
    build_hf_lows.py without a single refusal.

Everything runs on hand-built events and lows. Nothing here reads
data/hf_lows/precursors.csv or the HSF cache.

    python3 tests/track_hsf/test_track_hsf.py
"""
import csv
import importlib.util
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
spec = importlib.util.spec_from_file_location("track_hsf", os.path.join(ROOT, "tools", "track_hsf.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
B = T.B

T0 = 2010011012                 # first HF fix of the synthetic storm
LAT = 50.0
DLON = 3.1                      # degrees of longitude per 6 h at 50N = ~120 nm = 20 kt


def when(slot):
    return T.shift(T0, -6 * slot)


def event(fixes, basin="atl", eid="2009201001", season=2009):
    return {"basin": basin, "id": eid, "season": season, "fixes": sorted(fixes),
            "hfN": sum(1 for f in fixes if f[3] == "HF"), "minP": 960}


def storm_event(**kw):
    """The storm at t0 (970 hPa, 50N 40W) and, 6 h later, the second HF fix that seeds its heading."""
    return event([[T0, LAT, -40.0, "HF", 970], [T.shift(T0, 6), LAT, -40.0 + DLON, "HF", 968]], **kw)


def true_low(slot, pres=None, lat=LAT, **kw):
    """The storm's low `slot` slots before t0, 20 kt further west each time, a
    little shallower each time."""
    pres = 970 + 5 * slot if pres is None else pres
    return T.new_node(lat, -40.0 - DLON * slot, float(pres), **kw)


def lows_with(*per_slot, basin="atl", verified=True):
    """per_slot: {slot: [nodes]}; slot 0 gets a matching low unless verified=False."""
    out = {}
    for slot, nodes in per_slot[0].items():
        out[(basin, when(slot))] = nodes
    if verified:
        out.setdefault((basin, T0), []).append(true_low(0, 970.0))
    return out


def run(ev, lows, mode="production"):
    prep, why = T.prepare(ev, lows, mode)
    assert prep is not None, why
    return T.track(prep)


def slots_of(res):
    return [f["slot"] for f in res["fixes"]]


class CostTerms(unittest.TestCase):
    def test_pressure_cost_is_symmetric_in_sign(self):
        # The point of the term: a candidate 10 hPa deeper and one 10 hPa shallower
        # than the fix cost exactly the same, at every step length.
        for dt in (6.0, 12.0):
            for dp in (1, 4, 10, 17, 24):
                self.assertEqual(T.pressure_cost(980.0, 980.0 - dp, dt),
                                 T.pressure_cost(980.0, 980.0 + dp, dt))
                self.assertEqual(T.pressure_cost(980.0 + dp, 980.0, dt),
                                 T.pressure_cost(980.0 - dp, 980.0, dt))

    def test_mirrored_candidates_tie_in_the_whole_edge_cost(self):
        a = T.new_node(50.0, -40.0, 970.0)
        deeper = T.new_node(50.0, -43.1, 960.0)
        shallower = T.new_node(50.0, -43.1, 980.0)
        self.assertEqual(T.edge_cost(a, deeper, 6.0)[0], T.edge_cost(a, shallower, 6.0)[0])

    def test_no_term_rewards_backward_rising_pressure(self):
        # A sign-aware term would make "rises going back" cheaper than "flat". It must not.
        a = T.new_node(50.0, -40.0, 970.0)
        flat = T.new_node(50.0, -43.1, 970.0)
        rising = T.new_node(50.0, -43.1, 975.0)
        falling = T.new_node(50.0, -43.1, 965.0)
        self.assertLess(T.edge_cost(a, flat, 6.0)[0], T.edge_cost(a, rising, 6.0)[0])
        self.assertEqual(T.edge_cost(a, rising, 6.0)[0], T.edge_cost(a, falling, 6.0)[0])

    def test_speed_hard_reject_at_90_kt(self):
        a = T.new_node(50.0, -40.0, 970.0)
        # 1 degree of longitude at 50N is ~38.6 nm; 6 h at 90 kt is 540 nm = ~14 degrees
        self.assertIsNone(T.edge_cost(a, T.new_node(50.0, -40.0 - 14.2, 970.0), 6.0))
        self.assertIsNotNone(T.edge_cost(a, T.new_node(50.0, -40.0 - 12.0, 970.0), 6.0))
        self.assertEqual(T.speed_cost(90.0), None)

    def test_pressure_hard_reject_at_33_hpa_per_6h(self):
        # Calibrated on the pre-HF regime: the observed 6-h extreme is 31 hPa, so a real
        # step of 30 must not be rejected as impossible; 34 is.
        a = T.new_node(50.0, -40.0, 970.0)
        self.assertEqual(T.PRES_HARD_HPA, 33.0)
        self.assertIsNone(T.edge_cost(a, T.new_node(50.0, -43.1, 1004.0), 6.0))
        self.assertIsNone(T.edge_cost(a, T.new_node(50.0, -43.1, 936.0), 6.0))
        self.assertIsNotNone(T.pressure_cost(970.0, 1000.0, 6.0))
        self.assertIsNotNone(T.pressure_cost(970.0, 940.0, 6.0))
        # a 12 h step is allowed proportionally more (square-root of time), not twice
        self.assertIsNotNone(T.pressure_cost(970.0, 1010.0, 12.0))
        self.assertIsNone(T.pressure_cost(970.0, 1020.0, 12.0))

    def test_a_16_hpa_fall_is_cheap_in_the_pre_hf_regime(self):
        # In the mature regime (scale 8) 16 hPa in 6 h cost 4; it is 1-in-18 pre-HF, so ~1.3 now.
        self.assertLess(T.pressure_cost(970.0, 986.0, 6.0), 1.5)
        self.assertLess(T.pressure_cost(970.0, 986.0, 6.0), T.MISSING_COST)

    def test_speed_cost_shape(self):
        self.assertLess(T.speed_cost(25.0), 0.2)
        self.assertLess(T.speed_cost(45.0), 0.7)
        self.assertGreater(T.speed_cost(75.0), 3 * T.speed_cost(55.0))

    def test_heading_free_band_widens_for_short_steps(self):
        # 60 degrees on a 70 nm step is rounding noise; on a 200 nm step it is a turn.
        self.assertEqual(T.heading_cost(0.0, 70.0, 60.0, 70.0), 0.0)
        self.assertGreater(T.heading_cost(0.0, 200.0, 60.0, 200.0), 0.1)
        self.assertGreater(T.heading_cost(0.0, 200.0, 180.0, 200.0), 10.0)

    def test_reported_motion_is_a_soft_cost_only(self):
        a = T.new_node(50.0, -40.0, 970.0, vx=20.0, vy=0.0)       # printed: moving E 20 kt
        right = T.new_node(50.0, -43.1, 975.0, vx=20.0, vy=0.0)
        wrong = T.new_node(50.0, -43.1, 975.0, vx=-20.0, vy=0.0)  # printed: moving W
        self.assertLess(T.edge_cost(a, right, 6.0)[0], T.edge_cost(a, wrong, 6.0)[0])
        self.assertLessEqual(T.edge_cost(a, wrong, 6.0)[0] - T.edge_cost(a, right, 6.0)[0],
                             T.MOTION_CAP + 1e-9)


class Tracking(unittest.TestCase):
    def test_clean_track_is_recovered_and_tagged_high(self):
        ev = storm_event()
        lows = lows_with({s: [true_low(s)] for s in range(1, 5)})
        res = run(ev, lows)
        self.assertEqual(slots_of(res), [1, 2, 3, 4])
        self.assertTrue(all(f["conf"] == "high" for f in res["fixes"]),
                        [(f["slot"], f["conf"], f["cost"]) for f in res["fixes"]])
        for f in res["fixes"]:
            self.assertEqual(f["node"]["pres"], 970.0 + 5 * f["slot"])
            self.assertLess(f["match_nm"], 15.0)        # the prediction continues the seed's motion

    def test_nearest_neighbour_would_fail_and_the_tracker_does_not(self):
        # At slot 1 a low sits 58 nm east of the anchor - nearer than the true low
        # 120 nm west - but reaching it means turning round.
        near = T.new_node(LAT, -38.5, 971.0)
        ev = storm_event()
        lows = lows_with({1: [near, true_low(1)], 2: [true_low(2)]})
        res = run(ev, lows)
        first = next(f for f in res["fixes"] if f["slot"] == 1)
        self.assertEqual(first["node"]["lon"], -40.0 - DLON)
        d_near = B.great_circle_nm(LAT, -40.0, near["lat"], near["lon"])
        d_true = B.great_circle_nm(LAT, -40.0, LAT, -40.0 - DLON)
        self.assertLess(d_near, d_true)                 # i.e. nearest-neighbour would have picked it

    def test_far_away_low_is_not_jumped_to(self):
        # The probe's failures: 43N/67W -> a Greenland low at 63N/55W, a Kuroshio storm
        # -> a Gulf of Alaska low. Here a plausible-pressure low 1,100 nm away is the
        # only candidate at slot 1; the tracker emits nothing at all.
        greenland = T.new_node(68.0, -55.0, 972.0)
        res = run(storm_event(), lows_with({1: [greenland]}))
        self.assertEqual(res["fixes"], [])

    def test_two_consecutive_missing_slots_end_the_track(self):
        # True lows at slots 1-2, NOTHING at 3-4, and a perfectly consistent chain at 5-8.
        lows = lows_with({1: [true_low(1)], 2: [true_low(2)],
                          **{s: [true_low(s)] for s in range(5, 9)}})
        res = run(storm_event(), lows)
        self.assertEqual(slots_of(res), [1, 2])

    def test_one_missing_slot_is_bridged_and_tagged_medium(self):
        lows = lows_with({1: [true_low(1)], 2: [true_low(2)],       # slot 3 missing
                          **{s: [true_low(s)] for s in range(4, 7)}})
        res = run(storm_event(), lows)
        self.assertEqual(slots_of(res), [1, 2, 4, 5, 6])
        conf = {f["slot"]: f["conf"] for f in res["fixes"]}
        self.assertEqual((conf[1], conf[2]), ("high", "high"))
        self.assertEqual((conf[4], conf[5], conf[6]), ("medium", "medium", "medium"))

    def test_second_bridged_gap_makes_the_rest_low(self):
        lows = lows_with({s: [true_low(s)] for s in (1, 2, 4, 6, 7)})   # 3 and 5 missing
        res = run(storm_event(), lows)
        conf = {f["slot"]: f["conf"] for f in res["fixes"]}
        self.assertEqual(conf[4], "medium")
        self.assertEqual((conf[6], conf[7]), ("low", "low"))

    def test_unverified_anchor_or_missing_seed_cannot_be_high(self):
        lows = lows_with({s: [true_low(s)] for s in range(1, 4)}, verified=False)
        res = run(storm_event(), lows)
        self.assertTrue(res["fixes"])
        self.assertTrue(all(f["conf"] == "medium" for f in res["fixes"]))
        lows = lows_with({s: [true_low(s)] for s in range(1, 4)})
        single = event([[T0, LAT, -40.0, "HF", 970]])                     # one HF fix: no seed
        res = run(single, lows)
        self.assertTrue(all(f["conf"] == "medium" for f in res["fixes"]))

    def test_two_equally_good_candidates_are_ambiguous_and_low(self):
        twin = T.new_node(LAT + 3.0, -40.0 - DLON, 975.0)      # 180 nm from the true low, same pressure
        lows = lows_with({1: [true_low(1, 975.0), twin]})
        res = run(storm_event(), lows)
        self.assertEqual(slots_of(res), [1])
        self.assertEqual(res["fixes"][0]["conf"], "low")

    def test_duplicate_listing_of_one_low_is_not_ambiguity(self):
        # the product listed the same low in its warning and its synopsis: 10 nm apart, 1 hPa apart
        dup = T.new_node(LAT + 0.17, -40.0 - DLON, 976.0)
        lows = lows_with({1: [true_low(1, 975.0), dup]})
        res = run(storm_event(), lows)
        self.assertEqual(res["fixes"][0]["conf"], "high")

    def test_a_dreadful_link_cannot_be_bought_with_a_pleasant_chain_beyond_it(self):
        # Slot 1 holds the right low. Slot 2 has nothing consistent, so the right chain
        # stops after one fix. Far to the north-west a different storm has a flawless
        # chain at slots 3-12, joined to the anchor only by a 12 h step that costs more
        # than a gap. The search must keep the good near fix and not bridge over it.
        wrong = {s: [T.new_node(62.0, -60.0 - 1.0 * s, 975.0 + s)] for s in range(2, 13)}
        lows = lows_with({1: [true_low(1)], **wrong})
        res = run(storm_event(), lows)
        self.assertEqual(slots_of(res)[:1], [1])
        self.assertNotIn(62.0, [f["node"]["lat"] for f in res["fixes"]])

    def test_the_pressure_term_never_selects_for_deepening(self):
        # Two candidates at the same place, 10 hPa deeper / 10 hPa shallower than the
        # anchor-consistent value. Whichever is chosen, the choice is not based on the
        # sign: they cost the same, so the tracker calls it ambiguous rather than
        # picking the deeper storm.
        a = true_low(1, 980.0)
        b = true_low(1, 960.0)
        res = run(storm_event(), lows_with({1: [a, b]}))
        self.assertEqual(res["fixes"][0]["conf"], "low")
        self.assertAlmostEqual(res["ambiguous"][1], 0.0, places=6)

    def test_window_stops_at_72_hours(self):
        lows = lows_with({s: [true_low(s)] for s in range(1, 20)})
        res = run(storm_event(), lows)
        self.assertEqual(max(slots_of(res)), 12)
        self.assertTrue(all(0 < (B.to_dt(T0) - B.to_dt(f["valid"])).total_seconds() / 3600 <= 72
                            for f in res["fixes"]))

    def test_no_row_is_ever_at_or_after_t0(self):
        lows = lows_with({s: [true_low(s)] for s in range(1, 5)})
        lows[("atl", T.shift(T0, 6))] = [T.new_node(LAT, -36.9, 968.0)]
        res = run(storm_event(), lows)
        self.assertTrue(all(f["valid"] < T0 for f in res["fixes"]))


class ArchiveFixes(unittest.TestCase):
    def test_archive_lead_fixes_are_pinned_used_and_not_reemitted(self):
        ev = storm_event()
        ev["fixes"].append([when(2), LAT, -40.0 - 2 * DLON, "DHF", 980])
        ev["fixes"].sort()
        lows = lows_with({s: [true_low(s)] for s in range(1, 6)})
        res = run(ev, lows)
        self.assertNotIn(2, slots_of(res))                       # the archive owns slot 2
        self.assertEqual(sorted(slots_of(res)), [1, 3, 4, 5])
        self.assertTrue(all(f["conf"] == "high" for f in res["fixes"]),
                        [(f["slot"], f["conf"]) for f in res["fixes"]])

    def test_hidden_mode_ignores_the_archive_pre_hf_fixes(self):
        ev = storm_event()
        ev["fixes"].append([when(1), LAT, -40.0 - DLON, "DHF", 975])
        lows = lows_with({1: [T.new_node(LAT, -40.0 - DLON, 975.0)]})
        res = run(ev, lows, "hidden")
        self.assertEqual(slots_of(res), [1])                     # recovered from the HSF alone
        prep, _ = T.prepare(ev, lows, "production")
        self.assertTrue(prep["slots"][1][0]["pinned"])

    def test_events_that_cannot_be_anchored_are_not_tracked(self):
        lows = lows_with({1: [true_low(1)]})
        no_pres = event([[T0, LAT, -40.0, "HF", None]])
        self.assertEqual(T.prepare(no_pres, lows)[1], "anchor-no-pressure")
        dup = storm_event()
        dup["fixes"].append([when(2), LAT, -50.0, "S", 985])
        dup["fixes"].append([when(2), LAT, -46.0, "S", 984])
        self.assertEqual(T.prepare(dup, lows)[1], "duplicate-times")
        no_hf = event([[T0, LAT, -40.0, "DHF", 970]])
        self.assertEqual(T.prepare(no_hf, lows)[1], "no-hf-fix")


class ArchiveSuspects(unittest.TestCase):
    """A mistyped archive coordinate is found by the HSF, listed, and never anchored on."""

    def setUp(self):
        T.ARCHIVE_SUSPECTS.clear()

    tearDown = setUp

    def typo_event(self):
        # DHF lead fix at slot 1 typed 10 degrees of longitude wrong (west of where it was)
        ev = storm_event()
        ev["fixes"].append([when(1), LAT, -40.0 - DLON - 10.0, "DHF", 975])
        ev["fixes"].sort()
        return ev

    def test_same_pressure_low_that_removes_an_implausible_leg_is_listed(self):
        ev = self.typo_event()
        lows = lows_with({1: [T.new_node(LAT, -40.0 - DLON, 975.0)]})
        found = T.archive_position_suspects([ev], lows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["valid"], when(1))
        self.assertGreater(found[0]["speed_before"], 60.0)
        self.assertLess(found[0]["speed_after"], 50.0)

    def test_equal_pressure_alone_is_not_evidence(self):
        # A different low with the same pressure, but the archive track is perfectly plausible
        ev = storm_event()
        ev["fixes"].append([when(1), LAT, -40.0 - DLON, "DHF", 975])
        far = T.new_node(62.0, -55.0, 975.0)
        self.assertEqual(T.archive_position_suspects([ev], lows_with({1: [far]})), [])

    def test_a_suspect_anchor_or_pinned_fix_is_not_tracked(self):
        ev = self.typo_event()
        lows = lows_with({1: [T.new_node(LAT, -40.0 - DLON, 975.0)]})
        T.set_suspects([ev], lows)
        self.assertEqual(T.prepare(ev, lows, "production")[1], "archive-suspect")
        # hidden mode ignores the pre-HF fix, so only a suspect ANCHOR blocks it
        self.assertIsNotNone(T.prepare(ev, lows, "hidden")[0])
        T.ARCHIVE_SUSPECTS.add((ev["basin"], ev["id"], T0))
        self.assertEqual(T.prepare(ev, lows, "hidden")[1], "archive-suspect")


class RecoveredOnlyChains(unittest.TestCase):
    def setUp(self):
        T.ARCHIVE_SUSPECTS.clear()

    def test_chain_hours_ignore_the_archives_own_lead_fixes(self):
        ev = storm_event()
        ev["fixes"].append([when(2), LAT, -40.0 - 2 * DLON, "DHF", 980])   # archive owns slot 2
        ev["fixes"].sort()
        lows = lows_with({s: [true_low(s)] for s in range(1, 6)})
        c = T.hidden_chains([ev], lows)[0]
        self.assertEqual((c["chain_h_any"], c["chain_h_usable"], c["chain_h_high"]), (30, 30, 30))
        # while the production rows skip slot 2, which is why the sidecar exists
        prod = run(ev, lows)
        self.assertNotIn(2, slots_of(prod))

    def test_a_gap_ends_the_chain_hours(self):
        lows = lows_with({1: [true_low(1)], 2: [true_low(2)], 4: [true_low(4)]})
        c = T.hidden_chains([storm_event()], lows)[0]
        self.assertEqual(c["chain_h_usable"], 12)


class Output(unittest.TestCase):
    def rows(self, res):
        return T.rows_for(res)

    def test_columns_and_format_match_the_contract(self):
        self.assertEqual(T.COLUMNS, ["basin", "event_id", "valid", "lat", "lon", "pres",
                                     "warn_cat", "source", "match_nm", "conf"])
        res = run(storm_event(), lows_with({1: [true_low(1, cat="S")]}))
        row = self.rows(res)[0]
        self.assertEqual(row[:2], ["atl", "2009201001"])
        self.assertEqual(row[2], "2010-01-10T06:00:00Z")
        self.assertEqual(row[6], "S")
        self.assertEqual(row[7], "hsf")
        self.assertIn(row[9], ("high", "medium", "low"))

    def test_same_event_id_in_two_basins_stays_two_events(self):
        a = storm_event(basin="atl", eid="2006200718")
        p = storm_event(basin="pac", eid="2006200718")
        lows = lows_with({1: [true_low(1)]}, basin="atl")
        lows.update(lows_with({1: [true_low(1)]}, basin="pac"))
        rows = self.rows(run(a, lows)) + self.rows(run(p, lows))
        self.assertEqual({(r[0], r[1]) for r in rows}, {("atl", "2006200718"), ("pac", "2006200718")})

    def test_the_build_accepts_what_the_tracker_writes(self):
        lows = lows_with({s: [true_low(s)] for s in range(1, 6)})
        res = run(storm_event(), lows)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "precursors.csv")
            n = T.write_csv(path, [res], [])
            self.assertEqual(n, 5)
            qc = B.QC()
            records, _ = B.read_precursors(path, qc)
            self.assertEqual(len(records), 5)
            self.assertEqual(qc.counts.get("precursorsRefused", 0), 0, qc.notes)

    def test_the_build_refuses_low_but_the_tracker_still_emits_it(self):
        # Spec: emit all three grades; the build decides. A low row is refused by the build.
        twin = T.new_node(LAT + 3.0, -40.0 - DLON, 975.0)
        res = run(storm_event(), lows_with({1: [true_low(1, 975.0), twin]}))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "precursors.csv")
            T.write_csv(path, [res], [])
            qc = B.QC()
            records, _ = B.read_precursors(path, qc)
            self.assertEqual(records, [])
            self.assertEqual([n["kind"] for n in qc.notes], ["precursor-low-conf"])


class CollisionQC(unittest.TestCase):
    def test_a_fix_on_another_events_fix_is_noted_and_kept(self):
        mine = storm_event(eid="2009201001")
        other = event([[when(1), LAT, -40.0 - DLON, "HF", 976], [when(0), LAT, -40.5, "HF", 972]],
                      eid="2009201002")
        res = run(mine, lows_with({1: [true_low(1)]}))
        notes = T.collisions([res], [mine, other])
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["event"], notes[0]["other"]), ("2009201001", "2009201002"))
        self.assertEqual(len(res["fixes"]), 1)                       # not dropped

    def test_a_distant_event_is_not_a_collision(self):
        mine = storm_event(eid="2009201001")
        far = event([[when(1), 40.0, -20.0, "HF", 976]], eid="2009201002")
        res = run(mine, lows_with({1: [true_low(1)]}))
        self.assertEqual(T.collisions([res], [mine, far]), [])

    def test_other_basin_is_not_compared(self):
        mine = storm_event(eid="2006200718")
        other = event([[when(1), LAT, -40.0 - DLON, "HF", 976]], basin="pac", eid="2006200718")
        res = run(mine, lows_with({1: [true_low(1)]}))
        self.assertEqual(T.collisions([res], [mine, other]), [])


class RealArchiveIds(unittest.TestCase):
    """The ids come from the build's own reader, split rule and all."""

    @classmethod
    def setUpClass(cls):
        cls.events = T.load_events()

    def test_split_events_carry_their_suffix(self):
        ids = {(e["basin"], e["id"]) for e in self.events}
        split = [e for e in self.events if e.get("split")]
        self.assertTrue(split, "the archive has split events")
        self.assertIn(("atl", "2024202508b"), ids)
        bases = {(e["basin"], e["id"][:-1]) for e in split}
        self.assertTrue(bases.isdisjoint(ids), "an unsuffixed base id of a split event is emitted")

    def test_the_same_id_in_both_basins_is_two_events(self):
        ids = [(e["basin"], e["id"]) for e in self.events]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(("atl", "2006200718"), ids)
        self.assertIn(("pac", "2006200718"), ids)

    def test_a_row_for_a_split_event_is_accepted_by_the_build(self):
        ev = next(e for e in self.events if e["basin"] == "atl" and e["id"] == "2024202508b")
        hf = next(f for f in sorted(ev["fixes"]) if f[3] == "HF")
        have = {f[0] for f in ev["fixes"]}
        slot = next(s for s in range(1, 13) if T.shift(hf[0], -6 * s) not in have)
        prev = T.new_node(hf[1], hf[2], hf[4] + 4.0)
        prep, why = T.prepare(ev, {("atl", T.shift(hf[0], -6 * slot)): [prev]})
        self.assertIsNotNone(prep, why)
        res = T.track(prep)
        res["fixes"] = [{"slot": slot, "valid": T.shift(hf[0], -6 * slot), "node": prev,
                         "conf": "high", "cost": 0.0, "gap_before": 0, "match_nm": 0.0, "ambiguity": 99}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.csv")
            T.write_csv(path, [res], [])
            payload = B.build(precursors=path)
        kinds = [n["kind"] for n in payload["qc"]["notes"] if n["kind"].startswith("precursor")]
        self.assertNotIn("precursor-ambiguous-id", kinds)
        self.assertNotIn("precursor-unknown-event", kinds)
        self.assertEqual(payload["qc"]["counts"].get("precursorsAccepted"), 1)


@unittest.skipUnless(os.path.exists(T.LOWS_CSV), "data/hf_lows/hsf_lows.csv not generated")
class Calibration(unittest.TestCase):
    def test_shipped_constants_follow_their_stated_rule(self):
        events = T.load_events()
        lows = T.load_lows()
        costs = T.true_step_costs(events, lows)
        self.assertAlmostEqual(T.MISSING_COST, T.quantile(costs, 0.95), delta=0.25)
        self.assertAlmostEqual(T.LOW_BAND_COST, T.quantile(costs, 0.90), delta=0.25)
        self.assertAlmostEqual(T.AMBIGUITY_MARGIN, T.quantile(costs, 0.75), delta=0.25)


if __name__ == "__main__":
    unittest.main(verbosity=1)
