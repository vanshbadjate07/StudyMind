"""Trains the interview answer scorer (PRD 6.10) and saves the artefact.

Run from the `backend/` directory:

    python -m ml.train_answer_scorer

Writes `ml/artifacts/answer_scorer.joblib` and `ml/artifacts/metrics.json`.
Both are committed, so a fresh checkout scores answers with the trained model
without anyone having to run this first — this script exists to make the model
reproducible and inspectable, not as an install step.

## Where the labels come from

There is no public corpus of "interview answers about *your* uploaded study
material", so the training set is constructed rather than collected, with the
label coming from how the answer was *built* rather than from a human's
guess after the fact.

A seed corpus of question/ideal-answer/key-concepts items (`SEED_ITEMS`) is
expanded into answers at controlled quality tiers: a full paraphrase of the
ideal answer, the ideal answer with concepts progressively removed, an
on-topic-but-contentless ramble, another item's answer entirely (off-topic),
and non-answers. Because each variant is produced by a known transformation,
its score is known by construction — "this answer retains 2 of 5 key concepts
and 40% of the ideal content" is a fact about how it was generated, not an
opinion.

Realistic variation is injected on purpose — filler words, truncation,
hedging, rambling tails — because a model trained on clean synthetic text
scores confidently on clean text and falls apart on how people actually
speak, which is exactly the input voice mode (6.8) feeds it.

## Honest limitations (state these rather than hiding them)

- The corpus is synthetic. It teaches the model a consistent, explainable
  mapping from the five features to a score; it does not encode a human
  examiner's judgement.
- Held-out metrics therefore measure *generalisation across constructed
  variants*, not agreement with human graders. Collecting real labelled
  answers is the obvious next improvement.
- The split is grouped by seed item, so an item's variants never straddle
  train and test — otherwise the model could memorise an item and the
  reported score would be meaningless.
"""

import json
import random
import statistics
from dataclasses import dataclass
from pathlib import Path

from app.services.answer_scoring import FEATURE_ORDER, extract_features

RANDOM_SEED = 20260817
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "answer_scorer.joblib"
METRICS_PATH = ARTIFACTS_DIR / "metrics.json"

# Share of seed items held out for evaluation. Grouped by item, so this is a
# share of *topics*, not of rows.
TEST_ITEM_FRACTION = 0.25

FILLER_INSERTS = ["um", "like", "basically", "you know", "sort of", "I mean", "kind of", "uh"]

HEDGES = [
    "I think",
    "I'm fairly sure",
    "If I remember right",
    "Not totally certain but",
    "I believe",
]

VAGUE_TAILS = [
    "and so on",
    "and stuff like that",
    "or something along those lines",
    "which is the main thing really",
]


@dataclass(frozen=True)
class SeedItem:
    question: str
    ideal_answer: str
    key_concepts: tuple[str, ...]
    # Sentences of the ideal answer, pre-split so partial answers can be
    # built by keeping a prefix — each sentence is written to carry roughly
    # one key concept, in the same order as key_concepts.
    sentences: tuple[str, ...]


