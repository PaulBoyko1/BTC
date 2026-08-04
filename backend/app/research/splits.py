from __future__ import annotations

from dataclasses import replace

from .types import Candle, FoldDefinition, WalkForwardConfig


SECONDS_PER_DAY = 86_400


def build_walk_forward_folds(
    start_timestamp: int,
    end_timestamp: int,
    config: WalkForwardConfig,
    maximum_horizon_minutes: int,
) -> list[FoldDefinition]:
    train_seconds = config.train_days * SECONDS_PER_DAY
    validation_seconds = config.validation_days * SECONDS_PER_DAY
    test_seconds = config.test_days * SECONDS_PER_DAY
    step_seconds = config.step_days * SECONDS_PER_DAY
    first_train_start = start_timestamp
    cursor = start_timestamp + train_seconds
    folds: list[FoldDefinition] = []
    index = 0
    while cursor + validation_seconds + test_seconds <= end_timestamp:
        train_start = first_train_start if config.mode == "expanding" else cursor - train_seconds
        train_end = cursor
        validation_start = train_end
        validation_end = validation_start + validation_seconds
        test_start = validation_end
        test_end = test_start + test_seconds
        folds.append(FoldDefinition(
            fold_index=index,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=test_end,
        ))
        cursor += step_seconds
        index += 1
    return folds


def purge_and_embargo_indices(
    candles: list[Candle],
    training_start: int,
    training_end: int,
    test_start: int,
    test_end: int,
    prediction_horizon_minutes: int,
    maximum_holding_minutes: int,
    embargo_minutes: int,
) -> tuple[list[int], int, int]:
    """Return usable training indices and exact purge/embargo counts.

    An observation's label window begins at its candle availability and ends at
    availability plus the larger of prediction and holding horizon. Any window
    intersecting the test interval is purged. Observations in the configured
    post-test embargo interval are excluded separately.
    """

    label_seconds = max(prediction_horizon_minutes, maximum_holding_minutes) * 60
    embargo_end = test_end + embargo_minutes * 60
    kept: list[int] = []
    purged = 0
    embargoed = 0
    for index, candle in enumerate(candles):
        if not (training_start <= candle.timestamp < training_end):
            continue
        available = candle.availability_timestamp or candle.timestamp
        label_end = available + label_seconds
        overlaps_test = available < test_end and label_end > test_start
        if overlaps_test:
            purged += 1
            continue
        if test_end <= available < embargo_end:
            embargoed += 1
            continue
        kept.append(index)
    return kept, purged, embargoed


def annotate_fold_counts(
    fold: FoldDefinition,
    candles: list[Candle],
    prediction_horizon_minutes: int,
    maximum_holding_minutes: int,
    embargo_minutes: int,
) -> FoldDefinition:
    _, purged, embargoed = purge_and_embargo_indices(
        candles,
        fold.train_start,
        fold.train_end,
        fold.test_start,
        fold.test_end,
        prediction_horizon_minutes,
        maximum_holding_minutes,
        embargo_minutes,
    )
    return fold.model_copy(update={"purged_observations": purged, "embargoed_observations": embargoed})
