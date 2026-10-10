"""项目全局配置。"""

# ── 屏幕 / 地图尺寸 ──────────────────────────────────────────
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 600
MAP_WIDTH = 800
MAP_HEIGHT = 600
PANEL_WIDTH = SCREEN_WIDTH - MAP_WIDTH

# ── 仿真参数 ──────────────────────────────────────────────────
FPS = 60
SIMULATION_INTERVAL_MS = 220
MAX_SIMULATION_STEPS = 2000  # 教学演示上限，持续僵持时以平局结束
MIN_STEP_DURATION_SECONDS = 0.01
MAX_STEP_DURATION_SECONDS = 60.0
MAX_CONFIGURABLE_STEPS = 1_000_000
SIM_SPEED_LEVELS = [
    ("1x", 220),
    ("2x", 110),
    ("4x", 55),
    ("MAX", 0),
]

# ── 颜色常量 ──────────────────────────────────────────────────
BACKGROUND_COLOR = (22, 26, 32)
GRID_COLOR = (43, 49, 58)
OBSTACLE_COLOR = (88, 92, 99)
RED_COLOR = (220, 72, 72)
BLUE_COLOR = (72, 132, 220)
TEXT_COLOR = (235, 238, 245)
PANEL_BG = (32, 37, 45)
HP_GREEN = (80, 210, 120)
HP_RED = (230, 70, 70)
DETECT_RED = (255, 100, 100, 42)
DETECT_BLUE = (100, 150, 255, 42)
ATTACK_EFFECT_COLOR = (255, 215, 95)

TEAM_RED = "red"
TEAM_BLUE = "blue"

# ── 单位状态常量 ──────────────────────────────────────────────
STATUS_SCOUT = "Scout"
STATUS_MOVE = "Move"
STATUS_ATTACK = "Attack"
STATUS_EVADE = "Evade"
STATUS_DESTROYED = "Destroyed"

STATUS_LABELS = {
    "Scout": "侦察", "Move": "机动", "Attack": "攻击",
    "Evade": "规避", "Destroyed": "已摧毁",
}

UNIT_TYPE_LABELS = {
    "scout_drone": "侦察无人机", "strike_drone": "打击无人机",
    "ground_vehicle": "无人战车", "missile_vehicle": "导弹发射车",
    "command_node": "指挥节点", "base": "基地",
}

OBSTACLE_TYPE_LABELS = {
    "mountain": "山地", "building": "建筑", "restricted": "禁行区",
}

STATE_LABELS = {
    "deployment": "部署阶段", "running": "运行中",
    "paused": "已暂停", "finished": "已结束",
}

# ── 对象放置参数 ──────────────────────────────────────────────
MIN_UNIT_DISTANCE = 14
MIN_OBSTACLE_SIZE = 12
MIN_BASE_DISTANCE = 50
RESIZE_HANDLE = 12
DRAG_THRESHOLD = 3
_BASE_HIT_RADIUS = 20

# ── 检测 / 威胁 ──────────────────────────────────────────────
DETECTION_TIMEOUT_STEPS = 8

THREAT_VALUE_BY_TYPE = {
    "scout_drone": 2, "strike_drone": 4, "ground_vehicle": 5,
    "missile_vehicle": 6, "command_node": 8, "base": 10,
}

# ── 第八阶段：威胁 / 态势 / 行为 / 卡死检测 ──────────────────
BASE_THREAT_SCORE = {
    "scout_drone": 30, "strike_drone": 80, "ground_vehicle": 60,
    "missile_vehicle": 100, "command_node": 20, "base": 200,
}
STRENGTH_ATTACK_WEIGHT = 0.4
STRENGTH_HP_WEIGHT = 0.4
STRENGTH_AMMO_WEIGHT = 0.2
SITUATION_ADVANTAGE_RATIO = 1.5
SITUATION_DISADVANTAGE_RATIO = 0.8
STUCK_THRESHOLD = 6          # 连续N帧位移<3px视为卡死
STUCK_MOVE_DELTA = 3.0       # 卡死判定最小位移
TARGET_LOCK_TIME = 5          # 目标锁定帧数
BASE_MAX_HP = 300             # 基地最大血量
BASE_REPAIR_RADIUS = 80       # 基地补给半径
BASE_REPAIR_PER_STEP = 4      # 每帧补给量（血量+弹药）
COMM_DELAY_FACTOR = 0.15      # 通信延迟系数（步/像素距离）


class SimState:
    DEPLOYMENT = "deployment"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


GAME_DEPLOYMENT = SimState.DEPLOYMENT
GAME_RUNNING = SimState.RUNNING
GAME_PAUSED = SimState.PAUSED
GAME_FINISHED = SimState.FINISHED

UNIT_RADIUS = 10
COMMAND_SIZE = 18