SEED_ITEMS: tuple[SeedItem, ...] = (
    SeedItem(
        question="How does a hash table achieve average constant-time lookup?",
        ideal_answer=(
            "A hash table applies a hash function to the key to compute a bucket index. "
            "Because the index is computed directly rather than searched for, lookup is "
            "average O(1). Collisions, where two keys hash to the same bucket, are resolved "
            "by chaining or open addressing. Performance degrades toward O(n) when the load "
            "factor rises and collisions become common, so the table is resized."
        ),
        key_concepts=("hash function", "bucket index", "collisions", "load factor"),
        sentences=(
            "A hash table applies a hash function to the key to compute a bucket index.",
            "Because the index is computed directly rather than searched for, lookup is average O(1).",
            "Collisions, where two keys hash to the same bucket, are resolved by chaining or open addressing.",
            "Performance degrades toward O(n) when the load factor rises, so the table is resized.",
        ),
    ),
    SeedItem(
        question="What is the difference between process and thread?",
        ideal_answer=(
            "A process is an independent execution unit with its own address space. "
            "Threads live inside a process and share its memory and open file descriptors. "
            "Context switching between threads is cheaper than between processes because "
            "the address space does not change. Sharing memory means threads need "
            "synchronization primitives such as mutexes to avoid race conditions."
        ),
        key_concepts=("address space", "shared memory", "context switching", "synchronization"),
        sentences=(
            "A process is an independent execution unit with its own address space.",
            "Threads live inside a process and share its memory and open file descriptors.",
            "Context switching between threads is cheaper because the address space does not change.",
            "Shared memory means threads need synchronization primitives such as mutexes.",
        ),
    ),
    SeedItem(
        question="Explain how photosynthesis converts light into chemical energy.",
        ideal_answer=(
            "Chlorophyll in the chloroplast absorbs light energy, which drives the light-dependent "
            "reactions in the thylakoid membrane. Those reactions split water, release oxygen, and "
            "produce ATP and NADPH. The Calvin cycle in the stroma then uses that ATP and NADPH to "
            "fix carbon dioxide into glucose. The overall result is light energy stored as chemical "
            "bonds in sugar."
        ),
        key_concepts=("chlorophyll", "light-dependent reactions", "Calvin cycle", "carbon dioxide"),
        sentences=(
            "Chlorophyll in the chloroplast absorbs light energy.",
            "The light-dependent reactions split water, release oxygen, and produce ATP and NADPH.",
            "The Calvin cycle uses that ATP and NADPH to fix carbon dioxide into glucose.",
            "The result is light energy stored as chemical bonds in sugar.",
        ),
    ),
    SeedItem(
        question="What does database normalization achieve?",
        ideal_answer=(
            "Normalization organizes tables so each fact is stored exactly once, removing "
            "redundancy. It eliminates update anomalies where the same value has to be changed "
            "in several places. Third normal form requires that every non-key attribute depend "
            "on the primary key and nothing else. The trade-off is more joins at query time, "
            "which is why reporting schemas are sometimes deliberately denormalized."
        ),
        key_concepts=("redundancy", "update anomalies", "third normal form", "joins"),
        sentences=(
            "Normalization organizes tables so each fact is stored once, removing redundancy.",
            "It eliminates update anomalies where the same value must change in several places.",
            "Third normal form requires every non-key attribute to depend on the primary key.",
            "The trade-off is more joins at query time, so reporting schemas are often denormalized.",
        ),
    ),
    SeedItem(
        question="Why is the TCP three-way handshake necessary?",
        ideal_answer=(
            "The handshake establishes a connection by exchanging SYN, SYN-ACK, and ACK segments. "
            "It lets both sides agree on initial sequence numbers so segments can be ordered and "
            "duplicates detected. It also confirms both directions of the path actually work before "
            "data is sent. Without it, a stale or spoofed packet could open a connection the other "
            "side never agreed to."
        ),
        key_concepts=("SYN-ACK", "sequence numbers", "connection establishment", "duplicates"),
        sentences=(
            "The handshake exchanges SYN, SYN-ACK, and ACK segments to open a connection.",
            "Both sides agree on initial sequence numbers so segments can be ordered.",
            "It confirms connection establishment in both directions before data is sent.",
            "Without it a stale packet could be mistaken for new data, so duplicates are detected.",
        ),
    ),
    SeedItem(
        question="What is overfitting in machine learning and how is it controlled?",
        ideal_answer=(
            "Overfitting is when a model learns noise specific to the training data instead of the "
            "underlying pattern, so training error keeps falling while validation error rises. "
            "It is detected by holding out a validation set and watching the gap between the two. "
            "It is controlled with regularization, more training data, simpler models, and early "
            "stopping. Cross-validation gives a more reliable estimate than a single split."
        ),
        key_concepts=("training data", "validation error", "regularization", "cross-validation"),
        sentences=(
            "Overfitting is learning noise in the training data rather than the underlying pattern.",
            "It shows up as falling training error alongside rising validation error.",
            "It is controlled with regularization, more data, simpler models, and early stopping.",
            "Cross-validation gives a more reliable estimate than a single split.",
        ),
    ),
    SeedItem(
        question="How does an index speed up a SQL query?",
        ideal_answer=(
            "An index is a separate B-tree structure mapping column values to row locations. "
            "The query planner can seek directly to matching rows instead of performing a full "
            "table scan, turning a linear scan into a logarithmic lookup. Indexes cost extra "
            "storage and slow down writes, because every insert and update must maintain them. "
            "An index only helps if the query's predicate matches its leading columns."
        ),
        key_concepts=("B-tree", "full table scan", "query planner", "write cost"),
        sentences=(
            "An index is a separate B-tree mapping column values to row locations.",
            "The query planner seeks directly to matching rows instead of a full table scan.",
            "Indexes cost storage and add write cost, since every insert must maintain them.",
            "An index only helps when the predicate matches its leading columns.",
        ),
    ),
    SeedItem(
        question="What problem does the HTTP stateless design create, and how is it solved?",
        ideal_answer=(
            "HTTP is stateless, so the server keeps no memory of previous requests from the same "
            "client. That makes it impossible to tell two users apart across requests without extra "
            "machinery. Sessions solve it by issuing a token, usually in a cookie, that the client "
            "returns on each request. The server maps that token to server-side session state, or "
            "the token itself carries signed claims as in a JWT."
        ),
        key_concepts=("stateless", "cookie", "session state", "token"),
        sentences=(
            "HTTP is stateless, so the server keeps no memory of previous requests.",
            "Without extra machinery two users cannot be told apart across requests.",
            "A token, usually in a cookie, is returned by the client on each request.",
            "The server maps that token to session state, or the token carries signed claims.",
        ),
    ),
    SeedItem(
        question="Explain the difference between supervised and unsupervised learning.",
        ideal_answer=(
            "Supervised learning trains on labelled examples, learning a mapping from inputs to a "
            "known target, as in classification and regression. Unsupervised learning has no labels "
            "and instead finds structure in the data itself, as in clustering or dimensionality "
            "reduction. Supervised performance is measured against the ground-truth labels. "
            "Unsupervised results need indirect evaluation, since there is no correct answer to "
            "compare against."
        ),
        key_concepts=("labelled examples", "clustering", "ground truth", "dimensionality reduction"),
        sentences=(
            "Supervised learning trains on labelled examples to map inputs to a known target.",
            "Unsupervised learning has no labels and finds structure, as in clustering.",
            "Supervised performance is measured against ground truth labels.",
            "Unsupervised results need indirect evaluation, including dimensionality reduction checks.",
        ),
    ),
    SeedItem(
        question="What is the role of the garbage collector in a managed runtime?",
        ideal_answer=(
            "The garbage collector reclaims heap memory holding objects no longer reachable from "
            "the program's roots. It frees the programmer from manual deallocation, removing whole "
            "classes of use-after-free and double-free bugs. Generational collectors exploit the "
            "fact that most objects die young, collecting a small nursery frequently and older "
            "objects rarely. The cost is pause times and less predictable latency than manual "
            "memory management."
        ),
        key_concepts=("reachable", "heap memory", "generational", "pause times"),
        sentences=(
            "The garbage collector reclaims heap memory for objects no longer reachable from roots.",
            "It removes manual deallocation and the use-after-free bugs that come with it.",
            "Generational collectors collect a young nursery often and older objects rarely.",
            "The cost is pause times and less predictable latency.",
        ),
    ),
    SeedItem(
        question="Why does a binary search require a sorted array?",
        ideal_answer=(
            "Binary search works by comparing the target to the middle element and discarding the "
            "half that cannot contain it. Discarding a half is only valid if the array is sorted, "
            "because sorting is what guarantees everything on one side is smaller. That halving "
            "gives O(log n) comparisons instead of the O(n) of a linear scan. On unsorted data the "
            "comparison carries no information about where the target lies."
        ),
        key_concepts=("middle element", "sorted order", "logarithmic", "linear scan"),
        sentences=(
            "Binary search compares the target to the middle element and discards half the range.",
            "Discarding a half is only valid because sorted order guarantees one side is smaller.",
            "Halving each step gives logarithmic comparisons rather than a linear scan.",
            "On unsorted data the comparison says nothing about where the target lies.",
        ),
    ),
    SeedItem(
        question="What does the CAP theorem say about distributed databases?",
        ideal_answer=(
            "CAP says a distributed system cannot simultaneously guarantee consistency, "
            "availability, and partition tolerance. Since network partitions are unavoidable in "
            "practice, the real choice is between consistency and availability during a partition. "
            "A CP system refuses requests it cannot serve correctly, while an AP system answers "
            "with possibly stale data. Many real systems are tunable per operation rather than "
            "fixed at one extreme."
        ),
        key_concepts=("consistency", "availability", "partition tolerance", "stale data"),
        sentences=(
            "CAP says consistency, availability, and partition tolerance cannot all be guaranteed.",
            "Because partitions are unavoidable, the choice is between consistency and availability.",
            "A CP system refuses requests it cannot serve correctly during a partition tolerance event.",
            "An AP system stays up but may answer with stale data.",
        ),
    ),
)


