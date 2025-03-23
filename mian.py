import pyautogui as pg
import cv2 as cv
import numpy as np
import time
import sys
import platform
import ctypes
import re
import threading
from subprocess import check_output

fish_leavel = 3;

def fish_swicth():
    if fish_leavel == 1:
        return 0.05
    elif fish_leavel == 2:
        return 0.06
    elif fish_leavel == 3:
        return 0.065
    else:
        return 0.05

class ScreenScaler:
    @staticmethod
    def get_scaling_factor():
        """获取系统缩放比例（返回倍数，如2.0表示200%缩放）"""
        system = platform.system()

        if system == "Windows":
            user32 = ctypes.windll.user32
            hwnd = user32.GetDesktopWindow()
            dc = user32.GetDC(hwnd)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
            user32.ReleaseDC(hwnd, dc)
            return dpi / 96.0

        elif system == "Darwin":
            from AppKit import NSScreen
            return NSScreen.mainScreen().backingScaleFactor()

        else:
            try:
                output = check_output(["xrandr"]).decode()
                match = re.search(
                    r"connected.*?(\d+)x(\d+)\+(\d+)\+(\d+)", output)
                if match:
                    physical_width = int(match.group(1))
                    logical_width = int(check_output(["xdpyinfo"]).decode().split(
                        "dimensions:")[1].split("pixels")[0].split("x")[0].strip())
                    return physical_width / logical_width
            except:
                pass
            return 1.0


