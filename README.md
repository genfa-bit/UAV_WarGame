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
│   ├── units.py            # UAV、UGV、CommandNode 单位类
│   ├── strategy.py         # 侦察、集火目标选择、规避和移动策略
│   ├── combat.py           # 攻击范围、弹药、伤害和攻击事件
│   └── scenario_loader.py  # JSON 场景加载
├── ui/
│   ├── renderer.py         # 地图、单位、基地、障碍物和攻击效果绘制
│   └── panel.py            # 右侧信息面板
├── data/
│   └── scenario_1.json     # 示例场景数据
├── tests/
│   ├── test_combat.py      # 攻击结算测试
│   ├── test_detection.py   # 侦察目标池测试
│   ├── test_evade.py       # 规避行为测试
│   └── test_simulator.py   # 初始化、胜负和目标池清理测试
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
| M | 切换预设/手动部署 |
| 1 | 选择 ScoutDrone |
| 2 | 选择 StrikeDrone |
| 3 | 选择 GroundVehicle |
| 4 | 选择 MissileVehicle |
| 5 | 选择 CommandNode |
| T | 切换部署阵营 |
| 鼠标左键 | 放置单位 |
| Backspace | 撤销部署 |
| C | 清空部署 |
| R | 恢复预设开局 |
| Space | 暂停/继续 |
| S | 单步推进 |
| ESC | 退出 |

## 课程验收演示建议

1. 启动程序，先说明系统处于 Deployment 状态，地图显示预设单位。
2. 按 `M` 切换 Manual，使用数字键选择兵种，`T` 切换阵营，鼠标左键部署单位。
3. 演示障碍物部署限制：地面单位不能放入障碍物，空中单位可以部署在障碍物上方。
4. 按 `Enter` 开始仿真，再讲解探测范围、状态文字和右侧统计。
5. 按 `S` 单步推进，观察 `[Scout]`、`[Attack]`、`[Evade]` 日志。
6. 运行到一方全部摧毁，观察 Finished 状态和胜负结果。

## 常见问题

- Pygame 安装失败：请使用 Python 3.10-3.13 的 Anaconda 环境，不要用当前 Python 3.14 环境。
- 中文字体显示异常：可在 `ui/panel.py` 和 `ui/renderer.py` 中更换为本机中文字体。
- 单位遇到障碍物停止：第一版和第二阶段采用简单障碍处理，后续可加入 A* 路径规划。
- 控制台日志较多：日志用于验收讲解侦察、攻击和规避流程，正式版本可增加日志开关。

## 兵种说明

| 兵种 | 平台 | 特点 |
|---|---|---|
| ScoutDrone | 空中 | 高速、高侦察、低攻击 |
| StrikeDrone | 空中 | 中速、中攻击、适合打击 |
| GroundVehicle | 地面 | 低速、高生命、高攻击 |
| MissileVehicle | 地面 | 远程、高伤害、低弹药 |
| CommandNode | 指挥 | 不移动、核心节点 |

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
