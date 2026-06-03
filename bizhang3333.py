#!/usr/bin/python3
# coding=utf8
import os
import random
import sys
import time
import math
import threading
import numpy as np
import hiwonder.ros_robot_controller_sdk as rrc
from hiwonder.Controller import Controller
import hiwonder.Sonar as Sonar
import hiwonder.ActionGroupControl as AGC

try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

debug=False

if sys.version_info.major == 2:
    print('Please run this program with python3!')
    sys.exit(0)

board = rrc.Board()
ctl = Controller(board)


def hand_up():
    ctl.set_bus_servo_pulse(8, 330, 1000)
    time.sleep(0.3)
    ctl.set_bus_servo_pulse(7, 860, 1000)
    ctl.set_bus_servo_pulse(6, 860, 1000)
    time.sleep(1)


def hand_down():
    ctl.set_bus_servo_pulse(7, 800, 1000)
    ctl.set_bus_servo_pulse(6, 575, 1000)
    time.sleep(0.3)
    ctl.set_bus_servo_pulse(8, 725, 1000)
    time.sleep(1)


# 状态控制变量
current_step = 1
obstacle_count = 1
distance = 99999  # 单位：mm
goforward = 0

# 跌倒检测相关变量
fall_recovery_in_progress = False  # 跌倒恢复中标志
screen_black = False  # 屏幕全黑标志
ULTRASONIC_FALL_THR = 50  # 超声波跌倒判定阈值（mm），极近距离视为跌倒
BLACK_SCREEN_THR = 100  # 屏幕全黑判定阈值（像素数），低于此值视为全黑

# 新增线程锁与视觉共享变量
distance_lock = threading.Lock()
img_lock = threading.Lock()
IMG_CENTER_X = 320
img_centerx = IMG_CENTER_X  # -1 表示未检测到线

# 视觉线程：检测赛道线中心（基于简单阈值）
def vision_loop():
    global img_centerx, screen_black
    if not CV2_AVAILABLE:
        # 无OpenCV时，模拟双边界线中间位置（固定320）
        while True:
            with img_lock:
                img_centerx = IMG_CENTER_X
                screen_black = False
            time.sleep(0.05)
        return
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        print("摄像头打开失败，使用默认值")
        while True:
            with img_lock:
                img_centerx = IMG_CENTER_X
                screen_black = False
            time.sleep(0.05)
        return
    # 新增：轮廓筛选参数（可根据实际赛道调整）
    MIN_CONTOUR_AREA = 500  # 最小轮廓面积（排除噪点，和原逻辑一致）
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("摄像头读取失败")
                time.sleep(0.02)
                continue
            # 1. 截取底部1/3 ROI（和原逻辑一致）
            h, w = frame.shape[:2]
            roi = frame[int(h * 0.66):h, 0:w]
            # 2. LAB颜色空间+阈值过滤（提取白色赛道线，和原逻辑一致）
            lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
            lower = np.array([189, 0, 0])
            upper = np.array([255, 255, 255])
            mask = cv2.inRange(lab, lower, upper)
            # 3. 形态学去噪（和原逻辑一致）
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            # 4. 检测屏幕是否完全变黑
            white_pixels = cv2.countNonZero(mask)
            with img_lock:
                screen_black = white_pixels < BLACK_SCREEN_THR
            # -------------------------- 新增/修改部分 --------------------------
            # 4. 查找所有轮廓（而非单个最大轮廓）
            contours, _ = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # 筛选：只保留面积≥MIN_CONTOUR_AREA的轮廓（排除噪点）
            valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) >= MIN_CONTOUR_AREA]
            with img_lock:
                if len(valid_contours) >= 2:
                    # 5. 按轮廓的“左边界x坐标”排序（区分左右线）
                    # 计算每个轮廓的左边界x坐标（boundingRect的x值）
                    valid_contours.sort(key=lambda cnt: cv2.boundingRect(cnt)[0])
                    left_contour = valid_contours[0]  # 最左的轮廓=左赛道线
                    right_contour = valid_contours[-1]  # 最右的轮廓=右赛道线
                    # 6. 分别计算左右轮廓的质心x坐标
                    m_left = cv2.moments(left_contour)
                    m_right = cv2.moments(right_contour)
                    if m_left['m00'] > 0 and m_right['m00'] > 0:
                        x1 = int(m_left['m10'] / m_left['m00'])  # 左线质心x
                        x2 = int(m_right['m10'] / m_right['m00'])  # 右线质心x
                        # 7. 赛道中心 = 左右线质心的中间位置（核心修改）
                        img_centerx = (x1 + x2) // 2  # 取整数像素（避免浮点数）
                    else:
                        img_centerx = -1  # 质心计算失败，视为未检测到线
                elif len(valid_contours) == 1:
                    # 只找到一条线，降级为单条线巡线（避免失控）
                    m = cv2.moments(valid_contours[0])
                    img_centerx = int(m['m10'] / m['m00']) if m['m00'] > 0 else -1
                else:
                    img_centerx = -1  # 没找到任何有效轮廓，视为未检测到线
            # ------------------------------------------------------------------
            time.sleep(0.02)
    finally:
        cap.release()
        cv2.destroyAllWindows()


