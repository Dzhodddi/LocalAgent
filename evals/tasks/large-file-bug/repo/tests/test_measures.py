from measures import circle_area, mm_to_cm_v1, triangle_area


def test_triangle_area():
    assert triangle_area(4, 3) == 6


def test_circle_area():
    assert circle_area(1) == 3.141593


def test_conversion():
    assert mm_to_cm_v1(25) == 2.5
