"""单位工厂。

UnitFactory 使用注册表根据 JSON 中的 unit_type 创建具体兵种，避免
scenario_loader 中堆积大量 if-else。
"""

from __future__ import annotations

from core.units import (
    CommandNode,
    GroundVehicle,
    MissileVehicle,
    ScoutDrone,
    StrikeDrone,
    Unit,
)


UNIT_REGISTRY = {
    "scout_drone": ScoutDrone,
    "strike_drone": StrikeDrone,
    "ground_vehicle": GroundVehicle,
    "missile_vehicle": MissileVehicle,
    "command_node": CommandNode,
    # 兼容旧场景字段。
    "UAV": ScoutDrone,
    "UGV": GroundVehicle,
    "CommandNode": CommandNode,
}

UNIT_DOMAIN_MAP = {
    "scout_drone": "air",
    "strike_drone": "air",
    "ground_vehicle": "ground",
    "missile_vehicle": "ground",
    "command_node": "command",
    "UAV": "air",
    "UGV": "ground",
    "CommandNode": "command",
}


class UnitFactory:
    """根据 unit_type 创建单位对象。"""

    @staticmethod
    def get_domain(unit_type: str) -> str:
        """根据 unit_type 返回对应的平台类型。"""
        return UNIT_DOMAIN_MAP.get(unit_type, "ground")

    @staticmethod
    def create(unit_data: dict) -> Unit:
        """创建单位。

        若 unit_type 未注册，则抛出清晰错误，便于检查场景文件配置。
        """
        data = dict(unit_data)
        unit_type = data.pop("unit_type", data.pop("type", None))
        if not unit_type:
            raise ValueError("单位配置缺少 unit_type 字段")

        unit_class = UNIT_REGISTRY.get(unit_type)
        if unit_class is None:
            valid_types = ", ".join(sorted(UNIT_REGISTRY.keys()))
            raise ValueError(f"未知 unit_type: {unit_type}. 可用类型: {valid_types}")

        # 具体兵种类会写入自己的 unit_type，避免 JSON 中重复传入造成冲突。
        data.pop("domain", None)
        return unit_class(**data)
