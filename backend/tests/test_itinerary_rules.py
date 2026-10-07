"""行程生成后的兜底逻辑单元测试 (离线, 不发外部请求)

本项目对"LLM 是否听话"采取的是**后置强制校正**策略, 而不是把约束写在提示词里
然后祈祷。这里固化四道兜底 + 距离排程的行为:

    _dedupe_attractions     全行程景点不重复
    _ensure_evening_plans   每天恰好 N 个夜间景点(多了裁、空了补)
    _ensure_famous_per_day  每天至少 1 个知名景点(榜单命中)
    _ensure_slot_counts     上午/下午各 N 个
    _optimize_itinerary_distance  按距离就近重排(不增删景点)

这些兜底都是踩坑后加的, 例如"上下午只剩1个景点""第2/3天夜间为空"
都是实际出现过的 bug, 用测试锁住。
"""

import pytest

from app.agents.trip_planner_agent import MultiAgentTripPlanner
from app.models.schemas import (
    Attraction, DayPlan, Location, Meal, POIInfo, TripPlan,
)


def attr(name: str, lon: float = 116.4, lat: float = 39.9,
         rating: float = 4.5) -> Attraction:
    return Attraction(
        name=name, address="测试地址",
        location=Location(longitude=lon, latitude=lat),
        visit_duration=120, description="测试", category="景点", rating=rating,
    )


def poi(name: str, lon: float = 116.4, lat: float = 39.9,
        rating: float = 4.5) -> POIInfo:
    return POIInfo(
        id=f"id-{name}", name=name, type="风景名胜;风景名胜;国家级景点",
        address="测试地址", location=Location(longitude=lon, latitude=lat),
        typecode="110202", rating=rating,
    )


def make_day(index: int, morning=None, afternoon=None, evening=None) -> DayPlan:
    day = DayPlan(
        date=f"2026-01-{index + 1:02d}", day_index=index,
        description="d", transportation="公共交通", accommodation="经济型酒店",
        attractions_morning=morning or [], attractions_afternoon=afternoon or [],
        attractions_evening=evening or [],
        meals=[Meal(type="lunch", name="待选择", estimated_cost=50),
               Meal(type="dinner", name="待选择", estimated_cost=80)],
    )
    day.merge_attractions()
    return day


@pytest.fixture
def planner() -> MultiAgentTripPlanner:
    """跳过 __init__ 避免构建图与初始化 LLM, 但手动补上 settings

    __init__ 会调用 get_llm() 与 _build_graph(), 在单元测试里既没必要也会很慢,
    故用 __new__ 绕过; 被测方法依赖 self.settings, 这里手动注入。
    """
    from app.config import get_settings

    p = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    p.settings = get_settings()
    p._famous_names = set()
    return p


def state(**kw) -> dict:
    base = {"attraction_pois": [], "night_attraction_pois": [],
            "famous_attraction_pois": [], "request": None}
    base.update(kw)
    return base


def slot_names(plan: TripPlan) -> list:
    """收集全行程各时段的景点名

    注意: 不要断言 day.attractions(合并列表) —— 各兜底方法只改时段字段,
    合并列表由 plan_trip 在所有兜底执行完毕后统一重建(见 _merge_all_days)。
    单元测试直接测兜底方法, 因此读时段字段。
    """
    return [
        a.name
        for d in plan.days
        for a in (d.attractions_morning + d.attractions_afternoon + d.attractions_evening)
    ]


# ============ 去重 ============

