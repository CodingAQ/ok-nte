import time

from ok import BaseTask, Box

from src.Labels import Labels
from src.utils import image_utils as iu
from src.utils.current_char_detector import (
    CurrentCharConfig,
    CurrentCharDetection,
    build_current_char_scores,
    detect_current_char,
    normalize_char_count,
)


class CharUIMixin(BaseTask):
    _CURRENT_CHAR = CurrentCharConfig()

    def _init_char_ui_state(self):
        self._char_ui_offset = False
        self._current_char_tracker = {
            "index": -1,
            "score": 1.0,
            "time": 0,
            "reason": "",
        }

    def _get_char_text_box(self, index: int):
        box = self.get_box_by_name(f"char_{index + 1}_text")
        return box

    def get_base_char_element_box(self):
        box = self.box_of_screen_scaled(
            2560, 1440, 2438, 335, width_original=29, height_original=29
        )
        box = self._shift_char_ui_box(box, expend=True)
        return box

    def _shift_char_ui_box(self, box: Box, expend=False):
        offset = -9 * self.width / 2560
        width_offset = 0
        if expend:
            width_offset = -offset
        box = box.copy(x_offset=offset, width_offset=width_offset)
        return box

    @property
    def _char_vertical_spacing(self):
        return int(self.height * 176 / 1440)

    def get_box_by_char_spacing(self, box: Box, index: int):
        return box.copy(y_offset=index * self._char_vertical_spacing, name=f"{box.name}_{index}")

    def _get_current_char_template(self):
        if (
            not hasattr(self, "_char_template_cache")
            or self._char_template_cache.get("width") != self.width
            or self._char_template_cache.get("height") != self.height
        ):
            feature = self.get_feature_by_name(Labels.is_current_char)
            self._char_template_cache = {
                "width": self.width,
                "height": self.height,
                "mat": feature.mat,
            }

        return self._char_template_cache["mat"]

    def _build_current_char_scores(self, index, score, accepted):
        return build_current_char_scores(index, score, accepted, config=self._CURRENT_CHAR)

    def _get_current_char_boxes(self):
        base_box = self.get_box_by_name(Labels.is_current_char)
        base_box = self._shift_char_ui_box(base_box, expend=True)
        return base_box, [self.get_box_by_char_spacing(base_box, i) for i in range(4)]

    def _detect_current_char_once(self, frame=None, char_count=None):
        candidate_count = normalize_char_count(char_count)
        if frame is None:
            frame = self.frame
        if frame is None or candidate_count <= 0:
            return CurrentCharDetection(
                index=-1,
                score=1.0,
                scores=[self._CURRENT_CHAR.reject_score] * 4,
                accepted=False,
                strong=False,
                reason="empty_frame" if frame is None else "empty_char_count",
                active_scores=[0.0] * 4,
            )

        _, boxes = self._get_current_char_boxes()
        slot_images = [box.crop_frame(frame) for box in boxes[:candidate_count]]
        detection = detect_current_char(
            slot_images=slot_images,
            template_mat=self._get_current_char_template(),
            char_count=candidate_count,
            config=self._CURRENT_CHAR,
        )

        if 0 <= detection.index < len(boxes):
            self.draw_boxes(boxes=boxes[detection.index], color="red")

        return detection

    def _apply_current_char_tracker(self, detection: CurrentCharDetection, char_count=None):
        now = time.time()
        tracker = self._current_char_tracker
        candidate_count = normalize_char_count(char_count)
        if detection.accepted:
            tracker["index"] = detection.index
            tracker["score"] = detection.score
            tracker["time"] = now
            tracker["reason"] = detection.reason
            return detection

        if (
            tracker["index"] != -1
            and tracker["index"] < candidate_count
            and now - tracker["time"] <= self._CURRENT_CHAR.sticky_seconds
        ):
            index = tracker["index"]
            score = max(tracker["score"], self._CURRENT_CHAR.accept_score)
            scores = self._build_current_char_scores(index, score, accepted=True)
            return CurrentCharDetection(
                index=index,
                score=scores[index],
                scores=scores,
                accepted=True,
                strong=False,
                reason=f"sticky:{tracker['reason']}",
                active_scores=detection.active_scores,
            )

        return detection

    def _get_current_char_detection(self, frame=None, char_count=None):
        detection = self._detect_current_char_once(frame=frame, char_count=char_count)
        if frame is None:
            return self._apply_current_char_tracker(detection, char_count=char_count)
        return detection

    def _get_char_match_scores(self, frame=None, char_count=None):
        """Return four slot scores; lower means the slot is the current char."""
        return self._get_current_char_detection(frame=frame, char_count=char_count).scores

    def get_current_char_index(self, char_count=None):
        # frame = self.frame
        detection = self._get_current_char_detection(char_count=char_count)
        if detection.accepted:
            self.log_debug(
                f"current_char found at {detection.index} "
                f"with score {detection.score:.4f} ({detection.reason})"
            )
            # if detection.score > 0.5:
            #     self.screenshot("low_conf", frame)
            return detection.index

        self.log_debug(
            f"current_char rejected ({detection.reason}) active={detection.active_scores}"
        )
        return -1

    def _multi_stage_char_match(self):
        results = [None, None, None, None]
        contrast_steps = [0, 30, 60, 90]

        for c_val in contrast_steps:
            if all(res is not None for res in results):
                break

            for i in range(4):
                if results[i] is not None:
                    continue

                def process(image, current_c=c_val):
                    return iu.adjust_lightness_contrast_lab(image, brightness=0, contrast=current_c)

                res = self.find_one(
                    f"char_{i + 1}_text",
                    threshold=0.7,
                    frame_processor=process,
                    mask_function=iu.mask_outside_white_rect,
                    horizontal_variance=0.005,
                )
                if res:
                    results[i] = res

        return results

    def _update_char_ui_offset(self):
        # now = time.time()
        arr = self._multi_stage_char_match()
        results = [
            c.x < self._get_char_text_box(idx).x for idx, c in enumerate(arr) if c is not None
        ]

        if results:
            self._char_ui_offset = sum(results) > (len(results) / 2)
        else:
            self._char_ui_offset = False
        # logger.debug(f"update_char_ui_offset cost {time.time() - now:.3f}")
        return arr
