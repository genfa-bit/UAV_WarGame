"""简化 Bug2 绕障算法。

单位知道障碍物位置，向目标直线移动；被阻时沿障碍物边缘绕行，
一旦到目标的直线再次畅通就脱离绕障恢复直行。
"""

from __future__ import annotations

from math import hypot

from core.battlefield import Battlefield
from core.units import Unit, UnitDomain

_EDGE_FOLLOW: dict[str, str | None] = {}  # unit_id -> "left"/"right"/None
_STUCK_COUNTERS: dict[str, int] = {}       # 角落卡死计数


def _sign(x: float) -> int:
    return 1 if x >= 0 else -1


def move_to(unit: Unit, target_x: float, target_y: float,
            battlefield: Battlefield) -> bool:
    """向目标移动一步，自动绕障。空中单位直飞。返回 True 表示发生了移动。"""
    if unit.is_destroyed or unit.speed <= 0:
        return False

    # 空中单位无需绕障
    if unit.domain == UnitDomain.AIR:
        unit.move_towards(target_x, target_y, battlefield)
        return True

    old_x, old_y = unit.x, unit.y
    dx = target_x - unit.x
    dy = target_y - unit.y
    dist = hypot(dx, dy)
    if dist == 0:
        return False

    # 向目标直线方向移动一步
    step = min(unit.speed, dist)
    nx = unit.x + dx / dist * step
    ny = unit.y + dy / dist * step
    nx, ny = battlefield.clamp_position(nx, ny)

    # 直线通畅 → 直接移动，清除绕障状态
    if battlefield.can_move_to(nx, ny, unit.domain):
        unit.x, unit.y = nx, ny
        _EDGE_FOLLOW.pop(unit.id, None)
        return True

    # 进入绕障模式
    return _follow_edge(unit, target_x, target_y, battlefield)


def _follow_edge(unit: Unit, tx: float, ty: float,
                 battlefield: Battlefield) -> bool:
    """沿障碍物边缘移动一步。"""
    side = _EDGE_FOLLOW.get(unit.id)

    if side is None:
        # 选择绕行方向：左/右垂直于目标方向
        dx = tx - unit.x
        dy = ty - unit.y
        dist = hypot(dx, dy) or 1.0
        # 垂直于目标方向的两个候选
        lx, ly = -dy / dist, dx / dist  # 左侧
        rx, ry = dy / dist, -dx / dist   # 右侧

        # 分别试探左右两步
        for label, sx, sy in (("left", lx, ly), ("right", rx, ry)):
            for mult in (1.5, 1.0, 0.7):
                cx = unit.x + sx * unit.speed * mult
                cy = unit.y + sy * unit.speed * mult
                cx, cy = battlefield.clamp_position(cx, cy)
                if battlefield.can_move_to(cx, cy, unit.domain):
                    # 选好后检查是否已能直线到达目标
                    ndx = tx - cx
                    ndy = ty - cy
                    nd = hypot(ndx, ndy) or 0.001
                    snx = cx + ndx / nd * min(unit.speed, nd)
                    sny = cy + ndy / nd * min(unit.speed, nd)
                    snx, sny = battlefield.clamp_position(snx, sny)
                    if battlefield.can_move_to(snx, sny, unit.domain):
                        # 已经可以直走了
                        unit.x, unit.y = snx, sny
                        return True
                    # 否则进入绕障模式
                    _EDGE_FOLLOW[unit.id] = label
                    unit.x, unit.y = cx, cy
                    return True
        # 两侧都堵 → 原地不动
        return False

    # 已有绕障方向 → 沿边缘继续
    dx = tx - unit.x
    dy = ty - unit.y
    dist = hypot(dx, dy) or 1.0
    lx, ly = -dy / dist, dx / dist  # 左
    rx, ry = dy / dist, -dx / dist   # 右
    if side == "left":
        sx, sy = lx, ly
    else:
        sx, sy = rx, ry

    # 尝试沿绕障方向移动
    for mult in (1.2, 1.0, 0.8, 0.5):
        cx = unit.x + sx * unit.speed * mult
        cy = unit.y + sy * unit.speed * mult
        cx, cy = battlefield.clamp_position(cx, cy)
        if battlefield.can_move_to(cx, cy, unit.domain):
            # 检查是否已能直达目标
            ndx = tx - cx
            ndy = ty - cy
            nd = hypot(ndx, ndy) or 0.001
            snx = cx + ndx / nd * min(unit.speed, nd)
            sny = cy + ndy / nd * min(unit.speed, nd)
            snx, sny = battlefield.clamp_position(snx, sny)
            if battlefield.can_move_to(snx, sny, unit.domain):
                unit.x, unit.y = snx, sny  # 直走
                _EDGE_FOLLOW.pop(unit.id, None)
                return True
            # 继续绕
            unit.x, unit.y = cx, cy
            return True

    # 沿边缘走不动 → 角落卡死，反弹逃离
    _EDGE_FOLLOW.pop(unit.id, None)
    return _corner_escape(unit, tx, ty, battlefield)


def _corner_escape(unit: Unit, tx: float, ty: float,
                   battlefield: Battlefield) -> bool:
    """角落反弹：远离最近边界，跳出死循环。"""
    _STUCK_COUNTERS[unit.id] = _STUCK_COUNTERS.get(unit.id, 0) + 1
    # 向地图中心 + 目标方向反弹
    cx, cy = battlefield.width / 2, battlefield.height / 2
    # 混合方向：60%目标方向 + 40%地图中心
    dx_to_target = tx - unit.x
    dy_to_target = ty - unit.y
    d1 = hypot(dx_to_target, dy_to_target) or 0.001
    dx_to_center = cx - unit.x
    dy_to_center = cy - unit.y
    d2 = hypot(dx_to_center, dy_to_center) or 0.001
    mix_x = dx_to_target / d1 * 0.6 + dx_to_center / d2 * 0.4
    mix_y = dy_to_target / d1 * 0.6 + dy_to_center / d2 * 0.4
    # 远离最近边界（四个边界）
    dist_left = unit.x
    dist_right = battlefield.width - unit.x
    dist_top = unit.y
    dist_bottom = battlefield.height - unit.y
    nearest_boundary = min(dist_left, dist_right, dist_top, dist_bottom)
    if nearest_boundary < 50:
        if nearest_boundary == dist_left:
            mix_x = 1.0
        elif nearest_boundary == dist_right:
            mix_x = -1.0
        elif nearest_boundary == dist_top:
            mix_y = 1.0
        else:
            mix_y = -1.0
    # 尝试反弹
    for step_mult in (1.5, 1.0, 0.7):
        nx = unit.x + mix_x * unit.speed * step_mult
        ny = unit.y + mix_y * unit.speed * step_mult
        nx, ny = battlefield.clamp_position(nx, ny)
        if battlefield.can_move_to(nx, ny, unit.domain):
            unit.x, unit.y = nx, ny
            return True
    # 完全卡死 → 硬跳
    jump_x = unit.x + (1 if unit.team == "red" else -1) * 40
    jump_y = unit.y + 30 * (_STUCK_COUNTERS.get(unit.id, 0) % 3 - 1)
    jump_x, jump_y = battlefield.clamp_position(jump_x, jump_y)
    if battlefield.can_move_to(jump_x, jump_y, unit.domain):
        unit.x, unit.y = jump_x, jump_y
    return True


def reset_path(unit_id: str) -> None:
    """切换目标时重置绕障状态。"""
    _EDGE_FOLLOW.pop(unit_id, None)
    _STUCK_COUNTERS.pop(unit_id, None)
