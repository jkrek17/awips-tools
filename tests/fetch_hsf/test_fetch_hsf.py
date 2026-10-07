#!/usr/bin/env python3
"""Checks for tools/fetch_hsf.py, against a fake archive (no network).

The fake stands in for urllib's urlopen and answers the AFOS bulk endpoint the way
the real one does (zip of PIL_YYYYMMDDHHMM.txt members, oldest first, sdate
inclusive to the minute, edate exclusive, limit honoured, an empty zip for an empty
span), with failures and corruption injectable per request. What is checked is the
behaviour the 24-year run depends on - cursor paging without loss at page and
month boundaries, retry/backoff, truncated-page detection, never re-fetching,
resuming a stopped run, topping up the current month, and the exact cache record
shape - not the archive itself.

    python3 tests/fetch_hsf/test_fetch_hsf.py
"""
import datetime as dt
import gzip
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import urllib.error
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
spec = importlib.util.spec_from_file_location("fetch_hsf", os.path.join(ROOT, "tools", "fetch_hsf.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def make_text(pil, ts, bbb="", seq=0, ttaaii="FZNT01"):
    """A product body shaped like the real thing: LDM sequence line, then the WMO
    header (DDHHMM, optional BBB) - the line the fetcher rebuilds the id from."""
    hdr = f"{ttaaii} KWBC {ts[6:8]}{ts[8:12]}" + (f" {bbb}" if bbb else "")
    return f"{seq:03d} \n{hdr}\n{pil}\n\nbody {ts} {bbb} {seq}\n"


class FakeArchive:
    """products: {pil: [(ts 'YYYYMMDDHHMM', bbb, seq)]}; kept sorted by ts (stable)."""

    def __init__(self, products):
        self.products = {p: sorted(v, key=lambda x: x[0]) for p, v in products.items()}
        self.urls = []
        self.script = []           # one entry consumed per request: None | Exception | callable(bytes)->bytes

    @staticmethod
    def zip_of(pil, rows):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for ts, bbb, seq in rows:
                z.writestr(f"{pil}_{ts}.txt", make_text(pil, ts, bbb, seq))
        return buf.getvalue()

    def urlopen(self, req, context=None, timeout=None):
        url = req.full_url
        self.urls.append(url)
        step = self.script.pop(0) if self.script else None
        if isinstance(step, Exception):
            raise step
        q = dict(re.findall(r"[?&](\w+)=([^&]*)", url))
        pil, limit = q["pil"], int(q["limit"])
        assert q["order"] == "asc" and q["fmt"] == "zip", url
        s = re.sub(r"[-T:Z]", "", q["sdate"]).ljust(12, "0")[:12]
        e = re.sub(r"[-T:Z]", "", q["edate"]).ljust(12, "0")[:12]
        rows = [r for r in self.products.get(pil, []) if s <= r[0] < e][:limit]
        body = self.zip_of(pil, rows)
        if callable(step):
            body = step(body)
        return FakeResp(body)


def reset():
    return urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))


def synoptic(days_from, ndays, pil="HSFAT1"):
    """4 products a day at 04:20/10:25/16:18/22:30 for ndays from 'YYYY-MM-DD'."""
    d0 = dt.date.fromisoformat(days_from)
    out = []
    for i in range(ndays):
        d = (d0 + dt.timedelta(days=i)).strftime("%Y%m%d")
        out += [(d + hm, "", 0) for hm in ("0420", "1025", "1618", "2230")]
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sleeps = []
        self._sleep, tool.time.sleep = tool.time.sleep, self.sleeps.append
        self._stderr, sys.stderr = sys.stderr, io.StringIO()      # the retry chatter is expected here
        self._stdout, sys.stdout = sys.stdout, io.StringIO()
        self.arch = FakeArchive({"HSFAT1": synoptic("2006-11-01", 61)})   # Nov + Dec 2006: 244 products
        self._urlopen, tool.urllib.request.urlopen = tool.urllib.request.urlopen, self.arch.urlopen
        self.today = dt.date(2007, 3, 1)

    def tearDown(self):
        sys.stderr, sys.stdout = self._stderr, self._stdout
        tool.time.sleep = self._sleep
        tool.urllib.request.urlopen = self._urlopen
        shutil.rmtree(self.tmp)

    def run_pil(self, start="2006-11", end="2006-12", pil="HSFAT1", cap=None, today=None, rescan=False):
        f = tool.Fetcher(0, cap)
        stats = tool.RunStats()
        try:
            tool.fetch_pil(f, self.tmp, pil, list(tool.month_range(start, end)), today or self.today, rescan, stats)
        except tool.CapReached:
            pass
        return f, stats

    def records(self, ym, pil="HSFAT1"):
        with gzip.open(tool.month_path(self.tmp, pil, ym), "rt", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh]

    def files(self, pil="HSFAT1"):
        d = os.path.join(self.tmp, pil)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []


