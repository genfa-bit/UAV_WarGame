from core.battlefield import Obstacle, obstacle_display_name


def test_generated_obstacle_names_are_hidden_from_ui():
    assert obstacle_display_name(
        Obstacle(0, 0, 10, 10, name="mountain_5", type="mountain")
    ) == "山地"
    assert obstacle_display_name(
        Obstacle(0, 0, 10, 10, name="building_2", type="building")
    ) == "建筑群"
    assert obstacle_display_name(
        Obstacle(0, 0, 10, 10, name="restricted_1", type="restricted")
    ) == "禁行区"


def test_custom_obstacle_names_are_preserved():
    obstacle = Obstacle(0, 0, 10, 10, name="中央山地", type="mountain")

    assert obstacle_display_name(obstacle) == "中央山地"
