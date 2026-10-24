"""Build a compact ratings model from Kaggle's MovieLens-style ratings.csv.

Two streaming passes keep memory bounded even for a large ratings file.
The item pairs are intentionally limited to common movies for practical builds.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path


DATA = Path(__file__).parent / "data"
RATINGS = DATA / "ratings.csv"
OUTPUT = DATA / "model.json"
TOP_MOVIES = 1500
MAX_LIKES_PER_USER = 20
MAX_NEIGHBORS = 35
SIMILARITY_SHRINKAGE = 10


def rows():
    with RATINGS.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"userId", "movieId", "rating", "timestamp"}.issubset(reader.fieldnames or []):
            raise ValueError("ratings.csv needs userId,movieId,rating,timestamp columns")
        for row in reader:
            try:
                yield int(row["userId"]), int(row["movieId"]), float(row["rating"]), int(row["timestamp"])
            except (TypeError, ValueError):
                continue


def build():
    if not RATINGS.exists():
        raise SystemExit("Place ratings.csv in data/ first. See README.md.")
    print("Pass 1/2: counting ratings...")
    count, total = Counter(), defaultdict(float)
    for _, movie, rating, _ in rows():
        count[movie] += 1
        total[movie] += rating
    popular = set(movie for movie, _ in count.most_common(TOP_MOVIES))
    print(f"Pass 2/2: building neighbors among {len(popular)} commonly rated films...")
    pairs = Counter()
    eligible_likes = Counter()
    current_user, user_likes, previous_user = None, [], None

    def flush():
        # Use recent unique likes and a matching denominator for pair cosine.
        latest = {}
        for movie, timestamp in user_likes:
            latest[movie] = max(timestamp, latest.get(movie, timestamp))
        sample = sorted(movie for movie, _ in sorted(latest.items(), key=lambda item: (-item[1], item[0]))[:MAX_LIKES_PER_USER])
        eligible_likes.update(sample)
        pairs.update(combinations(sorted(sample), 2))

    for user, movie, rating, timestamp in rows():
        if previous_user is not None and user < previous_user:
            raise ValueError("ratings.csv must be sorted by userId for streaming pair counts")
        previous_user = user
        if current_user is None:
            current_user = user
        if user != current_user:
            flush()
            user_likes = []
            current_user = user
        if rating >= 4.0 and movie in popular:
            user_likes.append((movie, timestamp))
    if current_user is not None:
        flush()

    neighbors = defaultdict(dict)
    for (first, second), together in pairs.items():
        if together < 3:
            continue
        # Cosine on the same capped vectors used for pair counts, with support shrinkage.
        cosine = together / math.sqrt(eligible_likes[first] * eligible_likes[second])
        similarity = cosine * together / (together + SIMILARITY_SHRINKAGE)
        neighbors[first][second] = round(similarity, 4)
        neighbors[second][first] = round(similarity, 4)
    limited = {str(movie): dict(sorted(values.items(), key=lambda item: -item[1])[:MAX_NEIGHBORS]) for movie, values in neighbors.items()}
    model = {
        "schemaVersion": 2,
        "popularity": {str(movie): {"count": amount, "mean": round(total[movie] / amount, 3)} for movie, amount in count.items()},
        "neighbors": limited,
        "method": "support-shrunk item-item cosine on ratings >= 4",
        "parameters": {
            "topMovies": TOP_MOVIES,
            "maxRecentLikesPerUser": MAX_LIKES_PER_USER,
            "maxNeighbors": MAX_NEIGHBORS,
            "minimumCoLikes": 3,
            "similarityShrinkage": SIMILARITY_SHRINKAGE,
        },
    }
    OUTPUT.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {OUTPUT} ({len(limited)} movies with collaborative neighbors)")


if __name__ == "__main__":
    build()
