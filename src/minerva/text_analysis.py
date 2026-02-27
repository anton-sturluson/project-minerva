"""Text analysis: keyword counting, sentiment scoring, risk classification."""

import re
from dataclasses import dataclass


@dataclass
class KeywordGroup:
    """Named group of keywords for text analysis."""

    name: str
    keywords: list[str]


@dataclass
class SentimentResult:
    """Sentiment scoring output."""

    confidence_count: int
    uncertainty_count: int
    net_score: float
    paragraph_count: int


DEFAULT_CONFIDENCE_WORDS: frozenset[str] = frozenset({
    "opportunity", "opportunities", "growth", "strong", "strengthen",
    "accelerate", "accelerating", "momentum", "innovation", "innovative",
    "leader", "leading", "advantage", "advantageous", "transformative",
    "transform", "enable", "enables", "enabling", "enhance", "enhanced",
    "improve", "improved", "improving", "optimistic", "confident",
    "excited", "exciting", "promising", "robust", "powerful",
    "breakthrough", "superior", "best-in-class", "state-of-the-art",
    "scalable", "scale", "scaling", "differentiated", "competitive",
    "demand", "invest", "investing", "investment",
})

DEFAULT_UNCERTAINTY_WORDS: frozenset[str] = frozenset({
    "risk", "risks", "uncertain", "uncertainty", "uncertainties",
    "challenge", "challenges", "challenging", "threat", "threats",
    "decline", "declining", "adverse", "adversely", "negative",
    "negatively", "difficult", "difficulty", "volatile", "volatility",
    "impair", "impairment", "litigation", "regulatory", "regulation",
    "compliance", "restrict", "restriction", "limitation", "limitations",
    "concern", "concerns", "cautious", "caution", "doubt", "doubtful",
    "failure", "fail", "fails", "unable", "inability", "obstacle",
    "disruption", "disruptions", "downside", "deteriorate", "deterioration",
    "unfavorable", "unpredictable", "unproven",
})

DEFAULT_FINANCIAL_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "our", "that", "this", "with", "from", "have",
    "has", "was", "were", "been", "will", "may", "can", "not", "which", "their",
    "they", "other", "also", "such", "more", "than", "each", "would", "could",
    "these", "those", "its", "any", "all", "about", "into", "some", "through",
    "over", "during", "under", "between", "after", "before", "including",
    "certain", "related", "upon", "within", "table", "contents", "item",
    "part", "page", "form", "annual", "report", "filed", "commission",
    "securities", "exchange", "registrant", "fiscal", "year", "ended",
    "december", "june", "september", "january", "february", "march", "april",
    "july", "august", "october", "november", "quarter", "quarterly",
    "financial", "statements", "consolidated", "notes", "company",
    "following", "period", "total", "amounts", "million", "billion",
    "percent", "increase", "decrease", "compared", "prior", "respectively",
    "results", "operations", "management", "discussion", "analysis",
    "operating", "income", "loss", "revenue", "cost", "expense", "net",
    "cash", "assets", "liabilities", "equity", "shares", "stock", "common",
    "per", "share", "diluted", "basic", "weighted", "average", "outstanding",
    "provision", "taxes", "tax", "rate", "effective", "deferred",
    "approximately", "primarily", "generally", "significant", "substantially",
})


def count_keyword_group(text: str, keywords: list[str]) -> int:
    """Count total occurrences of keywords in text (case-insensitive)."""
    text_lower: str = text.lower()
    total: int = 0
    for kw in keywords:
        total += len(re.findall(re.escape(kw), text_lower))
    return total


def count_keyword_groups(
    text: str, groups: list[KeywordGroup]
) -> dict[str, int]:
    """Count keyword occurrences for multiple groups."""
    return {g.name: count_keyword_group(text, g.keywords) for g in groups}


def compute_keyword_density(
    text: str, groups: list[KeywordGroup], per_n_words: int = 10_000
) -> dict[str, float]:
    """Compute keyword density (mentions per N words) for each group."""
    word_count: int = max(len(text.split()), 1)
    counts: dict[str, int] = count_keyword_groups(text, groups)
    return {
        name: (count / word_count) * per_n_words
        for name, count in counts.items()
    }


def split_into_chunks(
    text: str, chunk_size: int = 500, overlap_ratio: float = 0.5
) -> list[str]:
    """Split text into overlapping word-level chunks."""
    words: list[str] = text.split()
    chunks: list[str] = []
    step: int = max(1, int(chunk_size * (1 - overlap_ratio)))
    for i in range(0, len(words), step):
        chunk: str = " ".join(words[i : i + chunk_size])
        if len(chunk.split()) > 20:
            chunks.append(chunk)
    return chunks


def extract_topic_paragraphs(
    text: str, triggers: list[str], chunk_size: int = 300
) -> list[str]:
    """Extract text chunks that mention any trigger term."""
    chunks: list[str] = split_into_chunks(text, chunk_size=chunk_size, overlap_ratio=0.5)
    matched: list[str] = []
    for chunk in chunks:
        chunk_lower: str = chunk.lower()
        if any(trigger in chunk_lower for trigger in triggers):
            matched.append(chunk)
    return matched


def score_sentiment(
    paragraphs: list[str],
    confidence_words: frozenset[str] | None = None,
    uncertainty_words: frozenset[str] | None = None,
) -> SentimentResult:
    """Score confidence vs uncertainty across paragraphs."""
    if confidence_words is None:
        confidence_words = DEFAULT_CONFIDENCE_WORDS
    if uncertainty_words is None:
        uncertainty_words = DEFAULT_UNCERTAINTY_WORDS

    confidence_count: int = 0
    uncertainty_count: int = 0
    for para in paragraphs:
        words: list[str] = re.findall(r"\b\w+\b", para.lower())
        confidence_count += sum(1 for w in words if w in confidence_words)
        uncertainty_count += sum(1 for w in words if w in uncertainty_words)

    total: int = max(confidence_count + uncertainty_count, 1)
    net_score: float = (confidence_count - uncertainty_count) / total

    return SentimentResult(
        confidence_count=confidence_count,
        uncertainty_count=uncertainty_count,
        net_score=net_score,
        paragraph_count=len(paragraphs),
    )


def classify_risk_themes(
    text: str,
    themes: dict[str, list[str]],
    triggers: list[str],
) -> dict[str, int]:
    """Count topic paragraphs matching each risk theme."""
    paragraphs: list[str] = extract_topic_paragraphs(text, triggers)
    theme_counts: dict[str, int] = {theme: 0 for theme in themes}

    for para in paragraphs:
        para_lower: str = para.lower()
        for theme, keywords in themes.items():
            if any(kw in para_lower for kw in keywords):
                theme_counts[theme] += 1

    return theme_counts


def normalize_0_1(values: list[float]) -> list[float]:
    """Min-max normalize values to [0, 1]."""
    mn: float = min(values)
    mx: float = max(values)
    rng: float = mx - mn if mx != mn else 1.0
    return [(v - mn) / rng for v in values]
