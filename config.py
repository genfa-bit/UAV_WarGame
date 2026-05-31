"""项目全局配置。

本文件集中保存窗口尺寸、颜色、仿真速度等常量，便于后续调整。
"""

# ── 屏幕 / 地图尺寸 ──────────────────────────────────────────
DEFAULT_SCREEN_WIDTH = 1000
DEFAULT_SCREEN_HEIGHT = 600
BATTLEFIELD_W = 800          # 战场逻辑宽度（固定不变）
BATTLEFIELD_H = 600          # 战场逻辑高度（固定不变）
MAP_RATIO = 0.78             # 地图区域占屏幕宽的比例

# ── 仿真参数 ──────────────────────────────────────────────────
FPS = 60
SIMULATION_INTERVAL_MS = 220

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

# ── 单位状态常量（内部逻辑用英文，显示用 STATUS_LABELS）─────
STATUS_SCOUT = "Scout"
STATUS_MOVE = "Move"
STATUS_ATTACK = "Attack"
STATUS_EVADE = "Evade"
STATUS_DESTROYED = "Destroyed"

STATUS_LABELS = {
    "Scout": "侦察",
    "Move": "机动",
    "Attack": "攻击",
    "Evade": "规避",
    "Destroyed": "已摧毁",
}

UNIT_TYPE_LABELS = {
    "scout_drone": "侦察无人机",
    "strike_drone": "打击无人机",
    "ground_vehicle": "无人战车",
    "missile_vehicle": "导弹发射车",
    "command_node": "指挥节点",
}

OBSTACLE_TYPE_LABELS = {
    "mountain": "山地",
    "building": "建筑",
    "restricted": "禁行区",
}

STATE_LABELS = {
    "deployment": "部署阶段",
    "running": "运行中",
    "paused": "已暂停",
    "finished": "已结束",
}

MODE_LABELS = {
    "preset": "预设部署",
    "manual": "手动部署",
}

# ── 对象放置参数 ──────────────────────────────────────────────
MIN_UNIT_DISTANCE = 14
MIN_OBSTACLE_SIZE = 12
MIN_BASE_DISTANCE = 50       # 基地之间 / 基地与单位的最小距离
RESIZE_HANDLE = 12
DRAG_THRESHOLD = 3
_BASE_HIT_RADIUS = 20

# ── 检测 / 威胁 / 状态 ───────────────────────────────────────
DETECTION_TIMEOUT_STEPS = 8

THREAT_VALUE_BY_TYPE = {
    "scout_drone": 2,
    "strike_drone": 4,
    "ground_vehicle": 5,
    "missile_vehicle": 6,
    "command_node": 8,
}


class SimState:
    DEPLOYMENT = "deployment"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


GAME_DEPLOYMENT = SimState.DEPLOYMENT
GAME_RUNNING = SimState.RUNNING
GAME_PAUSED = SimState.PAUSED
GAME_FINISHED = SimState.FINISHED

DEPLOY_PRESET = "preset"
DEPLOY_MANUAL = "manual"

FULLSCREEN = False

UNIT_RADIUS = 10
COMMAND_SIZE = 18
