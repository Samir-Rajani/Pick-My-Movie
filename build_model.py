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


def rows():
    with RATINGS.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"userId", "movieId", "rating"}.issubset(reader.fieldnames or []):
            raise ValueError("ratings.csv needs userId,movieId,rating columns")
        for row in reader:
            try:
                yield int(row["userId"]), int(row["movieId"]), float(row["rating"])
            except (TypeError, ValueError):
                continue


def build():
    if not RATINGS.exists():
        raise SystemExit("Place ratings.csv in data/ first. See README.md.")
    print("Pass 1/2: counting ratings...")
    count, total, likes = Counter(), defaultdict(float), Counter()
    for _, movie, rating in rows():
        count[movie] += 1
        total[movie] += rating
        if rating >= 4.0:
            likes[movie] += 1
    popular = set(movie for movie, _ in count.most_common(TOP_MOVIES))
    print(f"Pass 2/2: building neighbors among {len(popular)} commonly rated films...")
    pairs = Counter()
    current_user, user_likes, previous_user = None, [], None

    def flush():
        # Prefer well-observed movies; cap each user's contribution to avoid quadratic growth.
        sample = sorted(set(user_likes), key=lambda movie: (-likes[movie], movie))[:MAX_LIKES_PER_USER]
        pairs.update(combinations(sorted(sample), 2))

    for user, movie, rating in rows():
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
            user_likes.append(movie)
    if current_user is not None:
        flush()

    neighbors = defaultdict(dict)
    for (first, second), together in pairs.items():
        if together < 3:
            continue
        # Cosine similarity of binary liked-movie vectors.
        similarity = together / math.sqrt(likes[first] * likes[second])
        neighbors[first][second] = round(similarity, 4)
        neighbors[second][first] = round(similarity, 4)
    limited = {str(movie): dict(sorted(values.items(), key=lambda item: -item[1])[:MAX_NEIGHBORS]) for movie, values in neighbors.items()}
    model = {"popularity": {str(movie): {"count": amount, "mean": round(total[movie] / amount, 3)} for movie, amount in count.items()}, "neighbors": limited,
             "method": "item-item cosine on ratings >= 4; top 1500 rated movies; max 20 likes per user"}
    OUTPUT.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(f"Saved {OUTPUT} ({len(limited)} movies with collaborative neighbors)")


if __name__ == "__main__":
    build()
