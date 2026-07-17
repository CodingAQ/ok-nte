import time

from ok import Logger, TriggerTask
from qfluentwidgets import FluentIcon

from src.combat.BaseCombatTask import BaseCombatTask, NotInCombatException

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    CONF_USE_ULT = "使用终结技"
    CONF_AUTO_TARGET = "自动目标"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {"_enabled": True}
        self.trigger_interval = 0.1
        self.name = "自动战斗"
        self.description = "受《异环》UI的特殊性影响, 部分场景下存在识别稳定性波动"
        self.icon = FluentIcon.CALORIES
        self.last_is_click = False
        self.default_config.update(
            {
                self.CONF_AUTO_TARGET: True,
                self.CONF_USE_ULT: True
            }
        )
        self.config_description = {
            self.CONF_AUTO_TARGET: "关闭时仅在中键选中敌人且画面识别到 'Lv' 文字时开启战斗",
        }
        self.op_index = 0
        self.origin_func = {}

    def run(self):
        ret = False
        if not self.scene.is_in_team(self.is_in_team):
            return

        try:
            while self.in_combat():
                if not ret:
                    ret = True
                    combat_start = time.time()
                    self.use_ultimate = self.config.get(self.CONF_USE_ULT, True)
                    self.switch_to_combat_start_char()
                self.get_current_char(raise_exception=True).perform()
        except NotInCombatException as e:
            logger.info(f"auto_combat_task_out_of_combat {int(time.time() - combat_start)} {e}")
        finally:
            if ret:
                self.combat_end()
