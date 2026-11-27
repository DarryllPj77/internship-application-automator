import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from partner_matcher import SearchFailure
from search_providers import SearXNGSearch, search_client


class SearchProviderTests(unittest.TestCase):
    def response(self, **payload):
        return Mock(status_code=200, json=Mock(return_value=payload))

    @patch("search_providers.requests.get")
    def test_hybrid_board_uses_only_brave_engine_and_normalizes_excerpt(self, get):
        get.return_value = self.response(results=[{"title": "Intern", "url": "https://example.com/job/1", "content": "C# required"}])
        client = SearXNGSearch("http://127.0.0.1:8080", hybrid=True)
        results = client.search('Acme site:ph.jobstreet.com intern')
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs["params"]["engines"], "braveapi")
        self.assertEqual(results[0]["description"], "C# required")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("search_providers.requests.get")
    def test_general_queries_do_not_spend_brave_credit(self, get):
        get.return_value = self.response(results=[])
        SearXNGSearch("http://localhost:8080", hybrid=True).search("Acme careers intern")
        self.assertEqual(get.call_args.kwargs["params"]["engines"], "duckduckgo")
        SearXNGSearch("http://localhost:8080").search("site:linkedin.com Acme")
        self.assertEqual(get.call_args.kwargs["params"]["engines"], "duckduckgo")

    @patch("search_providers.requests.get")
    def test_no_fallback_on_failure_or_engine_errors(self, get):
        for response in (Mock(status_code=403), self.response(results=[], unresponsive_engines=[["braveapi", "error"]]), self.response(results="bad")):
            get.reset_mock()
            get.return_value = response
            with self.assertRaises(SearchFailure):
                SearXNGSearch("http://localhost:8080", hybrid=True).search("site:indeed.com Acme")
            self.assertEqual(get.call_count, 1)

    def test_configuration_and_invalid_url(self):
        for url in ("file:///tmp", "http://user:secret@localhost", "http://localhost/?key=secret"):
            with self.assertRaises(SearchFailure):
                SearXNGSearch(url)
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            Path(directory, ".env").write_text("SEARXNG_URL=http://localhost:8888\nSEARXNG_ENGINES=duckduckgo\n")
            client = search_client(Path(directory), "Hybrid")
            self.assertEqual(client.url, "http://localhost:8888/search")
            self.assertTrue(client.hybrid)
