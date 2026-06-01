import re
import time

from ok import TaskDisabledException
from qfluentwidgets import FluentIcon

from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask
from src.utils import image_utils as iu

class DarkTask(NTEOneTimeTask, BaseNTETask):
    CONF_TIME = "循环次数(0为无限次)"
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "黑暗赛车"
        self.description = "自动执行黑暗赛车,请在大世界开始执行"
        self.icon = FluentIcon.CAR
        self.default_config.update(
            {
                self.CONF_TIME: 0,
            }
        )

    def run(self):
        super().run()
        try:
            self.do_run()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error("DarkTask error", e)
            raise

    def do_run(self):
        current_time = 0
        max_time = self.config.get(self.CONF_TIME, 0)
        running = True
        while running:

            # 判断是否达到次数
            if max_time > 0 and current_time >= max_time:
                self.log_info("达到最大循环次数")
                running = False
                break

            # 逻辑
            self.one_time()

            # 完成一次后计数
            current_time += 1

            self.log_info(
                f"当前次数: {current_time}/{max_time}"
            )

            self.sleep(0.1)


    def one_time(self):
        self.wait_until(
            lambda: self.ocr(0.03, 0.17, 0.15, 0.80, match=re.compile("黑暗赛车")),
            pre_action=lambda: self.send_key("f4", action_name="dark_racing", interval=2),
            time_out=30,
            raise_if_not_found=True,
        )

        btn = self.wait_ocr(
            0.03, 0.17, 0.15, 0.80, match=re.compile("黑暗赛车"), time_out=60, raise_if_not_found=True
        )

        self.wait_until(
            lambda: self.ocr(0.81, 0.91, 0.94, 0.97, match=re.compile("开始比赛")),
            pre_action=lambda: self.operate_click(btn, action_name="dark_racing", interval=1),
            time_out=30,
            raise_if_not_found=True,
        )

        self.wait_until(
            lambda: not self.ocr(0.03, 0.17, 0.15, 0.80, match=re.compile("黑暗赛车")),
            pre_action=lambda: self.operate_click(0.8995, 0.9546, interval=1),
            time_out=30,
            raise_if_not_found=True,
        )
        self.go()
        while not self.ocr(x=0.7839, y=0.8769, to_x=0.9792, to_y=0.9806, match=re.compile(r'.*?\((\d+)\).*')):
            self.sleep(1)
        self.operate_click(0.8995, 0.9546, after_sleep=1)
        while not self.in_world():
            self.sleep(1)
    
    def go(self):
        start_time = time.time()
        try:
            while True:
                elapsed = time.time() - start_time

                # 剩余时间
                remain = 150 - elapsed

                if remain <= 0:
                    break

                self.send_key_down('w')
                self.send_key('space')
                self.sleep(1)
        finally:
            self.send_key_up('w')
