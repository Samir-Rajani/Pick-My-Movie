"""Small, explainable hybrid movie recommender with no runtime dependencies."""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


YEAR = re.compile(r"\((\d{4})\)$")


@dataclass(frozen=True)
class Movie:
    id: int
    title: str
    genres: tuple[str, ...]
    year: int | None

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "genres": self.genres, "year": self.year}


class Recommender:
    def __init__(self, movies_path: Path, model_path: Path | None = None):
        self.movies: dict[int, Movie] = {}
        with movies_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"movieId", "title", "genres"}.issubset(reader.fieldnames or []):
                raise ValueError("movies.csv needs movieId,title,genres columns")
            for row in reader:
                try:
                    movie_id = int(row["movieId"])
                except (TypeError, ValueError):
                    continue
                title = (row["title"] or "").strip()
                if not title:
                    continue
                match = YEAR.search(title)
                genres = tuple(g for g in (row["genres"] or "").split("|") if g and g != "(no genres listed)")
                self.movies[movie_id] = Movie(movie_id, title, genres, int(match.group(1)) if match else None)
        if not self.movies:
            raise ValueError("No usable movies found")
        self.genre_frequency = Counter(g for m in self.movies.values() for g in m.genres)
        self.genre_weight = {genre: 1 / math.sqrt(count) for genre, count in self.genre_frequency.items()}
        self.movie_vector_norm = {movie.id: math.sqrt(sum(self.genre_weight[g] ** 2 for g in movie.genres)) or 1 for movie in self.movies.values()}
        self.genre_index: dict[str, set[int]] = {}
        for movie in self.movies.values():
            for genre in movie.genres:
                self.genre_index.setdefault(genre, set()).add(movie.id)
        self.model = {}
        if model_path and model_path.exists():
            self.model = json.loads(model_path.read_text(encoding="utf-8"))
        self.popularity = {int(k): v for k, v in self.model.get("popularity", {}).items()}
        self.neighbors = {int(k): {int(n): float(s) for n, s in v.items()} for k, v in self.model.get("neighbors", {}).items()}

    def search(self, query: str, limit: int = 12) -> list[dict]:
        q = query.strip().casefold()
        if not q:
            return [m.as_dict() for m in list(self.movies.values())[:limit]]
        matches = [m for m in self.movies.values() if q in m.title.casefold()]
        matches.sort(key=lambda m: (not m.title.casefold().startswith(q), len(m.title), m.title))
        return [m.as_dict() for m in matches[:limit]]

    def recommend(self, liked: list[int], limit: int = 12, genre_filter: str = "") -> list[dict]:
        liked = list(dict.fromkeys(i for i in liked if i in self.movies))[:30]
        if not liked:
            return []
        liked_set = set(liked)
        seeds = [self.movies[i] for i in liked]
        weights = Counter()
        for seed in seeds:
            for genre in seed.genres:
                weights[genre] += self.genre_weight[genre]
        magnitude = math.sqrt(sum(value * value for value in weights.values())) or 1
        candidate_ids = set().union(*(self.genre_index.get(g, set()) for g in weights)) if weights else set()
        for seed_id in liked:
            candidate_ids.update(self.neighbors.get(seed_id, {}))
        if genre_filter:
            candidate_ids &= self.genre_index.get(genre_filter, set())
        results = []
        genre_scores: dict[tuple[str, ...], float] = {}
        for movie_id in candidate_ids:
            movie = self.movies[movie_id]
            if movie.id in liked_set or (genre_filter and genre_filter not in movie.genres):
                continue
            if movie.genres not in genre_scores:
                genre_scores[movie.genres] = sum(weights[g] * self.genre_weight[g] for g in movie.genres) / (magnitude * self.movie_vector_norm[movie.id])
            genre_score = genre_scores[movie.genres]
            neighbor_score = max((self.neighbors.get(seed_id, {}).get(movie.id, 0) for seed_id in liked), default=0)
            votes = self.popularity.get(movie.id, {}).get("count", 0)
            rating = self.popularity.get(movie.id, {}).get("mean", 0)
            confidence = min(1.0, math.log1p(votes) / math.log1p(100)) if votes else 0
            quality = max(0.0, (rating - 2.5) / 2.5) * confidence
            score = (0.69 * genre_score + 0.26 * neighbor_score + 0.05 * quality) if self.neighbors else genre_score
            if score <= 0:
                continue
            results.append((score, votes, movie.title, movie.id, neighbor_score))
        if self.popularity:
            well_observed = [item for item in results if item[1] >= 500 and "\ufffd" not in item[2]]
            if len(well_observed) >= limit:
                results = well_observed
        results.sort(key=lambda item: (-item[0], -item[1], item[2]))
        # Diversify the visible shortlist so one liked genre combination does not
        # fill every card with near-identical movies.
        remaining = results[:max(500, limit * 30)]
        selected = []
        genre_sets = {item[3]: set(self.movies[item[3]].genres) for item in remaining}
        while remaining and len(selected) < limit:
            def value(item):
                genres = genre_sets[item[3]]
                overlap = max((len(genres & genre_sets[chosen[3]]) / len(genres | genre_sets[chosen[3]])
                               for chosen in selected if genres | genre_sets[chosen[3]]), default=0)
                return item[0] - 0.14 * overlap

            best = max(remaining, key=value)
            selected.append(best)
            remaining.remove(best)
        output = []
        for score, votes, _, movie_id, neighbor_score in selected:
            movie = self.movies[movie_id]
            shared = sorted((g for g in movie.genres if g in weights), key=lambda g: -weights[g])
            if neighbor_score > 0.3:
                reason = "Liked by viewers with similar taste"
            elif shared:
                reason = "Matches your taste for " + ", ".join(shared[:2])
            else:
                reason = "Related to your liked movies"
            output.append({**movie.as_dict(), "score": round(score, 3), "reason": reason, "rating": round(self.popularity[movie_id]["mean"], 1) if votes else None, "ratingCount": votes})
        return output

    def genres(self) -> list[str]:
        return sorted(self.genre_frequency)
