import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from app import Handler


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, path):
        with urlopen(self.base_url + path, timeout=3) as response:
            return response.status, json.load(response)

    def test_health_contract(self):
        status, payload = self.get_json("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertGreater(payload["movies"], 60_000)
        self.assertEqual(payload["mode"], "full")
        self.assertIs(payload["collaborative"], True)
        self.assertEqual(payload["modelSchema"], 2)
        with urlopen(self.base_url + "/api/health", timeout=3) as response:
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_search_and_recommendation_contracts(self):
        _, movies = self.get_json("/api/movies?q=heat")
        self.assertLessEqual(len(movies), 12)
        self.assertTrue(any(movie["title"] == "Heat (1995)" for movie in movies))

        _, recommendations = self.get_json("/api/recommendations?liked=296&limit=3")
        self.assertEqual(len(recommendations), 3)
        self.assertNotIn(296, [movie["id"] for movie in recommendations])
        self.assertTrue(all({"id", "title", "score", "reason"} <= movie.keys() for movie in recommendations))

    def test_invalid_parameters_and_missing_routes(self):
        for path in ("/api/recommendations?liked=nope", "/api/recommendations?liked=1&limit=nope"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.base_url + path, timeout=3)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()

        with self.assertRaises(HTTPError) as error:
            urlopen(self.base_url + "/missing", timeout=3)
        self.assertEqual(error.exception.code, 404)
        error.exception.close()

    def test_static_frontend_contract(self):
        with urlopen(self.base_url + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("PickMyMovie", html)
        self.assertIn("/pick-my-movie", html)
        self.assertIn('<div class="shell">', html)
        self.assertNotIn("document.write", html)


if __name__ == "__main__":
    unittest.main()
