from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np


@dataclass
class CurrentCharDetection:
    index: int
    score: float
    scores: list[float]
    accepted: bool
    strong: bool
    reason: str
    active_scores: list[float]


@dataclass(frozen=True)
class CurrentCharConfig:
    reject_score: float = 0.75
    accept_score: float = 0.45
    active_marker_score: float = 0.035
    active_marker_margin: float = 0.008
    active_marker_single_score: float = 0.10
    active_marker_shape_weight: float = 0.08
    sticky_seconds: float = 0.8


DEFAULT_CURRENT_CHAR_CONFIG = CurrentCharConfig()


def normalize_char_count(char_count: int | None) -> int:
    if char_count is None:
        return 4
    return max(0, min(int(char_count), 4))


def build_current_char_scores(
    index: int,
    score: float,
    accepted: bool,
    config: CurrentCharConfig = DEFAULT_CURRENT_CHAR_CONFIG,
) -> list[float]:
    scores = [config.reject_score] * 4
    if accepted and 0 <= index < len(scores):
        scores[index] = min(score, config.accept_score)
    return scores


def detect_current_char(
    slot_images: Sequence[np.ndarray],
    template_mat: np.ndarray | None,
    char_count: int | None = None,
    config: CurrentCharConfig = DEFAULT_CURRENT_CHAR_CONFIG,
) -> CurrentCharDetection:
    candidate_count = normalize_char_count(char_count)
    if candidate_count <= 0:
        return CurrentCharDetection(
            index=-1,
            score=1.0,
            scores=[config.reject_score] * 4,
            accepted=False,
            strong=False,
            reason="empty_char_count",
            active_scores=[0.0] * 4,
        )

    template_mask = current_char_shape_template(template_mat)
    active_scores = [0.0] * 4
    for index, image in enumerate(slot_images[:candidate_count]):
        active_scores[index] = current_char_activation_score(
            image,
            template_mask=template_mask,
            config=config,
        )

    index, active_score, active_margin = rank_current_char_activation_scores(
        active_scores,
        candidate_count,
    )
    accepted = active_score >= config.active_marker_score and (
        (candidate_count == 1 and active_score >= config.active_marker_single_score)
        or active_margin >= config.active_marker_margin
    )
    score = max(0.0, config.accept_score - active_score)
    scores = build_current_char_scores(index, score, accepted, config=config)

    return CurrentCharDetection(
        index=index if accepted else -1,
        score=score if accepted else 1.0,
        scores=scores,
        accepted=accepted,
        strong=accepted,
        reason="active_marker" if accepted else "rejected",
        active_scores=active_scores,
    )


def rank_current_char_activation_scores(
    scores: Sequence[float],
    candidate_count: int,
) -> tuple[int, float, float]:
    if not scores or candidate_count <= 0:
        return -1, 0.0, 0.0

    candidate_scores = scores[:candidate_count]
    best_idx = int(np.argmax(candidate_scores))
    ordered_scores = sorted(candidate_scores, reverse=True)
    best_score = ordered_scores[0]
    second_score = ordered_scores[1] if len(ordered_scores) > 1 else 0.0
    return best_idx, best_score, best_score - second_score


def current_char_shape_template(template_mat: np.ndarray | None) -> np.ndarray | None:
    if template_mat is None or template_mat.size == 0:
        return None

    if template_mat.ndim == 3 and template_mat.shape[2] >= 3:
        mask, _, _ = current_char_active_mask(template_mat)
    elif template_mat.ndim == 3 and template_mat.shape[2] >= 2:
        chroma = np.sqrt(
            (template_mat[:, :, 0].astype(np.int16) - 128) ** 2
            + (template_mat[:, :, 1].astype(np.int16) - 128) ** 2
        )
        mask = chroma >= 20
    else:
        mask = template_mat > 20

    if mask is None or not np.any(mask):
        return None

    mask = mask.astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def current_char_active_mask(
    image: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    if image.size == 0:
        return None, None, None

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2Lab).astype(np.int16)
    chroma = np.sqrt((lab[:, :, 1] - 128) ** 2 + (lab[:, :, 2] - 128) ** 2)
    height, width = image.shape[:2]
    y_grid, x_grid = np.mgrid[:height, :width]
    roi = (
        (x_grid >= width * 0.15)
        & (x_grid <= width * 0.90)
        & (y_grid >= height * 0.15)
        & (y_grid <= height * 0.95)
    )
    hue = hsv[:, :, 0]
    active_hue = ((hue >= 18) & (hue <= 45)) | ((hue >= 148) & (hue <= 179))
    active_mask = roi & active_hue & (hsv[:, :, 1] >= 55) & (hsv[:, :, 2] >= 65) & (chroma >= 20)
    if not np.any(active_mask):
        return active_mask, roi, None

    saturation = hsv[:, :, 1].astype(np.float32) / 255
    value = hsv[:, :, 2].astype(np.float32) / 255
    color_strength = np.minimum(chroma.astype(np.float32), 90) / 90
    y_weight = np.where(y_grid >= height * 0.42, 1.35, 0.75)
    x_weight = np.where(
        (x_grid >= width * 0.18) & (x_grid <= width * 0.78),
        1.2,
        0.8,
    )
    weighted = saturation * value * color_strength * y_weight * x_weight
    return active_mask, roi, weighted


def current_char_activation_score(
    image: np.ndarray,
    template_mask: np.ndarray | None = None,
    config: CurrentCharConfig = DEFAULT_CURRENT_CHAR_CONFIG,
) -> float:
    active_mask, roi, weighted = current_char_active_mask(image)
    if active_mask is None or roi is None or weighted is None:
        return 0.0

    color_score = float(weighted[active_mask].sum() / max(1, int(np.count_nonzero(roi))))
    shape_score = current_char_shape_score(active_mask, template_mask)
    return color_score + shape_score * config.active_marker_shape_weight


def current_char_shape_score(
    active_mask: np.ndarray,
    template_mask: np.ndarray | None,
) -> float:
    if template_mask is None or active_mask is None or not np.any(active_mask):
        return 0.0

    candidate = active_mask.astype(np.float32)
    template = template_mask.astype(np.float32)
    candidate_height, candidate_width = candidate.shape[:2]
    template_height, template_width = template.shape[:2]
    if template_height > candidate_height or template_width > candidate_width:
        scale = min(candidate_height / template_height, candidate_width / template_width)
        template_width = max(1, int(template_width * scale))
        template_height = max(1, int(template_height * scale))
        template = cv2.resize(
            template,
            (template_width, template_height),
            interpolation=cv2.INTER_AREA,
        )

    result = cv2.matchTemplate(candidate, template, cv2.TM_CCORR_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    if np.isnan(max_val):
        return 0.0
    return float(max_val)
