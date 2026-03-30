# examples/wikipedia/download.py
"""Download and prepare a Simple Wikipedia dataset for embeddy ingestion.

This module fetches articles from Simple English Wikipedia and saves them
as a JSONL file. Each line is a JSON object with ``title``, ``text``, and
``article_id`` fields.

Usage (standalone)::

    python download.py --output-dir ./data --max-articles 1000

The module provides a patchable ``_fetch_articles()`` function so tests
can inject fake data without network access.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Article:
    """A single Wikipedia article."""

    title: str
    text: str
    article_id: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to a plain dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Article:
        """Deserialize from a dict."""
        return cls(
            title=str(d["title"]),
            text=str(d["text"]),
            article_id=str(d["article_id"]),
        )


# ---------------------------------------------------------------------------
# Fetch (patchable for tests)
# ---------------------------------------------------------------------------


def _fetch_articles() -> list[Article]:
    """Fetch articles from Simple Wikipedia.

    This default implementation attempts to use the ``datasets`` library
    (HuggingFace) to load ``wikipedia`` / ``20220301.simple``.  If the
    library is not installed, it falls back to a small built-in sample.

    Returns:
        List of Article objects.
    """
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]

        logger.info("Loading Simple Wikipedia from HuggingFace datasets...")
        ds = load_dataset("wikipedia", "20220301.simple", split="train")
        articles: list[Article] = []
        for row in ds:
            articles.append(
                Article(
                    title=row["title"],
                    text=row["text"],
                    article_id=str(row["id"]),
                )
            )
        logger.info("Loaded %d articles from HuggingFace.", len(articles))
        return articles
    except ImportError:
        logger.warning(
            "HuggingFace `datasets` not installed. Using built-in sample. Install with: pip install datasets"
        )
        return _builtin_sample()
    except Exception as exc:
        logger.warning("Failed to load from HuggingFace: %s. Using built-in sample.", exc)
        return _builtin_sample()


def _builtin_sample() -> list[Article]:
    """Return a small built-in sample of articles for offline use."""
    return [
        Article(
            title="Python (programming language)",
            text=(
                "Python is a high-level, general-purpose programming language. "
                "Its design philosophy emphasizes code readability with the use of "
                "significant indentation. Python is dynamically typed and garbage-collected. "
                "It supports multiple programming paradigms, including structured, "
                "object-oriented and functional programming. Python was conceived in the "
                "late 1980s by Guido van Rossum at Centrum Wiskunde & Informatica (CWI) in "
                "the Netherlands as a successor to the ABC programming language."
            ),
            article_id="1",
        ),
        Article(
            title="Mathematics",
            text=(
                "Mathematics is an area of knowledge that includes the topics of numbers, "
                "formulas and related structures, shapes and the spaces in which they are "
                "contained, and quantities and their changes. These topics are represented in "
                "modern mathematics with the major subdisciplines of number theory, algebra, "
                "geometry, and analysis, respectively. There is no general consensus among "
                "mathematicians about a common definition for their academic discipline."
            ),
            article_id="2",
        ),
        Article(
            title="Solar System",
            text=(
                "The Solar System is the gravitationally bound system of the Sun and the "
                "objects that orbit it. The largest of such objects are the eight planets. "
                "The four inner system planets are Mercury, Venus, Earth, and Mars. "
                "The four outer planets are giant planets, being substantially more massive "
                "than the inner planets. The two largest, Jupiter and Saturn, are gas giants, "
                "and the two outermost planets, Uranus and Neptune, are ice giants."
            ),
            article_id="3",
        ),
        Article(
            title="Machine learning",
            text=(
                "Machine learning is a subset of artificial intelligence that provides "
                "systems the ability to automatically learn and improve from experience "
                "without being explicitly programmed. Machine learning focuses on the "
                "development of computer programs that can access data and use it to learn "
                "for themselves. The process begins with observations or data, such as "
                "examples, direct experience, or instruction, to look for patterns in data."
            ),
            article_id="4",
        ),
        Article(
            title="DNA",
            text=(
                "Deoxyribonucleic acid is a polymer composed of two polynucleotide chains "
                "that coil around each other to form a double helix. The polymer carries "
                "genetic instructions for the development, functioning, growth and "
                "reproduction of all known organisms and many viruses. DNA and ribonucleic "
                "acid are nucleic acids. Alongside proteins, lipids and complex "
                "carbohydrates, nucleic acids are one of the four major types of "
                "macromolecules that are essential for all known forms of life."
            ),
            article_id="5",
        ),
    ]


# ---------------------------------------------------------------------------
# Save / Load (JSONL format)
# ---------------------------------------------------------------------------


def save_articles(articles: list[Article], path: Path) -> None:
    """Save articles to a JSONL file (one JSON object per line).

    Args:
        articles: List of articles to save.
        path: Output file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for article in articles:
            f.write(json.dumps(article.to_dict(), ensure_ascii=False) + "\n")
    logger.info("Saved %d articles to %s", len(articles), path)


def load_articles(path: Path) -> list[Article]:
    """Load articles from a JSONL file.

    Args:
        path: Path to the JSONL file.

    Returns:
        List of Article objects.
    """
    articles: list[Article] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                articles.append(Article.from_dict(json.loads(line)))
    logger.info("Loaded %d articles from %s", len(articles), path)
    return articles


# ---------------------------------------------------------------------------
# Main download function
# ---------------------------------------------------------------------------


def download_simple_wikipedia(
    output_dir: Path,
    max_articles: int = 1000,
    min_length: int = 100,
) -> list[Article]:
    """Download Simple Wikipedia articles and save to JSONL.

    Args:
        output_dir: Directory to save the output file.
        max_articles: Maximum number of articles to keep.
        min_length: Minimum text length to keep an article.

    Returns:
        List of Article objects that were saved.
    """
    logger.info("Fetching Simple Wikipedia articles...")
    all_articles = _fetch_articles()

    # Filter by minimum text length
    filtered = [a for a in all_articles if len(a.text) >= min_length]
    logger.info(
        "Filtered %d -> %d articles (min_length=%d)",
        len(all_articles),
        len(filtered),
        min_length,
    )

    # Truncate to max_articles
    articles = filtered[:max_articles]
    logger.info("Keeping %d articles (max_articles=%d)", len(articles), max_articles)

    # Save
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_articles(articles, output_dir / "articles.jsonl")

    return articles


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Download Simple Wikipedia articles")
    parser.add_argument("--output-dir", type=Path, default=Path("data"), help="Output directory")
    parser.add_argument("--max-articles", type=int, default=1000, help="Max articles to download")
    parser.add_argument("--min-length", type=int, default=100, help="Min article text length")
    args = parser.parse_args()

    articles = download_simple_wikipedia(
        output_dir=args.output_dir,
        max_articles=args.max_articles,
        min_length=args.min_length,
    )
    print(f"Downloaded {len(articles)} articles to {args.output_dir}/articles.jsonl")
