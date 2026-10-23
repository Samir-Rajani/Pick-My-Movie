import unittest
from pathlib import Path

from recommender import Recommender


class RecommenderTests(unittest.TestCase):
    def setUp(self):
        self.csv = Path(__file__).parent / 'fixtures' / 'movies.csv'
        self.engine = Recommender(self.csv)

    def test_search_and_exclusion(self):
        self.assertEqual(self.engine.search('beta')[0]['id'], 2)
        results = self.engine.recommend([1])
        self.assertEqual(results[0]['id'], 2)
        self.assertNotIn(1, [movie['id'] for movie in results])
        self.assertNotIn(3, [movie['id'] for movie in results])

    def test_genre_filter_and_invalid_ids(self):
        results = self.engine.recommend([1, 999, 1], genre_filter='Action')
        self.assertEqual({movie['id'] for movie in results}, {2, 4})


if __name__ == '__main__':
    unittest.main()
