# 无人装备战争游戏仿真系统

基于 Python + PySide6/QML 的二维无人装备对抗仿真系统。系统通过抽象规则展示自主侦察、协同集火、战术规避、战斗统计和胜负判断，全部参数为仿真抽象值，不涉及真实军事数据。

## 前端说明

- 默认前端为 `PySide6 + QML` 现代战术指挥台，入口 `main.py` → `ui/qt_app.py`。
- `core/controller.py` 提供前端无关的生命周期命令和可序列化快照。
- `ui/qt_models.py` 负责 QML ViewModel、单位列表模型和自动推进定时器。
- `ui/qml/Main.qml` 提供战场、部署编辑、运行控制、统计和日志界面。
- 原 Pygame 前端保留在 `pygame_main.py`，用于兼容和回归验证。

## 功能列表

- 二维战场地图，地图区域和信息面板分离。
- JSON 场景配置，支持基地、地形、障碍物和初始单位。
- 支持空中、地面、指挥节点三类平台和 5 个具体兵种。
- 启动后先进入部署阶段，支持预设开局和手动部署。
- 红蓝双方每个时间步自动侦察敌方单位。
- 按阵营维护共享目标池：红方发现目标、蓝方发现目标。
- 每个阵营根据共享目标池选择当前集火目标。
- 集火规则：低生命值优先；生命值相同则距离己方平均位置更近者优先。
- 低血量、弹药耗尽或敌人过近时进入 Evade。
- Evade 状态下远离最近可见敌人；无可见敌人时撤回己方基地。
- 攻击消耗弹药、造成伤害，并输出攻击日志。
- 显示单位、指挥节点、基地、障碍物、探测范围、血条、状态和攻击连线。
- 信息面板显示时间步、剩余单位、摧毁数量、发现目标数、集火目标、运行状态和胜负结果。
- 威胁评估与优先级目标排序，目标锁定避免频繁切换。
- 战场态势感知（战力/态势/战术），兵种角色智能化。
- 统一行为决策管理器，卡死检测与路径恢复。
- 兵种战斗属性 JSON 配置化（data/unit_config.json）。
- F 键仿真加速：1x / 2x / 4x / MAX 四档速度切换。
- 简化交战状态机（SEARCH → REACTING → ATTACK → COOLDOWN），每单位独立维护攻击时序。
- 反应延迟与攻击冷却采用随机范围取值，消除“先发现→先攻击→绝对优势”问题。
- 攻击意图队列 + 同步伤害结算，帧内所有攻击统一结算，消除执行顺序先手优势。
- 动态命中概率（距离/速度/状态/掩体遮挡四因子），含 Liang-Barsky 射线-矩形相交检测。
- 多目标探测时反应进度不回退，避免多敌互现导致永不攻击。

## 目录结构

```text
UAV_WarGame/
├── main.py                 # 默认入口：启动 PySide6/QML 前端
├── pygame_main.py          # 旧 Pygame 前端入口
├── config.py               # 全局配置，如窗口尺寸、颜色、状态常量
├── requirements.txt        # 项目依赖
├── pytest.ini              # pytest 配置（pythonpath = .）
├── UAV_WarGame.spec        # PyInstaller 打包配置
├── README.md               # 项目说明
├── core/
│   ├── controller.py       # 前端无关的仿真控制器与快照
│   ├── battlefield.py      # 战场、障碍物、基地和地形信息
│   ├── simulator.py        # 仿真流程主控
│   ├── entity.py           # 实体基础类
│   ├── units.py            # 五类兵种单位定义
│   ├── strategy.py         # 侦察、集火目标选择、规避和移动策略
│   ├── combat.py           # 攻击范围、弹药、伤害和攻击事件
│   ├── target_pool.py      # 阵营共享目标池
│   ├── scenario_loader.py  # JSON 场景加载
│   ├── unit_factory.py     # 兵种工厂
│   ├── deployment.py       # 部署阶段管理
│   ├── obstacle_editor.py  # 地图编辑器（障碍物+基地拖动）
│   ├── map_persistence.py  # 地图保存与加载
│   ├── behavior.py         # 统一行为决策管理器
│   ├── threat.py           # 威胁评估与态势感知
│   ├── pathfinding.py      # 地面绕障路径规划（Bug2 算法）
│   ├── engagement.py       # 简化交战状态机（反应延迟+冷却+反先手）
│   └── unit_config_loader.py # 兵种配置加载器
├── ui/
│   ├── qt_app.py           # PySide6 应用引导，加载 QML
│   ├── qt_models.py        # QML ViewModel 与单位模型
│   ├── qml/Main.qml        # 主界面
│   ├── assets/             # 单位与障碍物图标
│   ├── renderer.py         # Pygame 前端绘制
│   └── panel.py            # Pygame 前端右侧信息面板
├── data/
│   ├── scenario_1.json     # 预设场景数据
│   ├── saved_map.json      # 保存的地图（运行时生成）
│   └── unit_config.json    # 兵种战斗属性配置
├── tests/                  # pytest 测试用例
└── docs/                   # 需求、设计、测试与验收文档
```

