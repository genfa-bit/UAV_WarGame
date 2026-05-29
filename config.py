"""项目全局配置。

本文件集中保存窗口尺寸、颜色、仿真速度等常量，便于后续调整。
"""

SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 600
MAP_WIDTH = 800
MAP_HEIGHT = 600
PANEL_WIDTH = SCREEN_WIDTH - MAP_WIDTH

FPS = 60
SIMULATION_INTERVAL_MS = 220

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

STATUS_SCOUT = "Scout"
STATUS_MOVE = "Move"
STATUS_ATTACK = "Attack"
STATUS_EVADE = "Evade"
STATUS_DESTROYED = "Destroyed"

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

UNIT_RADIUS = 10
COMMAND_SIZE = 18
