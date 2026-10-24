"""Offline evaluation for PickMyMovie's recommendation strategies.

The evaluator uses a deterministic temporal split per user: the two latest
positive ratings are validation and test targets, and all earlier activity is
training data. It builds a compact collaborative model from training data only,
tunes the content/collaborative blend on validation, then reports held-out test
metrics. The candidate universe and sampled-user count are recorded with every
result so portfolio claims remain reproducible and properly scoped.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from recommender import Recommender


LIKE_THRESHOLD = 4.0
WEIGHT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


@dataclass(frozen=True)
class Rating:
    movie_id: int
    value: float
    timestamp: int


@dataclass(frozen=True)
class EvaluationUser:
    user_id: int
    seeds: tuple[int, ...]
    validation: int
    test: int


def user_ratings(path: Path, max_users: int | None = None):
    """Yield ratings grouped by user from a user-sorted MovieLens CSV."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"userId", "movieId", "rating", "timestamp"}.issubset(reader.fieldnames or []):
            raise ValueError("ratings.csv needs userId,movieId,rating,timestamp columns")
        current_user = None
        current: list[Rating] = []
        emitted = 0
        previous_user = -1
        for row in reader:
            user_id = int(row["userId"])
            if user_id < previous_user:
                raise ValueError("ratings.csv must be sorted by userId")
            previous_user = user_id
            if current_user is None:
                current_user = user_id
            if user_id != current_user:
                yield current_user, current
                emitted += 1
                if max_users is not None and emitted >= max_users:
                    return
                current_user, current = user_id, []
            current.append(Rating(int(row["movieId"]), float(row["rating"]), int(row["timestamp"])))
        if current_user is not None and (max_users is None or emitted < max_users):
            yield current_user, current


def temporal_split(user_id: int, ratings: list[Rating], seed_count: int = 5):
    positives = sorted((rating for rating in ratings if rating.value >= LIKE_THRESHOLD), key=lambda item: (item.timestamp, item.movie_id))
    if len(positives) < 4:
        return None
    validation, test = positives[-2], positives[-1]
    held_out = {validation.movie_id, test.movie_id}
    training = [rating for rating in ratings if rating.movie_id not in held_out]
    seeds = tuple(dict.fromkeys(rating.movie_id for rating in reversed(positives[:-2])))[:seed_count]
    if len(seeds) < 2:
        return None
    return training, EvaluationUser(user_id, seeds, validation.movie_id, test.movie_id)


def training_statistics(ratings_path: Path, max_users: int | None):
    count: Counter[int] = Counter()
    total: defaultdict[int, float] = defaultdict(float)
    likes: Counter[int] = Counter()
    evaluation_users: list[EvaluationUser] = []
    users_seen = 0
    ratings_seen = 0
    for user_id, ratings in user_ratings(ratings_path, max_users):
        users_seen += 1
        ratings_seen += len(ratings)
        split = temporal_split(user_id, ratings)
        training = split[0] if split else ratings
        if split:
            evaluation_users.append(split[1])
        for rating in training:
            count[rating.movie_id] += 1
            total[rating.movie_id] += rating.value
            if rating.value >= LIKE_THRESHOLD:
                likes[rating.movie_id] += 1
    return count, total, likes, evaluation_users, users_seen, ratings_seen


def collaborative_neighbors(
    ratings_path: Path,
    max_users: int | None,
    popular: set[int],
    max_likes: int,
    max_neighbors: int,
    shrinkage: float,
):
    pairs: Counter[tuple[int, int]] = Counter()
    eligible_likes: Counter[int] = Counter()
    for user_id, ratings in user_ratings(ratings_path, max_users):
        split = temporal_split(user_id, ratings)
        training = split[0] if split else ratings
        selected = []
        seen = set()
        for rating in sorted(training, key=lambda item: (item.timestamp, item.movie_id), reverse=True):
            if rating.value < LIKE_THRESHOLD or rating.movie_id not in popular or rating.movie_id in seen:
                continue
            selected.append(rating.movie_id)
            seen.add(rating.movie_id)
            if len(selected) == max_likes:
                break
        eligible_likes.update(selected)
        pairs.update(combinations(sorted(selected), 2))

    neighbors: defaultdict[int, dict[int, float]] = defaultdict(dict)
    for (first, second), together in pairs.items():
        if together < 3:
            continue
        cosine = together / math.sqrt(eligible_likes[first] * eligible_likes[second])
        similarity = cosine * together / (together + shrinkage)
        neighbors[first][second] = similarity
        neighbors[second][first] = similarity
    return {
        movie: dict(sorted(values.items(), key=lambda item: (-item[1], item[0]))[:max_neighbors])
        for movie, values in neighbors.items()
    }


