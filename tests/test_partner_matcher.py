import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.parse import urlsplit, parse_qs

from streamlit.testing.v1 import AppTest

from partner_matcher import (normalize_company, employer_matches, partner_snapshot, search_links,
    export_searches, canonical_posting, classify, leads_from_results, MatcherStore,
    LeadReview, BraveSearch, SearchFailure, search_query, suggested_search_name)
from core import CompanyStore, atomic_text

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://docs.google.com/spreadsheets/d/test/edit?gid=1"


def directory():
    return partner_snapshot([["", "Company"], ["", "Software Co, Inc."], ["", "Software Co Inc"],
        ["", "Aboitiz Equity Ventures, Inc."], ["", "No Email Partner"]],
        source_url=SOURCE, worksheet="Partners", first_data_row=2)


def result(**changes):
    return {"title": "Software Co .NET Developer Intern", "description": "Develop software using C# and ASP.NET.",
            "url": "https://ph.indeed.com/viewjob?jk=abc123def456&utm_source=tracker", **changes}


class PartnerMatchingTests(unittest.TestCase):
    def test_directory_includes_names_without_email_and_deduplicates_only_legal_suffix(self):
        snapshot = directory()
        self.assertEqual(len(snapshot["partners"]), 3)
        self.assertEqual(snapshot["partners"][0]["source_rows"], [2, 3])
        self.assertEqual(snapshot["partners"][2]["name"], "No Email Partner")
        self.assertTrue(employer_matches("Software Co, Inc.", "SOFTWARE CO INC"))
        self.assertFalse(employer_matches("Aboitiz Equity Ventures", "Aboitiz Foods"))
        self.assertFalse(employer_matches("Aboitiz", "Aboitiz Foods"))
        self.assertFalse(employer_matches("ABC Philippines Inc.", "ABC Global Inc."))

    def test_search_links_encode_csharp_and_export_all_companies(self):
        links = search_links("A & B #1", "C#")
        query = parse_qs(urlsplit(links["Indeed search"]).query)
        self.assertEqual(query["q"], ['A & B #1 C#'])
        self.assertEqual(urlsplit(links["JobStreet search"]).fragment, "")
        rows = list(csv.reader(io.StringIO(export_searches(directory()["partners"]).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(rows[0]), 7)
        unsafe = [{"name": "=CMD()", "source_rows": [4]}]
        self.assertTrue(list(csv.reader(io.StringIO(export_searches(unsafe).decode("utf-8-sig"))))[1][0].startswith("'="))

    def test_search_results_and_foreign_hosts_never_become_postings(self):
        for url in ("https://ph.indeed.com/jobs?q=C%23", "https://ph.indeed.com/q-C%23-jobs.html",
                    "https://ph.jobstreet.com/csharp-jobs", "https://ph.jobstreet.com.evil.test/job/123",
                    "http://ph.jobstreet.com/job/123", "https://user:pass@ph.jobstreet.com/job/123"):
            self.assertIsNone(canonical_posting(url))
        self.assertEqual(canonical_posting("https://ph.jobstreet.com/job/123456?tracking=anything"),
                         ("https://ph.jobstreet.com/job/123456", "JobStreet"))
        self.assertEqual(canonical_posting(result()["url"])[0], "https://ph.indeed.com/viewjob?jk=abc123def456")

    def test_legal_directory_name_is_shortened_for_search_only(self):
        original = "BCS Technology PTY. LTD. Philippines - ROHQ *"
        self.assertEqual(suggested_search_name(original), "BCS Technology")
        self.assertEqual(parse_qs(urlsplit(search_links(original)["Indeed search"]).query)["q"], ["BCS Technology C#"])
        self.assertIn('"BCS Technology"', search_query(original, "Philippines"))
        self.assertFalse(employer_matches(original, "BCS Information Technology Corp."))
        self.assertEqual(suggested_search_name("ABC Philippines"), "ABC Philippines")

    def test_custom_search_name_persists_without_changing_partner_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = MatcherStore(Path(temporary) / "matches.json")
            snapshot = directory()
            store.set_directory(snapshot)
            partner = snapshot["partners"][0]
            store.set_search_name(snapshot["revision"], partner["id"], "Software Brand")
            state = store.load()
            self.assertEqual(state["search_names"][partner["id"]], "Software Brand")
            self.assertEqual(state["directory"], snapshot)
            self.assertIn("Software Brand C#", parse_qs(urlsplit(search_links(partner["name"], search_name="Software Brand")["Indeed search"]).query)["q"])
            with self.assertRaises(ValueError):
                store.set_search_name("stale", partner["id"], "Other")

    def test_internship_title_and_language_mentions_are_not_overclaimed(self):
        self.assertIn("Internship/OJT lead", classify("Software Intern", "C#"))
        self.assertIn("Developer hiring lead", classify("Senior Developer", "We have an internship programme; .NET"))
        self.assertIn("C# unconfirmed", classify("VB.NET Developer", "VB.NET"))
        self.assertIn("C# mentioned", classify("C Sharp Developer", ""))
        self.assertIn("No technology evidence", classify("Java Developer", "Internet research"))

    def test_deduplication_html_cleanup_and_unverified_company_match(self):
        partner = directory()["partners"][1]
        results = [result(), result(url="https://ph.indeed.com/viewjob?jk=abc123def456&from=other"),
                   result(url="https://ph.jobstreet.com/jobs?keywords=C%23"),
                   result(url="https://ph.jobstreet.com/job/12345", description="Java only", title="Java Developer")]
        leads = leads_from_results(partner, results)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["verification"], "unreviewed")
        self.assertEqual(leads[0]["employer"], "")
        # Being returned by a company query is not evidence of employer identity.
        self.assertEqual(leads[0]["partner_name"], "Aboitiz Equity Ventures, Inc.")

    def test_provider_failure_is_sanitized_and_does_not_retry(self):
        response = MagicMock(status_code=429)
        response.text = "SECRET-KEY"
        with patch("requests.get", return_value=response) as get:
            with self.assertRaises(SearchFailure) as error:
                BraveSearch("SECRET-KEY").search("company C#")
            self.assertNotIn("SECRET-KEY", str(error.exception))
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_provider_request_is_bounded_and_returns_web_results(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"web": {"results": [result()]}}
        with patch("requests.get", return_value=response) as get:
            found = BraveSearch("test-only-key").search(search_query("Company", "Philippines"))
            self.assertEqual(found, [result()])
            self.assertEqual(get.call_args.kwargs["params"]["count"], 10)
            self.assertEqual(get.call_args.kwargs["timeout"], (5, 15))

    def test_reviews_survive_research_and_directory_versions_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory_path:
            store = MatcherStore(Path(directory_path) / ".local" / "matches.json")
            snapshot = directory()
            store.set_directory(snapshot)
            partner = snapshot["partners"][0]
            lead = leads_from_results(partner, [result()])[0]
            store.record_search(snapshot["revision"], partner["id"], "query", [lead])
            with self.assertRaises(ValueError):
                store.review(lead["id"], LeadReview(employer="Different Company", role_type="Internship/OJT",
                    language="C# confirmed", outcome="reviewed"), lead)
            store.review(lead["id"], LeadReview(employer="Software Co Inc", role_type="Internship/OJT",
                language="C# confirmed", outcome="reviewed"), lead)
            store.record_search(snapshot["revision"], partner["id"], "query", [lead])
            self.assertEqual(store.load()["leads"][lead["id"]]["verification"], "reviewed")
            other = partner_snapshot([["", "Different Company"]], source_url=SOURCE, worksheet="Other", first_data_row=1)
            store.set_directory(other)
            self.assertFalse(store.load()["leads"])
            store.set_directory(snapshot)
            self.assertEqual(store.load()["leads"][lead["id"]]["verification"], "reviewed")
            with self.assertRaises(ValueError):
                store.record_search("stale", partner["id"], "query", [])


class MatcherUITests(unittest.TestCase):
    def test_no_key_still_provides_directory_links_and_no_queue_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = MatcherStore(root / ".local" / "partner-jobs.json")
            store.set_directory(directory())
            code = "from pathlib import Path\nfrom matcher_ui import render_matcher\nrender_matcher(Path(" + repr(str(root)) + "))"
            with patch("matcher_ui.configured_search_key", return_value=""):
                app = AppTest.from_string(code, default_timeout=30).run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.dataframe[0].value), 3)
                button = next(b for b in app.button if b.label.startswith("Discover next"))
                self.assertTrue(button.disabled)

    def test_discovery_review_and_related_company_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = MatcherStore(root / ".local" / "partner-jobs.json")
            snapshot = directory()
            store.set_directory(snapshot)
            code = "from pathlib import Path\nfrom matcher_ui import render_matcher\nrender_matcher(Path(" + repr(str(root)) + "))"
            with patch("matcher_ui.configured_search_key", return_value="test"), \
                 patch("matcher_ui.BraveSearch.search", return_value=[result()]):
                app = AppTest.from_string(code, default_timeout=30).run()
                app.number_input[-1].set_value(1).run()
                next(b for b in app.button if b.label.startswith("Discover next")).click().run()
                self.assertFalse(app.exception)
                self.assertEqual(len(store.load()["leads"]), 1)
                next(t for t in app.text_input if t.label == "Employer name shown on the posting").set_value("Software Co Inc")
                next(c for c in app.checkbox if c.label.startswith("I checked the employer")).check()
                next(b for b in app.button if b.label == "Save posting review").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(next(iter(store.load()["leads"].values()))["verification"], "reviewed")


if __name__ == "__main__":
    unittest.main()
