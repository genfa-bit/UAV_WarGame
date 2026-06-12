# 无人装备战争游戏仿真系统

本项目是软件工程课程大作业，使用 Python + Pygame 实现二维无人装备对抗仿真。系统通过抽象规则展示自主侦察、协同集火、战术规避、战斗统计和胜负判断，不涉及真实军事参数。

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
- Pygame 显示单位、指挥节点、基地、障碍物、探测范围、血条、状态和攻击连线。
- 信息面板显示时间步、剩余单位、摧毁数量、发现目标数、集火目标、运行状态和胜负结果。
- 威胁评估与优先级目标排序，目标锁定避免频繁切换。
- 战场态势感知（战力/态势/战术），兵种角色智能化。
- 统一行为决策管理器，卡死检测与路径恢复。
- 兵种战斗属性 JSON 配置化（data/unit_config.json）。
- F 键仿真加速：1x / 2x / 4x / MAX 四档速度切换。

## 目录结构

```text
UAV_WarGame/
├── main.py                 # 程序入口，负责初始化和主循环
├── config.py               # 全局配置，如窗口尺寸、颜色、状态常量
├── requirements.txt        # 项目依赖
├── README.md               # 项目说明
├── core/
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
│   ├── pathfinding.py      # 地面绕障路径规划（Bug2算法）
│   └── unit_config_loader.py # 兵种配置加载器
├── ui/
│   ├── renderer.py         # 地图、单位、基地、障碍物和攻击效果绘制
│   └── panel.py            # 右侧信息面板
├── data/
│   ├── scenario_1.json     # 示例场景数据
│   └── unit_config.json    # 兵种战斗属性配置
├── tests/
│   ├── test_combat.py      # 攻击结算测试
│   ├── test_detection.py   # 侦察目标池测试
│   ├── test_evade.py       # 规避行为测试
│   ├── test_simulator.py   # 初始化、胜负和目标池清理测试
│   ├── test_unit_factory.py # 兵种工厂测试
│   ├── test_unit_domains.py # 平台类型测试
│   ├── test_deployment.py   # 部署阶段测试
│   ├── test_deployment_events.py # 部署事件测试
│   ├── test_state_transition.py # 状态切换测试
│   ├── test_movement_stability.py # 移动稳定性测试
│   ├── test_victory.py      # 胜负判断测试
│   ├── test_statistics.py   # 战斗统计测试
│   ├── test_detection_pool.py # 目标池测试
│   ├── test_focus_target.py  # 集火目标测试
│   ├── test_unit_state.py    # 单位状态机测试
│   ├── test_obstacle_editor.py # 障碍物编辑器测试
│   ├── test_obstacle_save_load.py # 地图保存加载测试
│   ├── test_base_drag.py     # 基地拖动测试
│   ├── test_destroyed_unit_visibility.py # 残骸显示测试
│   ├── test_ui_translation.py # 中文界面测试
│   ├── test_map_persistence.py # 地图持久化测试
│   ├── test_behavior_manager.py # 行为管理器测试
│   ├── test_threat_assessment.py # 威胁评估测试
│   ├── test_priority_target.py # 优先级目标测试
│   ├── test_battlefield_situation.py # 战场态势测试
│   ├── test_stuck_detection.py # 卡死检测测试
│   ├── test_role_behavior.py # 兵种角色测试
│   └── test_pathfinding.py # 路径规划测试
└── docs/                   # 软件工程课程文档
```

## 环境要求

- Python 3.10 或以上版本
- 推荐使用 Anaconda 专用环境 `uav_wargame`
- 当前推荐解释器：`D:\Anaconda\envs\uav_wargame\python.exe`
- 不建议使用 base；也不建议使用 Python 3.14 环境安装 Pygame

## 安装依赖

```powershell
cd d:\study_BJC\softwareproject\UAV_WarGame
conda activate uav_wargame
pip install -r requirements.txt
```

如果终端没有初始化 conda，可以直接指定解释器：

```powershell
& "D:\Anaconda\envs\uav_wargame\python.exe" -m pip install -r requirements.txt
```

## 运行方法

```powershell
python main.py
```

或：

```powershell
& "D:\Anaconda\envs\uav_wargame\python.exe" main.py
```

## 测试方法

```powershell
pytest
```

或：

```powershell
& "D:\Anaconda\envs\uav_wargame\python.exe" -m pytest
```

## 键盘操作

| 按键 | 功能 |
|---|---|
| Enter | 开始仿真 |
| 1 | 选择侦察无人机 |
| 2 | 选择打击无人机 |
| 3 | 选择无人战车 |
| 4 | 选择导弹发射车 |
| 5 | 选择指挥节点 |
| 6 | 选择障碍物-山地 |
| 7 | 选择障碍物-建筑 |
| 8 | 选择障碍物-禁行区 |
| T | 切换红/蓝方阵营 |
| Backspace | 撤销部署 / 删除选中障碍物 |
| Delete | 删除选中障碍物 |
| C | 清空地图（清除所有单位和障碍物） |
| R | 恢复预设开局 |
| Ctrl+S | 保存地图 |
| L | 加载地图 |
| Space | 暂停/继续 |
| S | 单步推进 |
| F | 切换仿真速度（1x/2x/4x/MAX） |
| K | 切换残骸显示 |
| ESC | 退出 |

### 鼠标操作（部署阶段）

| 操作 | 功能 |
|------|------|
| 左键点击空位 | 放置当前选中的单位 |
| 左键拖拽空位 | 创建矩形障碍物（需先按键6/7/8选择障碍物类型） |
| 左键点击已有对象 | 选中单位或障碍物 |
| 左键拖拽已有对象 | 移动单位、障碍物或基地 |
| 左键拖拽障碍物右下角把手 | 调整障碍物大小 |
| 右键点击 | 删除单位或障碍物 |

## 课程验收演示建议

1. 启动程序，界面全部中文，系统处于部署阶段，地图显示预设单位和障碍物。
2. 可直接在预设地图上编辑：按键 `1`-`5` 选兵种，`T` 切换阵营，左键点击放置单位。
3. 按键 `6`-`8` 选障碍物类型，左键拖拽创建；右键删除对象；左键拖拽移动单位/障碍物/基地。
4. 按 `C` 清空地图从头手动部署；按 `R` 恢复预设开局。
5. 按 `Ctrl+S` 保存当前编辑结果为新预设；按 `L` 加载已保存的地图。
6. 按 `Enter` 开始仿真，按 `S` 单步推进观察战斗。
7. 运行中按 `R` 退回部署继续编辑；按 `K` 切换残骸显示。

## 常见问题

- Pygame 安装失败：请使用 Python 3.10-3.13 的 Anaconda 环境，不要用当前 Python 3.14 环境。
- 中文字体显示异常：可在 `ui/panel.py` 和 `ui/renderer.py` 中更换为本机中文字体。
- 单位遇到障碍物停止：第一版和第二阶段采用简单障碍处理，后续可加入 A* 路径规划。
- 控制台日志较多：日志用于验收讲解侦察、攻击和规避流程，正式版本可增加日志开关。

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