class Evaluator:
    def __init__(self, engine: Recommender, counts, totals, neighbors, candidate_ids: set[int]):
        self.engine = engine
        self.counts = counts
        self.neighbors = neighbors
        self.candidate_ids = candidate_ids & engine.movies.keys()
        global_count = sum(counts.values()) or 1
        global_mean = sum(totals.values()) / global_count
        prior = 25
        self.quality = {
            movie_id: ((totals[movie_id] + prior * global_mean) / (counts[movie_id] + prior) - 0.5) / 4.5
            for movie_id in self.candidate_ids
        }
        self.popular_ranking = sorted(self.candidate_ids, key=lambda movie_id: (-counts[movie_id], movie_id))
        genres = {genre for movie in engine.movies.values() for genre in movie.genres}
        genre_bit = {genre: 1 << index for index, genre in enumerate(sorted(genres))}
        self.genre_bits = {
            movie_id: sum(genre_bit[genre] for genre in engine.movies[movie_id].genres)
            for movie_id in self.candidate_ids
        }
        self._content_cache = {}
        self._collaborative_cache = {}

    def clear_signal_cache(self):
        self._content_cache.clear()
        self._collaborative_cache.clear()

    def content_scores(self, seeds: tuple[int, ...]):
        if seeds in self._content_cache:
            return self._content_cache[seeds]
        weights = Counter()
        for seed_id in seeds:
            movie = self.engine.movies.get(seed_id)
            if movie:
                for genre in movie.genres:
                    weights[genre] += self.engine.genre_weight[genre]
        magnitude = math.sqrt(sum(value * value for value in weights.values())) or 1
        candidates = set().union(*(self.engine.genre_index.get(genre, set()) for genre in weights)) if weights else set()
        scores = {}
        for movie_id in candidates & self.candidate_ids:
            movie = self.engine.movies[movie_id]
            scores[movie_id] = sum(weights[genre] * self.engine.genre_weight[genre] for genre in movie.genres) / (
                magnitude * self.engine.movie_vector_norm[movie_id]
            )
        self._content_cache[seeds] = scores
        return scores

    def collaborative_scores(self, seeds: tuple[int, ...]):
        if seeds in self._collaborative_cache:
            return self._collaborative_cache[seeds]
        scores: defaultdict[int, float] = defaultdict(float)
        contributing: Counter[int] = Counter()
        for seed_id in seeds:
            for movie_id, similarity in self.neighbors.get(seed_id, {}).items():
                if movie_id in self.candidate_ids:
                    scores[movie_id] += similarity
                    contributing[movie_id] += 1
        for movie_id in scores:
            scores[movie_id] /= math.sqrt(contributing[movie_id])
        maximum = max(scores.values(), default=1)
        normalized = {movie_id: score / maximum for movie_id, score in scores.items()}
        self._collaborative_cache[seeds] = normalized
        return normalized

    def rank(self, seeds: tuple[int, ...], strategy: str, limit: int, content_weight: float = 0.5):
        excluded = set(seeds)
        if strategy == "popularity":
            return [movie_id for movie_id in self.popular_ranking if movie_id not in excluded][:limit]
        content = self.content_scores(seeds) if strategy in {"content", "hybrid"} else {}
        collaborative = self.collaborative_scores(seeds) if strategy in {"collaborative", "hybrid"} else {}
        candidates = (content.keys() | collaborative.keys()) - excluded
        if strategy == "content":
            score = lambda movie_id: content.get(movie_id, 0)
        elif strategy == "collaborative":
            score = lambda movie_id: collaborative.get(movie_id, 0)
        else:
            score = lambda movie_id: (
                0.97 * content_weight * content.get(movie_id, 0)
                + 0.97 * (1 - content_weight) * collaborative.get(movie_id, 0)
                + 0.03 * self.quality.get(movie_id, 0)
            )
        ranked = sorted(candidates, key=lambda movie_id: (-score(movie_id), -self.counts[movie_id], movie_id))
        if strategy != "hybrid":
            return ranked[:limit]
        remaining = [(movie_id, score(movie_id)) for movie_id in ranked[: max(300, limit * 30)]]
        selected = []
        while remaining and len(selected) < limit:
            def diversified_value(item):
                movie_id, base_score = item
                genres = self.genre_bits[movie_id]
                overlap = max(
                    (((genres & self.genre_bits[chosen]).bit_count() / (genres | self.genre_bits[chosen]).bit_count())
                     for chosen in selected if genres | self.genre_bits[chosen]),
                    default=0,
                )
                return base_score - 0.14 * overlap

            best = max(remaining, key=lambda item: (diversified_value(item), self.counts[item[0]], -item[0]))
            selected.append(best[0])
            remaining.remove(best)
        return selected