## 环境要求

- Python 3.10 或以上版本（当前验证环境为 3.11.17）
- 推荐使用 Anaconda 专用环境 `uav_wargame`
- 当前推荐解释器：`D:\conda_envs\uav_wargame\python.exe`
- 当前环境已验证版本：PySide6 6.12.0、pygame 2.6.1
- 不建议使用 base；也不建议使用 Python 3.14 环境安装 Pygame

## 安装依赖

在项目根目录执行：

```powershell
cd D:\应用综合实验\UAV_WarGame
conda activate uav_wargame
pip install -r requirements.txt
```

如果终端没有初始化 conda，可以直接指定解释器（无需 activate）：

```powershell
cd D:\应用综合实验\UAV_WarGame
& "D:\conda_envs\uav_wargame\python.exe" -m pip install -r requirements.txt
```

依赖内容（`requirements.txt`）：

```text
pygame>=2.5.0
PySide6>=6.8,<7
pytest>=8.0.0
```

## 运行方法

所有命令都需要先进入项目根目录：

```powershell
cd D:\应用综合实验\UAV_WarGame
```

### 1. 运行默认前端（PySide6 + QML，推荐）

```powershell
python main.py
```

未初始化 conda 时直接指定解释器：

```powershell
& "D:\conda_envs\uav_wargame\python.exe" main.py
```

也可以在任意目录用绝对路径启动：

```powershell
& "D:\conda_envs\uav_wargame\python.exe" "D:\应用综合实验\UAV_WarGame\main.py"
```

注意：`main.py` 依赖相对包结构（`core`、`ui`），用绝对路径启动时请确保工作目录或 `pythonpath` 能定位到项目根目录，否则建议先 `cd` 到项目根目录。

### 2. 运行旧 Pygame 前端

```powershell
python pygame_main.py
```

或：

```powershell
& "D:\conda_envs\uav_wargame\python.exe" pygame_main.py
```

### 3. 运行测试

运行全部测试：

```powershell
pytest
```

或指定解释器：

```powershell
& "D:\conda_envs\uav_wargame\python.exe" -m pytest
```

常用变体：

```powershell
# 精简输出
python -m pytest -q

# 显示每个用例名称
python -m pytest -v

# 只跑某个模块
python -m pytest tests/test_combat.py

# 只跑名称匹配的用例
python -m pytest -k "attack or evade"

# 首个失败即停止
python -m pytest -x

# 显示打印输出（排查仿真日志时有用）
python -m pytest -s
```

> 当前基线：`219 passed`，全部用例通过。

### 4. 打包为可执行文件（可选）

`UAV_WarGame.spec` 已配置好数据文件与隐藏导入，打包命令为：

```powershell
pip install pyinstaller
pyinstaller UAV_WarGame.spec
```

产物位于 `dist/UAV_WarGame/`，双击其中的 `UAV_WarGame.exe` 即可运行（无需控制台）。

## 命令速查

| 目的 | 命令 |
|---|---|
| 进入项目目录 | `cd D:\应用综合实验\UAV_WarGame` |
| 激活环境 | `conda activate uav_wargame` |
| 安装依赖 | `pip install -r requirements.txt` |
| 启动主程序（QML） | `python main.py` |
| 启动旧前端（Pygame） | `python pygame_main.py` |
| 运行全部测试 | `pytest` 或 `python -m pytest -q` |
| 打包 | `pyinstaller UAV_WarGame.spec` |