class Retry(Base):
    def test_transient_resets_are_retried_with_2_4_8_backoff(self):
        self.arch.script = [reset(), ConnectionResetError(104, "reset"), reset()]
        f = tool.Fetcher(0, None)
        self.assertTrue(f.get("https://x/?pil=HSFAT1&sdate=2006-11-01T00:00Z&edate=2006-12-01&limit=100&order=asc&fmt=zip"))
        self.assertEqual(self.sleeps, [2, 4, 8])
        self.assertEqual((f.retries, f.failed), (3, 0))

    def test_every_network_error_class_is_transient(self):
        import http.client, socket
        url = "https://x/?pil=HSFAT1&sdate=2006-11-01T00:00Z&edate=2006-12-01&limit=100&order=asc&fmt=zip"
        for exc in (http.client.RemoteDisconnected("x"), http.client.IncompleteRead(b"a"),
                    socket.timeout("t"), TimeoutError("t"), ConnectionResetError(104, "r")):
            self.arch.script = [exc]
            self.assertTrue(tool.Fetcher(0, None).get(url))

    def test_gives_up_after_2_4_8_16_and_is_not_fatal(self):
        url = "https://x/?pil=HSFAT1&sdate=2006-11-01T00:00Z&edate=2006-12-01&limit=100&order=asc&fmt=zip"
        self.arch.script = [reset() for _ in range(5)]
        f = tool.Fetcher(0, None)
        with self.assertRaises(tool.FetchError):
            f.get(url)
        self.assertEqual(self.sleeps, [2, 4, 8, 16])
        self.assertEqual(f.attempts, 5)
        self.assertTrue(f.get(url))                                # the next request just works

    def test_4xx_refusal_is_not_repeated_but_429_is(self):
        url = "https://x/?pil=HSFAT1&sdate=2006-11-01T00:00Z&edate=2006-12-01&limit=100&order=asc&fmt=zip"
        self.arch.script = [urllib.error.HTTPError("u", 422, "Unprocessable", {}, None)]
        f = tool.Fetcher(0, None)
        with self.assertRaises(tool.FetchError):
            f.get(url)
        self.assertEqual((f.attempts, self.sleeps), (1, []))
        self.arch.script = [urllib.error.HTTPError("u", 429, "Too Many", {}, None)]
        self.assertTrue(f.get(url))
        self.assertEqual(self.sleeps, [2])

    def test_run_aborts_only_when_the_network_is_plainly_down(self):
        url = "https://x/?pil=HSFAT1&sdate=2006-11-01T00:00Z&edate=2006-12-01&limit=100&order=asc&fmt=zip"
        self.arch.script = [reset() for _ in range(5 * tool.FETCH_ABORT_AFTER)]
        f = tool.Fetcher(0, None)
        with self.assertRaises(tool.RunAborted):
            for _ in range(tool.FETCH_ABORT_AFTER + 2):
                try:
                    f.get(url)
                except tool.FetchError:
                    pass


