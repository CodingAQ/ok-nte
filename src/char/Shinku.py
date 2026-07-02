import time

from src.char.BaseChar import BaseChar
from src.combat.planner import CombatContext, Planner, RoleProfile


class Shinku(BaseChar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.MAIN_DPS,
            field_preference=Planner.FieldPreference.MAIN_DPS,
            max_field_time=1.5,
        )

    def combat_intents(self, context):
        return self.intents(
            self.click_skill_action(),
            self.click_ultimate_action(
                after_execute=self._after_ultimate_execute,
            ),
        )

    def _after_ultimate_execute(
        self,
        context: CombatContext = None,
        success=False,
    ):
        if success:
            self.perform_in_ult(context)

    def perform_in_ult(self, context: CombatContext = None):
        start = time.time()
        while (elapsed := time.time() - start) < 12:
            if elapsed > 9 and self.ultimate_available():
                if self.click_ultimate():
                    return True
            self.click_skill()
            self.sleep(0.1)
            self.normal_attack()
            self.sleep(0.1)
        return False
    
    def on_combat_end(self, chars):
        self.switch_other_char()