def metrics(rankings: list[list[int]], targets: list[int], catalog_size: int, limit: int):
    hits = 0
    ndcg = 0.0
    reciprocal_rank = 0.0
    recommended = set()
    for ranking, target in zip(rankings, targets):
        recommended.update(ranking)
        if target in ranking:
            rank = ranking.index(target) + 1
            hits += 1
            ndcg += 1 / math.log2(rank + 1)
            reciprocal_rank += 1 / rank
    users = len(targets) or 1
    return {
        f"recall@{limit}": round(hits / users, 4),
        f"ndcg@{limit}": round(ndcg / users, 4),
        f"mrr@{limit}": round(reciprocal_rank / users, 4),
        f"catalog_coverage@{limit}": round(len(recommended) / (catalog_size or 1), 4),
    }


def evaluate_strategy(evaluator, users, target_field, strategy, limit, weight=0.5):
    started = time.perf_counter()
    rankings = [evaluator.rank(user.seeds, strategy, limit, weight) for user in users]
    targets = [getattr(user, target_field) for user in users]
    result = metrics(rankings, targets, len(evaluator.candidate_ids), limit)
    result["mean_latency_ms"] = round((time.perf_counter() - started) * 1000 / (len(users) or 1), 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratings", type=Path, default=Path("data/ratings.csv"))
    parser.add_argument("--movies", type=Path, default=Path("data/movies.csv"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results.json"))
    parser.add_argument("--max-users", type=int, default=10_000)
    parser.add_argument("--eval-users", type=int, default=1_000)
    parser.add_argument("--candidate-movies", type=int, default=5_000)
    parser.add_argument("--collaborative-movies", type=int, default=1_500)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261024)
    args = parser.parse_args()
    if not args.ratings.exists():
        raise SystemExit(f"Missing {args.ratings}. See README.md for the dataset source.")

    started = time.perf_counter()
    counts, totals, _, eligible, users_seen, ratings_seen = training_statistics(args.ratings, args.max_users)
    candidate_ids = {movie for movie, _ in counts.most_common(args.candidate_movies)}
    collaborative_ids = {movie for movie, _ in counts.most_common(args.collaborative_movies)}
    neighbors = collaborative_neighbors(args.ratings, args.max_users, collaborative_ids, 20, 35, 10.0)
    engine = Recommender(args.movies)
    eligible = [user for user in eligible if user.validation in candidate_ids and user.test in candidate_ids]
    random.Random(args.seed).shuffle(eligible)
    sample = eligible[: args.eval_users]
    if not sample:
        raise SystemExit("No eligible evaluation users. Increase --max-users or candidate coverage.")
    evaluator = Evaluator(engine, counts, totals, neighbors, candidate_ids)

    validation = {}
    for weight in WEIGHT_GRID:
        validation[str(weight)] = evaluate_strategy(evaluator, sample, "validation", "hybrid", args.limit, weight)
        validation[str(weight)].pop("mean_latency_ms")
    ndcg_key = f"ndcg@{args.limit}"
    selected_weight = max(WEIGHT_GRID, key=lambda value: (validation[str(value)][ndcg_key], -abs(value - 0.5)))
    test = {}
    for strategy in ("popularity", "content", "collaborative", "hybrid"):
        evaluator.clear_signal_cache()
        test[strategy] = evaluate_strategy(evaluator, sample, "test", strategy, args.limit, selected_weight)
    result = {
        "schema_version": 1,
        "protocol": {
            "split": "per-user temporal; latest positive=test, second latest=validation, earlier ratings=train",
            "positive_rating_threshold": LIKE_THRESHOLD,
            "seed_movies_per_user": 5,
            "random_seed": args.seed,
            "users_scanned": users_seen,
            "ratings_scanned": ratings_seen,
            "eligible_users": len(eligible),
            "evaluated_users": len(sample),
            "candidate_movies": len(candidate_ids),
            "collaborative_movies": len(collaborative_ids),
            "recommendations_per_user": args.limit,
        },
        "selected_content_weight": selected_weight,
        "validation_hybrid_grid": validation,
        "test": test,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "notes": [
            "Recall@K equals hit rate here because each user has one held-out target.",
            "Metrics apply to the recorded sampled users and candidate universe, not every catalog title or future user.",
            "The model uses only training interactions; validation selects the blend and test reports final results.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