@dataclass(frozen=True)
class TrainingRow:
    item_index: int
    answer: str
    ideal_answer: str
    key_concepts: tuple[str, ...]
    label: float
    tier: str


def _with_filler(text: str, rng: random.Random, count: int) -> str:
    """Sprinkles filler words through the text at word boundaries, the way a
    spoken answer carries them — not bolted onto the front, which the model
    would learn as a positional quirk rather than a delivery signal."""
    if count <= 0:
        return text
    words = text.split()
    for _ in range(count):
        if not words:
            break
        position = rng.randrange(len(words) + 1)
        words.insert(position, rng.choice(FILLER_INSERTS))
    return " ".join(words)


def _truncate_words(text: str, fraction: float) -> str:
    words = text.split()
    keep = max(1, int(len(words) * fraction))
    return " ".join(words[:keep])


def _build_rows(rng: random.Random) -> list[TrainingRow]:
    """Expands each seed item into answers at known quality tiers.

    The label for a partial answer is anchored to how much of the ideal
    content it retains (concept count and sentence prefix), then nudged by
    the delivery penalties a human grader would actually apply — a small
    deduction for heavy filler, a small one for being far too short. Those
    nudges are what stop the model from treating delivery as free.
    """
    rows: list[TrainingRow] = []

    for index, item in enumerate(SEED_ITEMS):
        concepts = item.key_concepts
        sentences = item.sentences

        def add(answer: str, label: float, tier: str) -> None:
            rows.append(
                TrainingRow(
                    item_index=index,
                    answer=answer,
                    ideal_answer=item.ideal_answer,
                    key_concepts=concepts,
                    label=max(0.0, min(100.0, label)),
                    tier=tier,
                )
            )

        # --- Tier: complete. The ideal answer itself, and lightly reworded
        # versions of it. Scores at the top but not a flat 100 — a model that
        # only ever predicts 100 for a perfect answer has learned a ceiling,
        # not a scale.
        add(item.ideal_answer, 97.0, "complete")
        add(f"{rng.choice(HEDGES)}, {item.ideal_answer[0].lower()}{item.ideal_answer[1:]}", 93.0, "complete")
        add(_with_filler(item.ideal_answer, rng, 2), 90.0, "complete_spoken")
        add(_with_filler(item.ideal_answer, rng, 6), 84.0, "complete_rambling")
        add(f"{item.ideal_answer} {rng.choice(VAGUE_TAILS)}.", 92.0, "complete")

        # --- Tier: strong. All but the last point.
        strong = " ".join(sentences[:-1])
        add(strong, 78.0, "strong")
        add(_with_filler(strong, rng, 3), 72.0, "strong_spoken")
        add(f"{rng.choice(HEDGES)} {strong.lower()}", 75.0, "strong")

        # --- Tier: partial. Roughly half the points.
        half = max(1, len(sentences) // 2)
        partial = " ".join(sentences[:half])
        add(partial, 55.0, "partial")
        add(_with_filler(partial, rng, 3), 48.0, "partial_spoken")
        add(_truncate_words(partial, 0.6), 42.0, "partial_short")

        # --- Tier: thin. One point only, stated briefly.
        add(sentences[0], 38.0, "thin")
        add(_truncate_words(sentences[0], 0.5), 28.0, "thin_short")
        add(_with_filler(_truncate_words(sentences[0], 0.6), rng, 4), 24.0, "thin_spoken")

        # --- Tier: vague. On-topic words, no actual content. This is the tier
        # that teaches the model that sounding relevant is not the same as
        # answering, which a similarity-only scorer gets badly wrong.
        topic_hint = concepts[0]
        add(
            f"It's about {topic_hint}, and it matters because of how the whole thing works, "
            f"{rng.choice(VAGUE_TAILS)}.",
            18.0,
            "vague",
        )
        add(f"{rng.choice(HEDGES)} it has something to do with {topic_hint}.", 14.0, "vague")
        add(_with_filler(f"Yeah it's the {topic_hint} thing, that's the main part.", rng, 3), 12.0, "vague")

        # --- Tier: off-topic. Another item's ideal answer, which is fluent,
        # well-formed, and completely wrong — the case an LLM-as-judge is
        # most likely to be charmed by.
        other = SEED_ITEMS[(index + 1) % len(SEED_ITEMS)]
        add(other.ideal_answer, 4.0, "off_topic")
        add(_truncate_words(other.ideal_answer, 0.4), 3.0, "off_topic")
        further = SEED_ITEMS[(index + 5) % len(SEED_ITEMS)]
        add(further.sentences[0], 2.0, "off_topic")

        # --- Tier: non-answer. Scored zero by construction, and also forced
        # to zero at runtime in score_answer — trained on anyway so the
        # model's own output is consistent with that clamp rather than
        # fighting it.
        for text in ("", "I don't know", "no idea", "I don't remember", "skip", "pass"):
            add(text, 0.0, "non_answer")

    return rows


def _split_by_item(rows: list[TrainingRow], rng: random.Random) -> tuple[list[TrainingRow], list[TrainingRow]]:
    """Groups the split by seed item so no item's variants appear in both
    train and test. A random row-level split would let the model memorise an
    item's ideal answer and then score its own paraphrases, which would make
    the reported metrics flattering and meaningless."""
    item_indices = sorted({row.item_index for row in rows})
    rng.shuffle(item_indices)
    test_count = max(1, round(len(item_indices) * TEST_ITEM_FRACTION))
    test_items = set(item_indices[:test_count])
    train = [row for row in rows if row.item_index not in test_items]
    test = [row for row in rows if row.item_index in test_items]
    return train, test


def main() -> None:
    import joblib
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error, r2_score

    rng = random.Random(RANDOM_SEED)
    rows = _build_rows(rng)
    train_rows, test_rows = _split_by_item(rows, rng)

    print(f"Corpus: {len(rows)} answers across {len(SEED_ITEMS)} seed items")
    print(f"Split:  {len(train_rows)} train / {len(test_rows)} test (grouped by item)")
    print("Extracting features (this loads the embedding model once)…")

    def featurize(batch: list[TrainingRow]) -> tuple[list[list[float]], list[float]]:
        vectors: list[list[float]] = []
        labels: list[float] = []
        for row in batch:
            features = extract_features(row.answer, row.ideal_answer, row.key_concepts)
            vectors.append(features.as_vector())
            labels.append(row.label)
        return vectors, labels

    x_train, y_train = featurize(train_rows)
    x_test, y_test = featurize(test_rows)

    # Gradient boosting over ridge: the relationship is non-linear in a way
    # that matters — a fluent off-topic answer has high length_ratio and
    # middling similarity but near-zero coverage, and must score low, which a
    # linear model (summing independent positive weights) cannot express.
    # Kept deliberately small: 5 features and a few hundred rows do not
    # support a deep ensemble, and a shallow one stays inspectable via
    # feature_importances_.
    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=3,
        learning_rate=0.06,
        subsample=0.9,
        random_state=RANDOM_SEED,
    )
    model.fit(np.array(x_train), np.array(y_train))

    predictions = np.clip(model.predict(np.array(x_test)), 0.0, 100.0)
    mae = float(mean_absolute_error(y_test, predictions))
    r2 = float(r2_score(y_test, predictions))

    # Per-tier error, because a single MAE hides the failure that actually
    # matters: scoring an off-topic answer highly. A model with a good
    # overall MAE and a terrible off_topic MAE is not usable here.
    per_tier: dict[str, float] = {}
    for tier in sorted({row.tier for row in test_rows}):
        errors = [
            abs(float(prediction) - row.label)
            for row, prediction in zip(test_rows, predictions, strict=True)
            if row.tier == tier
        ]
        if errors:
            per_tier[tier] = round(statistics.fmean(errors), 2)

    importances = {
        name: round(float(value), 4)
        for name, value in zip(FEATURE_ORDER, model.feature_importances_, strict=True)
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    metrics = {
        "model": "GradientBoostingRegressor",
        "feature_order": list(FEATURE_ORDER),
        "random_seed": RANDOM_SEED,
        "corpus_size": len(rows),
        "seed_items": len(SEED_ITEMS),
        "train_rows": len(train_rows),
        "test_rows": len(test_rows),
        "split": "grouped by seed item, so no item appears in both train and test",
        "held_out_mae": round(mae, 2),
        "held_out_r2": round(r2, 4),
        "held_out_mae_by_tier": per_tier,
        "feature_importances": importances,
        "label_provenance": (
            "Labels are assigned by construction from how each answer was generated "
            "(concepts retained, fraction of the ideal answer kept, delivery penalties), "
            "not by human grading. Metrics therefore measure generalisation across "
            "constructed variants, not agreement with human examiners."
        ),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2) + "\n")

    print(f"\nHeld-out MAE: {mae:.2f} points (0-100 scale)")
    print(f"Held-out R²:  {r2:.4f}")
    print("\nMAE by tier:")
    for tier, value in sorted(per_tier.items(), key=lambda pair: pair[1]):
        print(f"  {tier:22s} {value:6.2f}")
    print("\nFeature importances:")
    for name, value in sorted(importances.items(), key=lambda pair: -pair[1]):
        print(f"  {name:22s} {value:.4f}")
    print(f"\nSaved {MODEL_PATH}")
    print(f"Saved {METRICS_PATH}")


if __name__ == "__main__":
    main()