class PageIntegrity(Base):
    """A 200 that is not a whole page is a failure, never data."""

    def parse(self, body):
        return tool.parse_page(body, "HSFAT1")

    def good(self, n=5):
        return FakeArchive.zip_of("HSFAT1", synoptic("2006-11-01", 2)[:n])

    def test_truncated_zip_is_rejected_at_every_cut(self):
        body = self.good()
        for cut in (len(body) - 1, len(body) - 30, len(body) // 2, 10):
            with self.assertRaises(tool.BadBody, msg=f"cut at {cut}"):
                self.parse(body[:cut])

    def test_bit_rot_in_a_member_fails_the_crc(self):
        body = bytearray(self.good())
        body[60] ^= 0xFF
        with self.assertRaises(tool.BadBody):
            self.parse(bytes(body))

    def test_garbage_and_html_error_pages_are_rejected(self):
        for junk in (b"", b"<html>502 Bad Gateway</html>", b"ERROR: something else", b"ERROR: Could not Find: HSFAT1 and more " * 20):
            with self.assertRaises(tool.BadBody):
                self.parse(junk)

    def test_the_two_legitimate_empties(self):
        self.assertEqual(self.parse(FakeArchive.zip_of("HSFAT1", [])), [])
        self.assertEqual(self.parse(b"ERROR: Could not Find: HSFAT1"), [])

    def test_wrong_pil_member_and_over_limit_are_rejected(self):
        with self.assertRaises(tool.BadBody):
            tool.parse_page(FakeArchive.zip_of("HSFEP1", [("200611010420", "", 0)]), "HSFAT1")
        with self.assertRaises(tool.BadBody):
            self.parse(FakeArchive.zip_of("HSFAT1", synoptic("2006-11-01", 30)[:101]))

    def test_truncated_page_is_retried_then_succeeds(self):
        self.arch.script = [lambda b: b[:len(b) // 2]]
        f, stats = self.run_pil("2006-11", "2006-11")
        self.assertEqual((f.retries, stats.span_failed), (1, []))
        self.assertEqual(len(self.records("2006-11")), 120)

    def test_persistently_truncated_page_stops_that_span_not_the_run(self):
        self.arch.script = [lambda b: b[:len(b) // 2]] * 5
        f, stats = self.run_pil("2006-11", "2006-11")
        self.assertEqual(len(stats.span_failed), 1)
        self.assertEqual(stats.fetched, 0)
        self.assertEqual(self.files(), [])                       # nothing half-trusted reached disk
        f, stats = self.run_pil("2006-11", "2006-11")             # the next run just works
        self.assertEqual(len(self.records("2006-11")), 120)


class Paging(Base):
    def test_record_shape_ids_and_order(self):
        self.arch.products["HSFAT1"].append(("200611101005", "RRA", 0))
        self.arch.products["HSFAT1"].sort(key=lambda x: x[0])
        self.run_pil("2006-11", "2006-11")
        recs = self.records("2006-11")
        for r in recs:
            self.assertEqual(list(r), ["product_id", "issued", "text"])
        self.assertEqual(recs[0]["product_id"], "200611010420-KWBC-FZNT01-HSFAT1")
        self.assertEqual(recs[0]["issued"], "2006-11-01T04:20:00Z")
        self.assertEqual(recs[0]["text"], make_text("HSFAT1", "200611010420"))
        self.assertIn("200611101005-KWBC-FZNT01-HSFAT1-RRA", [r["product_id"] for r in recs])
        self.assertEqual([r["issued"] for r in recs], sorted(r["issued"] for r in recs))

    def test_no_loss_or_duplication_across_pages_and_months(self):
        f, stats = self.run_pil()
        self.assertEqual(len(self.records("2006-11")) + len(self.records("2006-12")), 244)
        self.assertTrue(all(r["issued"].startswith("2006-11") for r in self.records("2006-11")))
        self.assertTrue(all(r["issued"].startswith("2006-12") for r in self.records("2006-12")))
        self.assertEqual(f.requests, 3)                           # 100 + 100 + 44
        ids = [r["product_id"] for ym in ("2006-11", "2006-12") for r in self.records(ym)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_products_sharing_the_minute_that_straddles_a_page_edge_are_not_lost(self):
        # product #100 and #101 filed in the same minute: the cursor lands on that minute
        # and sdate is inclusive, so the second one arrives on the next page.
        rows = synoptic("2006-11-01", 30)
        edge = rows[99][0]
        rows.insert(100, (edge, "", 7))
        self.arch.products["HSFAT1"] = sorted(rows, key=lambda x: x[0])
        self.run_pil("2006-11", "2006-11")
        recs = self.records("2006-11")
        self.assertEqual(len(recs), 121)
        self.assertEqual(sum(r["issued"].replace("-", "").replace("T", "").replace(":", "")[:12] == edge for r in recs), 2)

    def test_same_id_different_text_are_both_kept_identical_repeats_are_not(self):
        self.arch.products["HSFAT1"] = [("200611010420", "", 710), ("200611010420", "", 878), ("200611011025", "", 0)]
        self.run_pil("2006-11", "2006-11")
        recs = self.records("2006-11")
        self.assertEqual([r["product_id"] for r in recs][:2], ["200611010420-KWBC-FZNT01-HSFAT1"] * 2)
        self.assertEqual(len({r["text"] for r in recs}), 3)
        self.run_pil("2006-11", "2006-11", rescan=True)           # re-receiving them adds nothing
        self.assertEqual(len(self.records("2006-11")), 3)

    def test_product_without_a_wmo_header_is_cached_under_a_placeholder(self):
        pg = FakeArchive.zip_of("HSFAT1", [("200611010420", "", 0)])
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("HSFAT1_200611010420.txt", "no header here\n")
        (pid, issued, text, ok), = tool.parse_page(z.getvalue(), "HSFAT1")
        self.assertFalse(ok)
        self.assertEqual(pid, "200611010420-NOHDR-NOHDR-HSFAT1")

    def test_span_end_is_exclusive_and_never_past_tomorrow(self):
        self.assertEqual(tool.span_end("2006-12", dt.date(2007, 3, 1)), dt.date(2007, 1, 1))
        self.assertEqual(tool.span_end("2026-10", dt.date(2026, 10, 7)), dt.date(2026, 10, 8))
        self.assertEqual(tool.span_end("2026-12", dt.date(2026, 12, 31)), dt.date(2027, 1, 1))


class Resume(Base):
    def test_finished_span_costs_one_short_page_and_changes_nothing(self):
        self.run_pil()
        before = {n: open(os.path.join(self.tmp, "HSFAT1", n), "rb").read() for n in self.files()}
        self.arch.urls.clear()
        f, stats = self.run_pil()
        self.assertEqual((f.requests, stats.fetched), (1, 0))
        self.assertEqual({n: open(os.path.join(self.tmp, "HSFAT1", n), "rb").read() for n in self.files()}, before)

    def test_cap_stops_cleanly_marks_the_month_and_resumes_without_refetching(self):
        f, stats = self.run_pil(cap=1)
        self.assertTrue(stats.capped)
        self.assertIn("2006-11.partial", self.files())
        n = len(self.records("2006-11")) + len(self.records("2006-12")) if "2006-12.jsonl.gz" in self.files() else len(self.records("2006-11"))
        self.assertEqual(n, 100)
        f, stats = self.run_pil()
        self.assertEqual(stats.fetched, 144)
        self.assertEqual(len(self.records("2006-11")) + len(self.records("2006-12")), 244)
        self.assertNotIn("2006-11.partial", self.files())

    def test_stopped_month_is_resumed_even_when_a_later_month_already_exists(self):
        self.run_pil("2006-12", "2006-12")                         # December first, on its own
        self.run_pil("2006-11", "2006-12", cap=1)                  # then a wider run that stops in November
        self.assertIn("2006-11.partial", self.files())
        self.run_pil("2006-11", "2006-12")
        self.assertEqual(len(self.records("2006-11")), 120)        # not left short behind a present December
        self.assertEqual(len(self.records("2006-12")), 124)

    def test_short_last_month_is_completed(self):
        self.run_pil()
        full = self.records("2006-12")
        tool.write_month(tool.month_path(self.tmp, "HSFAT1", "2006-12"), full[:60])
        f, stats = self.run_pil()
        self.assertEqual(stats.fetched, 64)
        self.assertEqual(self.records("2006-12"), full)

    def test_hole_in_the_middle_is_found_only_by_rescan(self):
        self.run_pil()
        full = self.records("2006-11")
        tool.write_month(tool.month_path(self.tmp, "HSFAT1", "2006-11"), [])
        f, stats = self.run_pil()
        self.assertEqual(stats.fetched, 0)
        f, stats = self.run_pil(rescan=True)
        self.assertEqual(self.records("2006-11"), full)

    def test_current_month_tops_up(self):
        today = dt.date(2006, 12, 20)
        self.run_pil(today=today)
        self.assertEqual(len(self.records("2006-12")), 4 * 20)
        self.arch.products["HSFAT1"].append(("200612202300", "", 0))
        self.arch.products["HSFAT1"].sort(key=lambda x: x[0])
        self.arch.urls.clear()
        f, stats = self.run_pil(today=today)
        self.assertEqual((f.requests, stats.fetched), (1, 1))
        self.assertTrue(self.arch.urls[0].endswith("edate=2006-12-21&limit=100&order=asc&fmt=zip"))
        self.assertEqual(len(self.records("2006-12")), 4 * 20 + 1)

    def test_empty_months_get_empty_files_only_when_the_span_finished(self):
        self.arch.products["HSFAT1"] = synoptic("2006-12-05", 3)
        self.run_pil("2006-11", "2006-12")
        self.assertEqual(self.records("2006-11"), [])
        self.assertEqual(len(self.records("2006-12")), 12)
        shutil.rmtree(os.path.join(self.tmp, "HSFAT1"))
        self.arch.script = [reset() for _ in range(5)]            # span fails: nothing was looked at
        self.run_pil("2006-11", "2006-12")
        self.assertEqual(self.files(), [])

    def test_failed_span_does_not_block_the_next_pil(self):
        self.arch.products["HSFEP1"] = synoptic("2006-11-01", 3)
        self.arch.script = [reset() for _ in range(5)]             # first PIL's first page dies for good
        f = tool.Fetcher(0, None)
        stats = tool.RunStats()
        months = ["2006-11"]
        for pil in ("HSFAT1", "HSFEP1"):
            tool.fetch_pil(f, self.tmp, pil, months, self.today, False, stats)
        self.assertEqual([p for p, _ in stats.span_failed], ["HSFAT1"])
        self.assertEqual(len(self.records("2006-11", "HSFEP1")), 12)


class Cli(Base):
    def test_pils(self):
        self.assertEqual(tool.parse_pils("hsfat1,HSFEPI"), ["HSFAT1", "HSFEPI"])
        for bad in ("HSFAT2", "HSFNP"):
            with self.assertRaises(Exception):
                tool.parse_pils(bad)

    def test_dry_run_makes_no_request_and_writes_nothing(self):
        argv, sys.argv = sys.argv, ["fetch_hsf.py", "--dry-run", "--cache-dir", self.tmp, "--start", "2006-11", "--end", "2006-12"]
        try:
            self.assertEqual(tool.main(), 0)
        finally:
            sys.argv = argv
        self.assertEqual(self.arch.urls, [])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_exit_codes(self):
        def run(*extra):
            argv, sys.argv = sys.argv, ["fetch_hsf.py", "--pil", "HSFAT1", "--delay", "0", "--cache-dir", self.tmp,
                                         "--start", "2006-11", "--end", "2006-11", *extra]
            try:
                return tool.main()
            finally:
                sys.argv = argv
        self.assertEqual(run(), 0)
        self.assertEqual(run("--max-requests", "0"), 0)
        shutil.rmtree(self.tmp); os.makedirs(self.tmp)
        self.arch.script = [reset() for _ in range(5)]
        self.assertEqual(run(), 1)


if __name__ == "__main__":
    unittest.main()