class TestDedupe:
    def test_removes_cross_day_duplicate(self, planner):
        """同一景点出现在不同天应被去重(实测 LLM 会这么干)"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-02",
            days=[
                make_day(0, morning=[attr("故宫")]),
                make_day(1, afternoon=[attr("故宫"), attr("天坛")]),
            ],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._dedupe_attractions(plan)
        names = slot_names(plan)
        assert names.count("故宫") == 1
        assert "天坛" in names

    def test_removes_duplicate_across_slots_same_day(self, planner):
        """同一景点出现在同一天的两个时段也应去重"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("故宫")], afternoon=[attr("故宫")])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._dedupe_attractions(plan)
        assert len(slot_names(plan)) == 1

    def test_keeps_first_occurrence(self, planner):
        """保留首次出现的位置"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-02",
            days=[
                make_day(0, morning=[attr("故宫")]),
                make_day(1, morning=[attr("故宫")]),
            ],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._dedupe_attractions(plan)
        assert [a.name for a in plan.days[0].attractions_morning] == ["故宫"]
        assert plan.days[1].attractions_morning == []


# ============ 夜间兜底 ============

class TestEveningPlans:
    def test_fills_empty_evening(self, planner):
        """夜间为空时补一个 —— 用户要求每天都安排夜间游览"""
        night = [poi("什刹海"), poi("南锣鼓巷"), poi("景山公园")]
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-03",
            days=[make_day(0), make_day(1), make_day(2)],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._ensure_evening_plans(plan, state(night_attraction_pois=night))
        assert all(len(d.attractions_evening) == 1 for d in plan.days)
        # 各天应使用不同景点(去重)
        names = [d.attractions_evening[0].name for d in plan.days]
        assert len(set(names)) == 3

    def test_trims_to_configured_count(self, planner):
        """给多了要裁到配置数量(用户要求一天一个)"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, evening=[attr("A"), attr("B"), attr("C")])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._ensure_evening_plans(plan, state(night_attraction_pois=[poi("X")]))
        assert len(plan.days[0].attractions_evening) == 1

    def test_does_not_reuse_daytime_attractions(self, planner):
        """补夜间时不能选白天已用过的景点"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("什刹海"), attr("故宫")])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._ensure_evening_plans(
            plan, state(night_attraction_pois=[poi("什刹海"), poi("南锣鼓巷")])
        )
        assert plan.days[0].attractions_evening[0].name == "南锣鼓巷"


# ============ 上午/下午数量兜底 ============

class TestSlotCounts:
    def test_fills_to_target(self, planner):
        """某段不足2个时补齐 —— 实际出现过上下午只剩1个景点的问题"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("故宫")], afternoon=[attr("天坛")])],
            weather_info=[], overall_suggestions="",
        )
        pool = [poi("颐和园"), poi("北海公园"), poi("雍和宫")]
        plan = planner._ensure_slot_counts(plan, state(attraction_pois=pool))
        assert len(plan.days[0].attractions_morning) == 2
        assert len(plan.days[0].attractions_afternoon) == 2

    def test_does_not_create_duplicates(self, planner):
        """补齐时不能引入全行程已存在的景点"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("故宫")])],
            weather_info=[], overall_suggestions="",
        )
        # 候选池里只有已用过的"故宫"
        plan = planner._ensure_slot_counts(plan, state(attraction_pois=[poi("故宫")]))
        names = slot_names(plan)
        assert names.count("故宫") == 1

    def test_leaves_full_slots_untouched(self, planner):
        """已达标的时段不应被改动"""
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("A"), attr("B")],
                           afternoon=[attr("C"), attr("D")])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._ensure_slot_counts(
            plan, state(attraction_pois=[poi("X"), poi("Y")])
        )
        assert [a.name for a in plan.days[0].attractions_morning] == ["A", "B"]
        assert [a.name for a in plan.days[0].attractions_afternoon] == ["C", "D"]


# ============ 知名景点兜底 ============

class TestFamousGuarantee:
    def test_replaces_when_no_famous(self, planner):
        """某天没有知名景点时, 用榜单景点替换普通景点"""
        planner._famous_names = {"故宫博物院"}
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("无名小馆"), attr("某艺术馆")],
                           afternoon=[attr("普通景点"), attr("另一个")])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._ensure_famous_per_day(
            plan, state(famous_attraction_pois=[poi("故宫博物院")])
        )
        names = slot_names(plan)
        assert "故宫博物院" in names

    def test_no_change_when_already_has_famous(self, planner):
        """已有知名景点则不动"""
        planner._famous_names = {"故宫博物院"}
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[attr("故宫博物院"), attr("B")],
                           afternoon=[attr("C"), attr("D")])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._ensure_famous_per_day(
            plan, state(famous_attraction_pois=[poi("颐和园")])
        )
        names = slot_names(plan)
        assert "颐和园" not in names, "已有名胜时不应再替换"
        assert "故宫博物院" in names


# ============ 距离排序与重排 ============

class TestDistance:
    def test_haversine_known_distance(self, planner):
        """北京到天津约 110-130km, 校验球面距离量级正确"""
        d = planner._haversine_m(116.407, 39.904, 117.201, 39.084)
        assert 100_000 < d < 140_000

    def test_rank_puts_near_first(self, planner):
        """按酒店距离排序: 近的在前"""
        hotel = Location(longitude=116.407, latitude=39.904)
        near = poi("近的", 116.408, 39.905)
        far = poi("远的", 116.60, 40.05)
        ranked = planner._rank_attractions_by_hotel([far, near], hotel)
        assert ranked[0].name == "近的"

    def test_rank_attaches_distance_attribute(self, planner):
        """排序时应把距离写入临时属性, 供提示词展示"""
        hotel = Location(longitude=116.407, latitude=39.904)
        p = poi("某景点", 116.42, 39.91)
        ranked = planner._rank_attractions_by_hotel([p], hotel)
        assert getattr(ranked[0], "_hotel_distance_m", None) is not None

    def test_optimize_shortens_zigzag_route(self, planner):
        """折返顺序应被改成顺路顺序, 且不增删景点

        构造: 北1 -> 南1 -> 北2 -> 南2 (南北相距约12km, 来回折返)
        """
        a = attr("北1", 116.40, 39.99)
        c = attr("南1", 116.40, 39.88)
        b = attr("北2", 116.41, 39.98)
        d = attr("南2", 116.41, 39.87)
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[a, c, b, d])],
            weather_info=[], overall_suggestions="",
        )
        before_len = planner._route_length(plan.days[0].attractions_morning)
        plan = planner._optimize_itinerary_distance(plan)
        after = plan.days[0].attractions_morning
        after_len = planner._route_length(after)

        assert {x.name for x in after} == {"北1", "南1", "北2", "南2"}, "重排不应增删景点"
        assert after_len < before_len, "重排后路程未缩短"

    def test_optimize_keeps_already_short_route(self, planner):
        """已顺路的顺序不应被打乱(最小收益门槛)"""
        e, f, g = attr("E", 116.40, 39.90), attr("F", 116.401, 39.901), attr("G", 116.402, 39.902)
        plan = TripPlan(
            city="北京", start_date="2026-01-01", end_date="2026-01-01",
            days=[make_day(0, morning=[e, f, g])],
            weather_info=[], overall_suggestions="",
        )
        plan = planner._optimize_itinerary_distance(plan)
        assert [a.name for a in plan.days[0].attractions_morning] == ["E", "F", "G"]