def move():
    global current_step, obstacle_count, distance, goforward, fall_recovery_in_progress

    DIST_OBSTACLE_MM = 400
    LINE_OFFSET_THR = 90

    while True:
        # 优先检查是否跌倒，若跌倒则进行恢复
        with distance_lock:
            local_distance = distance
        with img_lock:
            local_imgx = img_centerx
            local_screen_black = screen_black
            
        # 跌倒判定条件：屏幕全黑 AND 超声波极近距离
        if local_screen_black and local_distance < ULTRASONIC_FALL_THR:
            # 如果已经在恢复中，则跳过
            if not fall_recovery_in_progress:
                print("检测到跌倒，开始自动起立...")
                fall_recovery_in_progress = True
                try:
                    # 执行起立动作
                    AGC.runActionGroup('stand_up_front')
                    print("起立动作完成")
                    # 重置状态
                    fall_recovery_in_progress = False
                    current_step = 1
                    goforward = 0
                except Exception as e:
                    print(f"起立动作执行失败: {e}")
                    fall_recovery_in_progress = False
            time.sleep(0.1)
            continue

        if current_step == 1:
            if local_distance <= DIST_OBSTACLE_MM:
                obstacle_count += 1
                print(f"检测到第{obstacle_count}个障碍物, 距离={local_distance}mm")
                current_step = 2 if obstacle_count % 2 == 1 else 3
                time.sleep(0.05)
                continue

            if local_imgx == -1:
                print("未检测到线，缓慢搜索")
                AGC.runActionGroup('turn_left')
                time.sleep(0.15)
            else:
                offset = local_imgx - IMG_CENTER_X
                print(f"巡线: 线心={local_imgx}, 偏移={offset}, 距离={local_distance}mm")
                if abs(offset) <= LINE_OFFSET_THR:
                    AGC.runActionGroup('zhixing2')
                    print("直行")
                    goforward += 1
                elif offset > LINE_OFFSET_THR:
                    AGC.runActionGroup('turn_right')
                    print("右调")
                    goforward = 0
                else:
                    AGC.runActionGroup('turn_left')
                    print("左调")
                    goforward = 0

            time.sleep(0.08)

        elif current_step == 2:
            print("避障流程 2: 规避（执行右移+前进）")
            for _ in range(5):
                AGC.runActionGroup('turn_right')
                time.sleep(0.18)
            for _ in range(8):
                AGC.runActionGroup('zhixing2')
                time.sleep(0.18)
            current_step = 4
            goforward = 0

        elif current_step == 3:
            print("避障流程 3: 规避（执行左移+前进）")
            for _ in range(6):
                AGC.runActionGroup('turn_left')
                time.sleep(0.18)
            for _ in range(8):
                AGC.runActionGroup('go_forward_fast')
                time.sleep(0.18)
            current_step = 5
            goforward = 0

        elif current_step == 4:
            for _ in range(3):
                AGC.runActionGroup('turn_left')
                time.sleep(0.18)
            current_step = 1

        elif current_step == 5:
            for _ in range(4):
                AGC.runActionGroup('turn_right')
                time.sleep(0.18)
            current_step = 1

        else:
            time.sleep(0.1)


# 启动线程：移动逻辑与视觉采集
th_move = threading.Thread(target=move)
th_move.daemon = True
th_move.start()

th_vision = threading.Thread(target=vision_loop)
th_vision.daemon = True
th_vision.start()

if __name__ == "__main__":
    distance_list = []
    s = Sonar.Sonar()
    s.startSymphony()

    AGC.runActionGroup('stand_slow')
    time.sleep(1)


    try:
        while True:
            # 读取超声波并平滑
            distance_list.append(s.getDistance())
            if len(distance_list) >= 6:
                with distance_lock:
                    distance = int(round(np.mean(np.array(distance_list))))
                    print(distance, 'mm')
                    distance_list = []
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("程序中断，清理并退出")
        if CV2_AVAILABLE:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        # 可在此处添加资源释放