## 键盘操作

QML 前端与 Pygame 前端使用同一套按键。标注“部署”的按键仅在部署阶段生效。

| 按键 | 功能 |
|---|---|
| Enter | 开始仿真（部署阶段） |
| 1 | 选择侦察无人机（部署阶段） |
| 2 | 选择打击无人机（部署阶段） |
| 3 | 选择无人战车（部署阶段） |
| 4 | 选择导弹发射车（部署阶段） |
| 5 | 选择指挥节点（部署阶段） |
| 6 | 选择障碍物-山地（部署阶段） |
| 7 | 选择障碍物-建筑（部署阶段） |
| 8 | 选择障碍物-禁行区（部署阶段） |
| T | 切换红/蓝方阵营（部署阶段） |
| Backspace | 撤销部署 / 删除选中障碍物（部署阶段） |
| Delete | 删除选中障碍物（部署阶段） |
| C | 清空地图（清除所有单位和障碍物，部署阶段） |
| R | 恢复预设开局 |
| L | 加载地图（部署阶段） |
| Ctrl+S | 保存地图（部署阶段） |
| Space | 暂停/继续 |
| S | 单步推进 |
| F | 切换仿真速度（1x/2x/4x/MAX） |
| K | 切换残骸显示 |
| ESC | 退出 |

### 鼠标操作（部署阶段）

| 操作 | 功能 |
|------|------|
| 左键点击空位 | 放置当前选中的单位 |
| 左键拖拽空位 | 创建矩形障碍物（需先按键 6/7/8 选择障碍物类型） |
| 左键点击已有对象 | 选中单位或障碍物 |
| 左键拖拽已有对象 | 移动单位、障碍物或基地 |
| 左键拖拽障碍物右下角把手 | 调整障碍物大小 |
| 右键点击 | 删除单位或障碍物 |

### 地图文件

- 预设场景：`data/scenario_1.json`，启动时自动加载。
- 保存地图：`Ctrl+S` 写入 `data/saved_map.json`。
- 加载地图：`L` 读取 `data/saved_map.json` 并回到部署状态。

## 演示流程建议

1. 启动程序，界面全部中文，系统处于部署阶段，地图显示预设单位和障碍物。
2. 可直接在预设地图上编辑：按键 `1`-`5` 选兵种，`T` 切换阵营，左键点击放置单位。
3. 按键 `6`-`8` 选障碍物类型，左键拖拽创建；右键删除对象；左键拖拽移动单位/障碍物/基地。
4. 按 `C` 清空地图从头手动部署；按 `R` 恢复预设开局。
5. 按 `Ctrl+S` 保存当前编辑结果为新预设；按 `L` 加载已保存的地图。
6. 按 `Enter` 开始仿真，按 `S` 单步推进观察战斗。
7. 运行中按 `R` 退回部署继续编辑；按 `K` 切换残骸显示。

## 常见问题

- Pygame 安装失败：请使用 Python 3.10-3.13 的 Anaconda 环境，不要用 Python 3.14 环境。
- 找不到 `uav_wargame` 环境：确认解释器路径为 `D:\conda_envs\uav_wargame\python.exe`；conda 未初始化时直接用该路径调用即可。
- `ModuleNotFoundError: core` / `ui`：说明当前工作目录不是项目根目录，先 `cd D:\应用综合实验\UAV_WarGame` 再运行。
- 中文字体显示异常：可在 `ui/panel.py` 和 `ui/renderer.py` 中更换为本机中文字体。
- 控制台日志较多：日志用于讲解侦察、攻击和规避流程，可按需增加日志开关。

## 兵种说明

| 兵种 | 平台 | 特点 |
|---|---|---|
| 侦察无人机 | 空中 | 高速、高侦察、低攻击 |
| 打击无人机 | 空中 | 中速、中攻击、适合打击 |
| 无人战车 | 地面 | 低速、高生命、高攻击 |
| 导弹发射车 | 地面 | 远程、高伤害、低弹药 |
| 指挥节点 | 指挥 | 不移动、核心节点 |

场景文件使用 `unit_type` 创建单位，例如：

```json
{
  "id": "R-SD-1",
  "name": "红-侦察无人机",
  "team": "red",
  "unit_type": "scout_drone",
  "x": 85,
  "y": 110
}
```
