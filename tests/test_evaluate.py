import unittest

from evaluate import Rating, metrics, temporal_split


class EvaluationTests(unittest.TestCase):
    def test_temporal_split_uses_latest_positive_targets(self):
        ratings = [
            Rating(1, 4.0, 10),
            Rating(2, 5.0, 20),
            Rating(3, 2.0, 30),
            Rating(4, 4.5, 40),
            Rating(5, 4.0, 50),
        ]
        training, user = temporal_split(7, ratings, seed_count=2)
        self.assertEqual(user.validation, 4)
        self.assertEqual(user.test, 5)
        self.assertEqual(user.seeds, (2, 1))
        self.assertEqual({rating.movie_id for rating in training}, {1, 2, 3})

    def test_metrics_are_exact_for_single_target_protocol(self):
        result = metrics([[8, 2, 9], [3, 4, 5]], [2, 7], catalog_size=10, limit=3)
        self.assertEqual(result["recall@3"], 0.5)
        self.assertEqual(result["ndcg@3"], 0.3155)
        self.assertEqual(result["mrr@3"], 0.25)
        self.assertEqual(result["catalog_coverage@3"], 0.6)


if __name__ == "__main__":
    unittest.main()
