from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask
from src.Labels import Labels
from src.tasks.BaseNTETask import Box
from src.tasks.NTEOneTimeTask import NTEOneTimeTask

SPACE = "&nbsp;" * 4

# ruff: noqa: E501
INST = (
    "手动传送一次目标篝火后不要转动视角，直接开始任务。\n\n"
    "巧克力火山-底层最左边的篝火\n"
    f"{SPACE}底层整个地图最靠左的篝火\n"
    f"{SPACE}https://b23.tv/qsEVcDO\n\n"
    "赤龙古堡-龙之高塔室外篝火\n"
    f"{SPACE}龙之高塔只有两个篝火，室外旁边有棵树的篝火"
)

EN_INST = (
    "After manually teleporting to the target campfire once, do not rotate the camera; begin the quest immediately.\n\n"
    "Chocolate Volcano - Bottom Floor Leftmost Bonfire\n"
    f"{SPACE}The campfire on the far left of the entire bottom map\n"
    f"{SPACE}https://b23.tv/qsEVcDO\n\n"
    "Red Dragon Castle - Dragon Tower Outdoor Campfire\n"
    f"{SPACE}The Dragon Tower only has two campfires, one of which is outdoors next to a tree."
)
# ruff: noqa


class DSDFarmTask(NTEOneTimeTask, BaseCombatTask):
    CONF_LOCATION = "位置"
    CONF_ROUNDS = "循环次数"
    CONF_USE_ULT = "使用终结技"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "九百九十九夜"
        self.description = "挂机刷经验"
        self.icon = FluentIcon.FLAG
        _locale = self.get_app_locale()
        self.instructions = INST if _locale and "zh" in _locale else EN_INST
        self.locations = ["巧克力火山-底层最左边的篝火", "赤龙古堡-龙之高塔室外篝火"]
        self.default_config.update(
            {
                self.CONF_LOCATION: self.locations[0],
                self.CONF_ROUNDS: 0,
                self.CONF_USE_ULT: True
            }
        )

        self.config_description.update(
            {
                self.CONF_ROUNDS: "循环次数, 设置为0则一直运行",
            }
        )

        self.config_type.update(
            {
                self.CONF_LOCATION: {
                    "type": "drop_down",
                    "options": self.locations,
                },
            }
        )

    def run(self):
        super().run()
        try:
            self.sleep_check_skip.all = True
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("DSDFarmTask Error", e)
        finally:
            self.sleep_check_skip.all = False

    def do_run(self):
        self.use_ultimate = self.config.get(self.CONF_USE_ULT, True)
        self.deside_map_zoom()
        n = 0
        while True:
            n += 1
            rounds = self.config.get(self.CONF_ROUNDS, 0)
            if rounds == 0:
                rounds_text = f"{n} / ∞"
            elif n > rounds:
                return
            else:
                rounds_text = f"{n} / {rounds}"
            self.info_set("轮次", rounds_text)
            self.wait_until(
                self.find_interac,
                time_out=10,
                raise_if_not_found=True,
            )
            self.wait_until(
                lambda: not self.is_in_team(),
                pre_action=lambda: self.send_interac(handle_claim=False),
                time_out=10,
                raise_if_not_found=True,
            )
            self.sleep(2)
            self.operate_click(0.057, 0.218)
            self.sleep(0.5)
            self.ensure_main()
            self.deside_action()
            self.next_frame()

    def sleep_check(self):
        super().sleep_check()
        if self.should_check_monthly_card():
            self.handle_monthly_card()

    def deside_map_zoom(self):
        location = self.config.get(self.CONF_LOCATION, None)
        if location == self.locations[0]:
            self.map_zoom(zoom="max")
        elif location == self.locations[1]:
            self.map_zoom(zoom="mid")

    def deside_action(self):
        location = self.config.get(self.CONF_LOCATION, None)

        if location == self.locations[0]:
            self.location_0()
        elif location == self.locations[1]:
            self.location_1()

    def location_0(self):
        if self.walk_until_combat(run=True, delay=1):
            with self.skip_sleep_checks() as skip:
                skip.all = False
                self.combat_once()
        self.sleep(0.5)
        while True:
            if self.teleport_to_nearest_bonfire():
                break
            self.ensure_main()
            self.sleep(0.5)

    def location_1(self):
        self.send_key_down("w")
        self.sleep(0.37)
        self.send_key_down("lshift")
        self.sleep(0.12)
        self.send_key_up("lshift")
        self.sleep(4.11)
        self.send_key_up("w")
        self.sleep(0.51)
        self.send_key_down("s")
        self.sleep(0.40)
        self.send_key_up("s")
        self.sleep(0.18)
        self.send_key_down("d")
        self.sleep(0.36)
        self.send_key_down("w")
        self.sleep(0.5)
        for _ in range(5):
            self.send_key_down("d")
            self.sleep(0.5)
            self.send_key_up("d")
            self.sleep(0.8)
        self.sleep(2)
        self.send_key_up("w")
        if self.wait_until(self.in_combat, time_out=10):
            with self.skip_sleep_checks() as skip:
                skip.all = False
                self.combat_once()
        self.sleep(0.5)
        box = self.box_of_screen(0.498, 0.102, 0.931, 0.827)
        while True:
            if self.teleport_to_top_bonfire(box):
                break
            self.ensure_main()
            self.sleep(0.5)

    def map_zoom(self, zoom="max"):
        self.ensure_main()
        self.open_map()
        if zoom == "max":
            self.operate_click(0.050, 0.378)
        elif zoom == "mid":
            self.operate_click(0.050, 0.527)
        self.sleep(1)
        self.ensure_main()

    def open_map(self):
        self.wait_until(
            lambda: self.find_one(Labels.map_zoom_in),
            time_out=10,
            pre_action=lambda: self.send_key("m", interval=2),
            raise_if_not_found=True,
        )
        self.sleep(1)

    def teleport_to_nearest_bonfire(self, threshold=0.7, time_out=10):
        self.ensure_main()
        self.open_map()
        to_find = [Labels.bonfire_teleport]
        template_boxes = [self.get_box_by_name(label) for label in to_find]
        max_template_size = max(
            max(template_box.width, template_box.height) for template_box in template_boxes
        )
        step = max(max_template_size, self.width_of_screen(0.02), 1)
        center_x = self.width_of_screen(0.5)
        center_y = self.height_of_screen(0.5)
        max_radius = max(self.width, self.height)

        def find_teleport():
            radius = step
            while radius <= max_radius:
                x = max(0, center_x - radius)
                y = max(0, center_y - radius)
                to_x = min(self.width, center_x + radius)
                to_y = min(self.height, center_y + radius)
                box = Box(x=x, y=y, to_x=to_x, to_y=to_y, name="nearest_map_teleport")
                teleport = self.find_best_match_in_box(box, to_find, threshold=threshold)
                if teleport:
                    return teleport
                radius += step

        teleport = self.wait_until(find_teleport, time_out=time_out, raise_if_not_found=True)
        self.log_info(f"found nearest map teleport {teleport}")
        self.operate_click(teleport, action_name="click_nearest_map_teleport")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)

    def teleport_to_top_bonfire(self, box: Box, threshold=0.7):
        self.ensure_main()
        self.open_map()

        teleports = self.find_feature(Labels.bonfire_teleport, box=box, threshold=threshold)
        if not teleports:
            return False

        self.log_info(f"found map teleports {teleports}")

        teleport = min(teleports, key=lambda teleport: teleport.y)
        self.operate_click(teleport, action_name="click_map_teleport")
        self.sleep(0.5)
        return self.click_traval_button(raise_if_not_found=False)