def get_xy(img_model_path, img=None):
    scaler = ScreenScaler()
    scale_factor = scaler.get_scaling_factor()

    if img is None:
        screenshot = pg.screenshot()
        screen_img = cv.cvtColor(np.array(screenshot), cv.COLOR_RGB2GRAY)
    else:
        screen_img = img.copy()

    template = cv.imread(img_model_path, cv.IMREAD_GRAYSCALE)
    if template is None:
        print("错误：模板图片未正确加载！")
        return None

    h, w = template.shape
    scales = [0.8, 1.0, 1.2, 1.5]
    found = None

    for scale in scales:
        scaled_w = int(w * scale)
        scaled_h = int(h * scale)
        if scaled_w < 20 or scaled_h < 20:
            continue

        resized = cv.resize(template, (scaled_w, scaled_h))
        res = cv.matchTemplate(screen_img, resized, cv.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv.minMaxLoc(res)

        if found is None or max_val > found[0]:
            found = (max_val, max_loc, scaled_w, scaled_h)

    if not found or found[0] < 0.4:
        print(f"匹配失败，最高置信度：{found[0] if found else 0:.2f}")
        return None

    max_loc, rw, rh = found[1], found[2], found[3]
    center_x = max_loc[0] + rw // 2
    center_y = max_loc[1] + rh // 2

    return (
        int(center_x / scale_factor),
        int(center_y / scale_factor)
    )


def auto_click(center):
    if center:
        try:
            screen_w, screen_h = pg.size()
            if 0 <= center[0] <= screen_w and 0 <= center[1] <= screen_h:
                pg.moveTo(center[0], center[1])
                pg.click()
                return True
            print(f"坐标越界：{center}")
            return False
        except pg.FailSafeException:
            print("安全保护触发！")
            return False
    return False


def swipe_up(center):
    if center:
        try:
            screen_w, screen_h = pg.size()
            if not (0 <= center[0] <= screen_w and 0 <= center[1] <= screen_h):
                print(f"坐标越界：{center}")
                return False

            target_y = max(center[1] - 70, 0)
            pg.moveTo(center[0], center[1], duration=0.1)
            pg.dragTo(center[0], target_y, duration=0.15, button='left')
            time.sleep(fish_swicth())
            return True
        except pg.FailSafeException:
            print("安全保护触发！")
            return False
    return False


def click_worker(pos, stop_event):
    """持续点击的工作线程"""
    while not stop_event.is_set():
        auto_click(pos)
        time.sleep(0.01)  # 防止过高CPU占用


def swipe_worker(pos, stop_event):
    """持续滑动的工作线程"""
    while not stop_event.is_set():
        swipe_up(pos)
        time.sleep(0.1)


def execute_step(step_config, max_attempts=10):
    """支持并发点击的版本"""
    if step_config.get("persistent"):
        print(f"进入持续模式 [{step_config['name']}]")
        stop_event = threading.Event()
        threads = []
        NUM_WORKERS = 5  # 并发线程数

        try:
            # 初始定位
            time.sleep(3)
            initial_pos = get_xy(step_config["image_path"])
            if not initial_pos:
                print("初始目标未找到，退出持续模式")
                return False

            # 根据动作类型选择工作函数
            worker_func = click_worker if step_config["action"] == "continuous_click" else swipe_worker

            while True:
                # 启动工作线程
                stop_event.clear()
                threads = [threading.Thread(target=worker_func, args=(initial_pos, stop_event))
                           for _ in range(NUM_WORKERS)]
                for t in threads:
                    t.start()

                # 持续执行4秒
                start_time = time.time()
                while time.time() - start_time < 4:
                    time.sleep(0.05)

                # 停止当前批次线程
                stop_event.set()
                for t in threads:
                    t.join()

                # 验证目标状态
                check_pos = get_xy(step_config["image_path"])
                if not check_pos:
                    print("目标已消失，结束持续模式")
                    return True
                else:
                    print(f"坐标更新：{check_pos}")
                    initial_pos = check_pos

        except KeyboardInterrupt:
            print("用户主动终止")
            stop_event.set()
            for t in threads:
                t.join()
            return False
        except Exception as e:
            print(f"持续模式异常：{str(e)}")
            stop_event.set()
            for t in threads:
                t.join()
            return False
        finally:
            stop_event.set()
            for t in threads:
                t.join()

    # 普通模式（保持原样）
    screenshot = pg.screenshot()
    cached_img = cv.cvtColor(np.array(screenshot), cv.COLOR_RGB2GRAY)

    for _ in range(max_attempts):
        pos = get_xy(step_config["image_path"], cached_img)
        if pos:
            print(f"已定位到 [{step_config['name']}]，坐标: {pos}")
            if step_config["action"] == "click":
                auto_click(pos)
            elif step_config["action"] == "swipe":
                swipe_up(pos)
            return True
        time.sleep(0.05)

    pos = get_xy(step_config["image_path"])
    if pos:
        print(f"最终定位到 [{step_config['name']}]")
        if step_config["action"] == "click":
            auto_click(pos)
        elif step_config["action"] == "swipe":
            swipe_up(pos)
        return True

    print(f"未找到 [{step_config['name']}]，跳过...")
    return False


# 流程配置保持不变
workflow = [
    {"name": "百趣闲市", "image_path": "./pic/百趣闲市.png", "action": "click"},
    {"name": "阿超钓鱼", "image_path": "./pic/阿超钓鱼.png", "action": "click"},
    {"name": "开始钓鱼", "image_path": "./pic/开始钓鱼.png", "action": "click"},
    {"name": "抛竿", "image_path": "./pic/抛竿.png", "action": "swipe"},
    {"name": "提竿", "image_path": "./pic/提竿.png", "action": "click"},
    {"name": "收线", "image_path": "./pic/收线.png",
        "action": "continuous_click", "persistent": True},
    {"name": "再钓一次", "image_path": "./pic/再钓一次.png", "action": "click"},
]


def main():
    while True:  # 外层无限循环
        current_step = 0
        cycle_start_time = time.time()
        print("\n" + "="*40 + "\n开始新循环流程\n" + "="*40)

        while current_step < len(workflow):
            step = workflow[current_step]
            print(f"\n正在执行步骤 {current_step+1}/{len(workflow)}: {step['name']}")

            success = execute_step(step)

            # 成功执行后的处理
            if success:
                if step.get("persistent"):
                    current_step += 1  # 持续模式执行完后直接下一步
                else:
                    current_step += 1
                    time.sleep(1)  # 正常步骤间隔
            # 执行失败的处理
            else:
                found = False
                # 尝试后续步骤作为备选
                for next_step in range(current_step+1, len(workflow)):
                    if execute_step(workflow[next_step], max_attempts=2):
                        current_step = next_step
                        found = True
                        break
                if not found:
                    print("⚠️ 未找到后续可执行步骤，提前重启流程")
                    break  # 跳出当前循环直接重启

            # 防止单次循环时间过长（超过10分钟强制重启）
            if time.time() - cycle_start_time > 600:
                print("⏰ 单次循环超时，强制重启流程")
                break

        # 循环间隔时间（包含在超时判断中）
        restart_delay = 2
        print(f"\n🌀 准备重启流程，等待 {restart_delay} 秒...")
        for remaining in range(restart_delay, 0, -1):
            print(f"\r倒计时: {remaining} 秒  ", end="")
            time.sleep(1)
        print("\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🚫 用户主动终止程序")
