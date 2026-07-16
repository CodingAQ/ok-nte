from src.char.BaseChar import BaseChar
from src.combat.planner import Planner, RoleProfile


class Healer(BaseChar):
    def describe_role(self):
        return RoleProfile(
            role=Planner.Role.SUPPORT,
            field_preference=Planner.FieldPreference.SUPPORT,
            max_field_time=0.5,
        )

    def combat_plan(self, context):
        return self.plan(
            self.click_ultimate_action(
                tags={Planner.ActionTag.ULTIMATE_ACTION, Planner.ActionTag.SUPPORT},
                reason="support ultimate available",
            ),
            self.click_skill_action(
                tags={Planner.ActionTag.SKILL_ACTION, Planner.ActionTag.SUPPORT},
                reason="support skill available",
            ),
            (
                self.planner_action(
                    name="healer_refresh",
                    tags={Planner.ActionTag.SUPPORT},
                    execute=self._execute_refresh_action,
                    reason="support has been off field too long",
                )
                if self.time_elapsed_accounting_for_freeze(self.last_perform) > 20
                else None
            )
        )


    def _execute_refresh_action(self, context=None):
        self.continues_normal_attack(0.5, click_skill_if_ready_and_return=True)
        return True
