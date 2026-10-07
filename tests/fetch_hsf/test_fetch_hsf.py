#!/usr/bin/env python3
"""Checks for tools/fetch_hsf.py, against a fake archive (no network).

The fake stands in for urllib's urlopen: a list endpoint that answers per UTC day
and a text endpoint per product id, with failures injectable by URL. What is
checked is the behaviour the 24-year run depends on - retry/backoff, never
re-fetching, completing a short month file, topping up the current month, the
request cap, and the exact cache record shape - not the archive itself.

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
import tempfile
import sys
import unittest
import urllib.error

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


class FakeArchive:
    """products: {pil: {'YYYY-MM-DD': [(HHMM, suffix)]}}. fail: {url_substring: [exc, ...]}
    consumed one per matching request before the real answer is given."""

    def __init__(self, products):
        self.products = products
        self.fail = {}
        self.urls = []

    def pid(self, pil, day, hhmm, suffix=""):
        return f"{day.replace('-', '')}{hhmm}-KWBC-FZNT01-{pil}{suffix}"

    def urlopen(self, req, context=None, timeout=None):
        url = req.full_url
        self.urls.append(url)
        for key, excs in self.fail.items():
            if key in url and excs:
                raise excs.pop(0)
        m = re.search(r"list\.json\?pil=(\w+)&date=([\d-]+)", url)
        if m:
            pil, day = m.groups()
            rows = [{"entered": f"{day}T{hh[:2]}:{hh[2:]}:00Z", "pil": pil,
                     "product_id": self.pid(pil, day, hh, suf)} for hh, suf in self.products.get(pil, {}).get(day, [])]
            return FakeResp(json.dumps({"data": rows}).encode())
        pid = url.rsplit("/", 1)[1]
        return FakeResp(f"TEXT OF {pid}\n".encode())

    def count(self, kind):
        return sum(1 for u in self.urls if kind in u)


def reset():
    return urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._stderr, sys.stderr = sys.stderr, io.StringIO()      # the retry chatter is expected here
        self._stdout, sys.stdout = sys.stdout, io.StringIO()
        self.sleeps = []
        self._sleep, tool.time.sleep = tool.time.sleep, self.sleeps.append
        days = {f"2006-12-{d:02d}": [("0420", ""), ("1008", ""), ("1618", ""), ("2225", "")] for d in (1, 2, 3)}
        days["2006-12-02"].append(("0501", "-RRA"))
        self.arch = FakeArchive({"HSFAT1": days})
        self._urlopen, tool.urllib.request.urlopen = tool.urllib.request.urlopen, self.arch.urlopen
        self.today = dt.date(2007, 3, 1)

    def tearDown(self):
        sys.stderr, sys.stdout = self._stderr, self._stdout
        tool.time.sleep = self._sleep
        tool.urllib.request.urlopen = self._urlopen
        shutil.rmtree(self.tmp)

    def run_month(self, ym="2006-12", pil="HSFAT1", cap=None, today=None, relist=False):
        f = tool.Fetcher(0, cap)
        stats = tool.RunStats()
        try:
            tool.fetch_month(f, self.tmp, pil, ym, today or self.today, relist, stats)
        except tool.CapReached:
            pass
        return f, stats

    def records(self, pil="HSFAT1", ym="2006-12"):
        with gzip.open(tool.month_path(self.tmp, pil, ym), "rt", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh]


class Retry(Base):
    def test_transient_resets_are_retried_with_2_4_8_backoff(self):
        self.arch.fail["/nwstext/"] = [reset(), ConnectionResetError(104, "reset"), reset()]
        f = tool.Fetcher(0, None)
        body = f.get("https://x/api/1/nwstext/abc")
        self.assertTrue(body.startswith(b"TEXT OF"))
        self.assertEqual(self.sleeps, [2, 4, 8])
        self.assertEqual((f.retries, f.failed), (3, 0))

    def test_every_network_error_class_is_transient(self):
        import http.client, socket
        for exc in (http.client.RemoteDisconnected("x"), http.client.IncompleteRead(b"a"),
                    socket.timeout("t"), TimeoutError("t"), ConnectionResetError(104, "r")):
            self.arch.fail["/nwstext/"] = [exc]
            self.assertTrue(tool.Fetcher(0, None).get("https://x/api/1/nwstext/abc"))

    def test_gives_up_after_2_4_8_16_and_is_not_fatal(self):
        self.arch.fail["/nwstext/"] = [reset() for _ in range(5)]
        f = tool.Fetcher(0, None)
        with self.assertRaises(tool.FetchError):
            f.get("https://x/api/1/nwstext/abc")
        self.assertEqual(self.sleeps, [2, 4, 8, 16])
        self.assertEqual(f.attempts, 5)
        self.assertTrue(f.get("https://x/api/1/nwstext/abc"))      # the next request just works

    def test_4xx_refusal_is_not_repeated_but_429_is(self):
        e404 = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        self.arch.fail["/nwstext/"] = [e404]
        f = tool.Fetcher(0, None)
        with self.assertRaises(tool.FetchError):
            f.get("https://x/api/1/nwstext/abc")
        self.assertEqual((f.attempts, self.sleeps), (1, []))
        self.arch.fail["/nwstext/"] = [urllib.error.HTTPError("u", 429, "Too Many", {}, None)]
        self.assertTrue(f.get("https://x/api/1/nwstext/abc"))
        self.assertEqual(self.sleeps, [2])

    def test_run_aborts_only_when_the_network_is_plainly_down(self):
        self.arch.fail["/nwstext/"] = [reset() for _ in range(5 * tool.FETCH_ABORT_AFTER)]
        f = tool.Fetcher(0, None)
        with self.assertRaises(tool.RunAborted):
            for i in range(tool.FETCH_ABORT_AFTER + 2):
                try:
                    f.get("https://x/api/1/nwstext/abc")
                except tool.FetchError:
                    pass


class Cache(Base):
    def test_record_shape_and_order(self):
        self.run_month()
        recs = self.records()
        self.assertEqual(len(recs), 13)
        for r in recs:
            self.assertEqual(list(r), ["product_id", "issued", "text"])
        self.assertEqual(recs[0]["product_id"], "200612010420-KWBC-FZNT01-HSFAT1")
        self.assertEqual(recs[0]["issued"], "2006-12-01T04:20:00Z")
        self.assertEqual(recs[0]["text"], "TEXT OF 200612010420-KWBC-FZNT01-HSFAT1\n")
        self.assertIn("200612020501-KWBC-FZNT01-HSFAT1-RRA", [r["product_id"] for r in recs])  # amendments kept
        self.assertEqual([r["issued"] for r in recs], sorted(r["issued"] for r in recs))

    def test_complete_past_month_costs_zero_requests(self):
        self.run_month()
        n = len(self.arch.urls)
        f, stats = self.run_month()
        self.assertEqual((len(self.arch.urls), f.requests, stats.fetched, stats.skipped_complete), (n, 0, 0, 1))

    def test_short_month_file_is_completed_not_skipped(self):
        self.run_month()
        full = self.records()
        path = tool.month_path(self.tmp, "HSFAT1", "2006-12")
        tool.write_month(path, {r["product_id"]: r for r in full[:9]})
        self.arch.urls.clear()
        f, stats = self.run_month()
        self.assertEqual(stats.fetched, 4)
        self.assertEqual(self.arch.count("list.json"), 0)         # listings were recorded; not repeated
        self.assertEqual(self.arch.count("/nwstext/"), 4)
        self.assertEqual(self.records(), full)

    def test_month_file_with_no_sidecar_is_relisted_not_trusted(self):
        self.run_month()
        os.remove(tool.listing_path(self.tmp, "HSFAT1", "2006-12"))
        self.arch.urls.clear()
        f, stats = self.run_month()
        self.assertEqual((self.arch.count("list.json"), stats.fetched), (31, 0))

    def test_cap_stops_cleanly_and_resumes_without_refetching(self):
        f, stats = self.run_month(cap=40)                          # 31 listings + 9 products
        self.assertTrue(f.requests == 40 and stats.fetched == 9)
        self.assertEqual(len(self.records()), 9)
        self.arch.urls.clear()
        f, stats = self.run_month()
        self.assertEqual((self.arch.count("list.json"), stats.fetched), (0, 4))
        self.assertEqual(len({r["product_id"] for r in self.records()}), 13)

    def test_current_month_relists_today_only_and_tops_up(self):
        today = dt.date(2006, 12, 3)
        self.run_month(today=today)
        self.assertEqual(len(self.records()), 13)                   # days 1-3, incl. one amendment
        self.assertNotIn("2006-12-03", tool.read_listing(tool.listing_path(self.tmp, "HSFAT1", "2006-12")))
        # a new forecast arrives today
        self.arch.products["HSFAT1"]["2006-12-03"].append(("2330", ""))
        self.arch.urls.clear()
        f, stats = self.run_month(today=today)
        self.assertEqual(self.arch.count("list.json"), 1)
        self.assertEqual(stats.fetched, 1)
        self.assertEqual(stats.skipped_complete, 0)

    def test_failed_product_is_a_gap_and_next_run_fetches_only_it(self):
        self.arch.fail["200612020501"] = [reset() for _ in range(5)]
        f, stats = self.run_month()
        self.assertEqual(stats.text_failed, [("HSFAT1", "200612020501-KWBC-FZNT01-HSFAT1-RRA")])
        self.assertEqual(len(self.records()), 12)
        self.arch.urls.clear()
        f, stats = self.run_month()
        self.assertEqual((self.arch.count("list.json"), stats.fetched), (0, 1))
        self.assertEqual(len(self.records()), 13)

    def test_failed_listing_is_reported_and_retried_next_run(self):
        self.arch.fail["date=2006-12-02"] = [reset() for _ in range(5)]
        f, stats = self.run_month()
        self.assertEqual(stats.list_failed, [("HSFAT1", "2006-12-02")])
        self.assertEqual(self.arch.count("list.json"), 31 + 4)     # 30 days + 5 attempts at one
        self.arch.urls.clear()
        f, stats = self.run_month()
        self.assertEqual(self.arch.count("list.json"), 1)

    def test_truncated_month_file_is_read_as_far_as_it_goes(self):
        self.run_month()
        path = tool.month_path(self.tmp, "HSFAT1", "2006-12")
        data = open(path, "rb").read()
        open(path, "wb").write(data[:len(data) // 2])
        f, stats = self.run_month()
        self.assertEqual(len(self.records()), 13)
        self.assertGreater(stats.fetched, 0)

    def test_empty_month_gets_an_empty_file_and_is_then_complete(self):
        f, stats = self.run_month(ym="2006-11")
        self.assertEqual(self.records(ym="2006-11"), [])
        self.arch.urls.clear()
        f, stats = self.run_month(ym="2006-11")
        self.assertEqual((f.requests, stats.skipped_complete), (0, 1))


class Cli(unittest.TestCase):
    def test_pils(self):
        self.assertEqual(tool.parse_pils("hsfat1,HSFEPI"), ["HSFAT1", "HSFEPI"])
        for bad in ("HSFAT2", "HSFNP"):
            with self.assertRaises(Exception):
                tool.parse_pils(bad)

    def test_month_range(self):
        self.assertEqual(list(tool.month_range("2006-11", "2007-02")), ["2006-11", "2006-12", "2007-01", "2007-02"])


if __name__ == "__main__":
    unittest.main()
