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
MAX_SIMULATION_STEPS = 1200  # 教学演示上限；到上限仍未分胜负时按剩余战力裁定
MIN_STEP_DURATION_SECONDS = 0.01
MAX_STEP_DURATION_SECONDS = 60.0
# Complete journals are retained in memory and atomically rewritten.  Keep the
# public limit bounded until the journal is migrated to incremental storage.
MAX_CONFIGURABLE_STEPS = 10_000
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
# 血条底槽按阵营区分，与单位阵营色配套使用。
HP_TRACK_RED = (74, 28, 34)
HP_TRACK_BLUE = (22, 48, 79)
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
    "replay": "回放中", "replay_paused": "回放暂停",
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
UNIT_SEPARATION_DISTANCE = 12.0  # 单位间最小间距，低于此值逐步推开
UNIT_SEPARATION_PUSH = 2.0    # 每帧最多推开的距离
COMM_DELAY_FACTOR = 0.15      # 通信延迟系数（步/像素距离）

# ── 协同动态边际拍卖（RDMA）────────────────────────────────────
# 以下缺省值仅用于配置缺项/非法值兜底；实际运行参数以
# data/unit_config.json 的 cooperative_assignment 段为准。
CRIT_CHANCE = 0.1
CRIT_DAMAGE_MULTIPLIER = 1.5
BASE_DEFENSE_RADIUS = 250.0
EVADE_ATTACK_RANGE_FACTOR = 0.55
MIN_ASSIGNMENT_DEMAND = 1

COOPERATIVE_ROLE_FIT_DEFAULTS = {
    "scout_drone": {
        "scout_drone": 0.70, "strike_drone": 0.55, "ground_vehicle": 0.45,
        "missile_vehicle": 0.55, "command_node": 0.35, "base": 0.30,
    },
    "strike_drone": {
        "scout_drone": 0.95, "strike_drone": 0.65, "ground_vehicle": 0.75,
        "missile_vehicle": 0.70, "command_node": 0.80, "base": 0.95,
    },
    "ground_vehicle": {
        "scout_drone": 0.55, "strike_drone": 0.65, "ground_vehicle": 0.85,
        "missile_vehicle": 0.75, "command_node": 0.70, "base": 0.75,
    },
    "missile_vehicle": {
        "scout_drone": 0.40, "strike_drone": 0.65, "ground_vehicle": 0.80,
        "missile_vehicle": 0.70, "command_node": 0.95, "base": 1.00,
    },
    "command_node": {
        "scout_drone": 0.40, "strike_drone": 0.40, "ground_vehicle": 0.40,
        "missile_vehicle": 0.40, "command_node": 0.40, "base": 0.00,
    },
    "base": {
        "scout_drone": 0.40, "strike_drone": 0.40, "ground_vehicle": 0.40,
        "missile_vehicle": 0.40, "command_node": 0.40, "base": 0.00,
    },
}

COOPERATIVE_ASSIGNMENT_DEFAULTS = {
    "enabled": True,
    "replan_interval_steps": 5,
    "max_assignments_per_target": 3,
    "min_assignment_bid": 0.05,
    "switch_penalty": 0.10,
    "reassign_margin": 0.12,
    "overload_penalty": 0.12,
    "demand_horizon_steps": 10,
    # 效果型 WTA：F_j(D)=min(1, D/(q_j*H_j))。q_j 默认 1.0，
    # 保持原有“覆盖当前血量”的行为；基地固定为 1.0，必须被摧毁。
    "desired_effect_by_type": {
        "scout_drone": 1.0, "strike_drone": 1.0, "ground_vehicle": 1.0,
        "missile_vehicle": 1.0, "command_node": 1.0, "base": 1.0,
    },
    "marginal_utility_weight": 1.0,
    "effect_overkill_penalty": 0.25,
    "ammo_cost_weight": 0.02,
    "overkill_release_ratio": 1.20,
    # 基地作为战略目标：独立价值、打击包上限/下限与承诺窗口。
    "base_target_value": 0.90,
    "late_game_bonus": 0.50,
    "late_game_unit_threshold": 2,
    "base_max_assignments": 2,
    "base_min_assignments": 1,
    "base_commitment_steps": 8,
    "target_priority_weights": {
        "type_threat": 0.65, "low_hp": 0.35, "base_bonus": 0.15,
    },
    "unit_readiness_weights": {"health": 0.60, "ammo": 0.40},
    "bid_weights": {
        "target_priority": 0.40, "role_fit": 0.25, "readiness": 0.20,
        "freshness": 0.15, "distance_cost": 0.20,
    },
    "role_fit": COOPERATIVE_ROLE_FIT_DEFAULTS,
}


class SimState:
    DEPLOYMENT = "deployment"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    # 回放：replay 表示正在播放，replay_paused 表示停住等操作。
    REPLAY = "replay"
    REPLAY_PAUSED = "replay_paused"


GAME_DEPLOYMENT = SimState.DEPLOYMENT
GAME_RUNNING = SimState.RUNNING
GAME_PAUSED = SimState.PAUSED
GAME_FINISHED = SimState.FINISHED
GAME_REPLAY = SimState.REPLAY
GAME_REPLAY_PAUSED = SimState.REPLAY_PAUSED
GAME_REPLAY_STATES = (GAME_REPLAY, GAME_REPLAY_PAUSED)

UNIT_RADIUS = 10
COMMAND_SIZE = 18
