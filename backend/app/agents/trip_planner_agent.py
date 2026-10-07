"""基于 LangGraph 的多智能体旅行规划系统"""

import json
import logging
import math
import re
from datetime import datetime, timedelta
from typing import TypedDict, List, Tuple, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from ..config import get_settings
from ..services.llm_service import get_llm
from ..services.amap_service import get_amap_service
from ..services.hotel_service import get_hotel_service
from ..models.schemas import (
    TripRequest,
    TripPlan,
    DayPlan,
    Attraction,
    Meal,
    Location,
    Hotel,
    Budget,
    WeatherInfo,
    POIInfo,
)

logger = logging.getLogger(__name__)

# ============ 行程规划提示词 ============

PLANNER_SYSTEM_PROMPT = """你是专业的行程规划专家。根据用户提供的景点、天气和酒店信息, 生成详细的旅行计划。

**输出要求:**
必须只输出一个 JSON 对象, 不要输出任何其他文字, JSON 结构严格如下:
{{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "morning_desc": "上午行程概述",
      "afternoon_desc": "下午行程概述",
      "evening_desc": "夜间行程概述",
      "attractions_morning": [
        {{
          "name": "上午景点名称",
          "address": "详细地址",
          "location": {{"longitude": 116.397128, "latitude": 39.916527}},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }}
      ],
      "attractions_afternoon": [
        {{
          "name": "下午景点名称",
          "address": "详细地址",
          "location": {{"longitude": 116.397128, "latitude": 39.916527}},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }}
      ],
      "attractions_evening": [
        {{
          "name": "夜间可去景点名称(从「夜间可去景点」列表选)",
          "address": "详细地址",
          "location": {{"longitude": 116.397128, "latitude": 39.916527}},
          "visit_duration": 90,
          "description": "夜间游览描述",
          "category": "景点类别",
          "ticket_price": 0
        }}
      ],
      "meals": [
        {{"type": "lunch", "name": "待选择", "description": "该餐建议", "estimated_cost": 50}},
        {{"type": "dinner", "name": "待选择", "description": "该餐建议", "estimated_cost": 80}}
      ]
    }}
  ],
  "weather_info": [
    {{
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }}
  ],
  "overall_suggestions": "总体建议",
  "budget": {{
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }}
}}

**规则:**
1. **一天分为三个时段**, 景点数量固定如下:
   - `attractions_morning`  上午 **恰好 2 个**
   - `attractions_afternoon` 下午 **恰好 2 个**(午餐在上午与下午之间)
   - `attractions_evening`  **每晚恰好 1 个**, 只能从「夜间可去景点」列表里选
     (该列表已按"适合夜游"筛过)。**用户明确要求每天都安排夜间游览**,
     除非该列表为空, 否则不得留空。多天时请为每天选**不同**的夜间景点。
   若候选确实不足, 宁可少排也不要硬凑, 但正常情况下必须满足上述数量。
2. **距离只是次要参考, 绝不能为了"离酒店近"而放弃关键名胜。**
   本城的核心景点(如天坛、故宫、长城这类知名景点)即使离酒店较远也必须安排
   —— 用户明确表示"距离较远时放弃关键名胜不合适"。
   候选列表已按距酒店距离排序并标注"距酒店 X km", 但**排序靠后不代表不该去**。
   请以景点知名度/价值与用户偏好为主要依据; 距离仅用于在**同等价值**的景点
   之间取舍, 以及让同一天的景点顺路一些(当天内不要来回折返)。
   当晚回同一家酒店住宿。
2b. **同一景点在全行程中只能出现一次!** 不允许把同一个景点排进多个时段、
   或在不同天重复出现(系统会强制去重, 重复的会被移除导致行程变空)。
   每个候选景点只使用一次。
3. **景点只能是真实的游览场所**(风景名胜/公园/博物馆/美术馆/展览馆/科技馆/
   纪念馆/红色景区/寺庙道观/动物园/水族馆/游乐场)。**严禁**把餐厅、饭店、
   火锅店、小吃店、商场、KTV、酒吧、洗浴中心、SPA、足疗按摩、网吧等
   写进任何 attractions 字段 —— 吃饭由 meals 字段体现, 购物娱乐不属于景点。
4. **优先从「可选景点」列表中选择**; 该列表已过滤掉非游览场所, 可信。
   只有列表明显不足时才可补充你确有把握的知名景点, 且仍须遵守第3条。
5. **严格按用户勾选的旅行偏好选景**:
   - 红色精神 -> 红色景区/纪念馆/革命旧址/烈士纪念设施
   - 自然风景 -> 公园/山湖/自然类国家级景点
   - 人文风光 -> 寺庙道观/古城/世界遗产/历史文化街区
   - 博物馆藏 -> 博物馆/展览馆/科技馆/美术馆
   - 动物世界 -> 动物园/水族馆/海洋馆
   - 游乐场 -> 主题乐园/游乐场
   勾选了哪几类, 景点就应集中在这几类里, 不要安排无关类型。
6. 每天只包含午餐和晚餐两餐(lunch/dinner), **不要输出早餐(breakfast)**。
   meals 顺序必须是 lunch 在前, dinner 在后(午餐夹在上午与下午之间)。
7. 餐饮的 name 字段固定填写"待选择", description 填写该餐的建议
   (如"建议在故宫周边用餐"), estimated_cost 填写合理的人均预估。
   **不要编造具体餐厅名** —— 具体餐厅由用户从系统提供的周边候选中自行选择
8. **不要输出 hotel 字段**: 用户已自行选定一家酒店, 全程都住这一家,
   由系统统一填充。你只需照常安排景点与餐饮。
9. weather_info 中按日期填入对应天气; 某天没有天气数据时, 字段留空
10. 景点的经纬度坐标必须使用提供的真实坐标
11. 所有费用字段填写合理估算值, budget 为各项费用汇总
"""


class GraphState(TypedDict, total=False):
    """LangGraph 工作流状态"""
    request: TripRequest               # 用户旅行请求
    attraction_pois: List[POIInfo]     # 景点搜索结果
    famous_attraction_pois: List[POIInfo]  # 知名景点(榜单命中), 用于每日保底
    night_attraction_pois: List[POIInfo]  # 夜间可去景点(晚餐后安排用)
    weather_info: List[WeatherInfo]    # 天气信息
    hotel_pois: List[POIInfo]          # 酒店搜索结果
    trip_plan: TripPlan                # 最终行程计划
    error: bool                        # 是否出错(用于条件路由)


class MultiAgentTripPlanner:
    """基于 LangGraph 的多智能体旅行规划系统

    工作流: 搜索景点 → 查询天气 → 搜索酒店 → LLM生成行程 → (LLM失败)备用计划
    数据获取节点直接调用高德服务(不走LLM), 仅行程规划调用LLM, 高效且省成本。
    """

    def __init__(self):
        """初始化多智能体系统"""
        logger.info("🔄 开始初始化多智能体旅行规划系统...")
        self.settings = get_settings()
        self.llm = get_llm()
        self.amap_service = get_amap_service()
        self.graph = self._build_graph()
        logger.info("✅ 多智能体系统初始化成功")

    # ============ LangGraph 节点 ============

    def _search_attractions(self, state: GraphState) -> dict:
        """节点1: 搜索景点 (服务直调, 不走LLM)

        原实现把用户偏好词直接当关键词搜且不限类型, 导致"美食"偏好搜回一堆
        餐厅、"休闲"偏好搜回酒吧SPA, 最终被 LLM 排进每日景点。现在改为:
        1. 用中性景点关键词 + 偏好定向召回, 经类型白名单/黑名单筛选
        2. 剔除父子重复POI, 避免同一天重复安排"故宫博物院"及其门楼
        3. 应用景点状元榜(状元榜/必玩榜)加权
        4. **按用户选定的酒店距离筛选**: 只保留离酒店较近的景点,
           因为全程只住这一家酒店, 景点必须围绕它安排才合理
        5. RAG 知识库补充(未启用时静默跳过)
        """
        request = state["request"]
        logger.info("📍 步骤1: 搜索景点...")
        try:
            from ..services.attraction_service import get_attraction_service

            svc = get_attraction_service()
            pois = svc.search_attractions(
                city=request.city,
                preferences=request.preferences,
                # 取较多候选: 一天分上午/下午/夜间三段, 需要足够景点让LLM在
                # 每段填2个; 取少了会导致每段只有1个景点(实测发生过)
                top_n=36,
            )
            logger.info(f"   找到 {len(pois)} 个真实景点")

            # 记录命中景点榜单(状元榜/必玩榜)的景点名, 作为"知名景点"判据,
            # 供 _ensure_famous_per_day 保底使用
            self._famous_names = self._collect_famous_names(svc)
            self._famous_pois = [
                p for p in pois if (p.name or "").strip() in self._famous_names
            ]
            logger.info(
                f"   🏆 知名景点(榜单命中) {len(self._famous_names)} 个; "
                f"其中在候选池内 {len(self._famous_pois)} 个"
            )

            # 按所选酒店的距离筛选 + 排序
            hotel_loc = request.hotel.location if request.hotel else None
            if hotel_loc and (hotel_loc.longitude or hotel_loc.latitude):
                pois = self._rank_attractions_by_hotel(pois, hotel_loc)
                logger.info(
                    f"   🏨 已按酒店「{request.hotel.name}」位置排序并筛选, "
                    f"保留 {len(pois)} 个景点"
                )

            # 夜间预留: 把专供夜间的景点从白天池中移除。
            # 夜间候选基本是白天候选的子集, 若不预留, LLM 会把南锣鼓巷/什刹海
            # 这类排进白天, 去重后夜间就没有候选可补了(实测第2、3天夜间为空)。
            reserved = self._reserve_night_attractions(pois)

            # RAG 知识库景点补充 (失败/未启用时静默跳过, 不影响主流程)
            try:
                from ..services.rag_service import get_rag_service

                known_names = {p.name for p in pois if p.name}
                for name in get_rag_service().get_knowledge_attractions(request.city):
                    if any(name in n for n in known_names):
                        continue
                    kb_pois = self.amap_service.search_poi(name, request.city)
                    if kb_pois:
                        pois.append(kb_pois[0])
                        known_names.add(kb_pois[0].name or "")
                        logger.info(f"   + 知识库补充景点: {name}")
            except Exception as e:
                logger.warning(f"   ⚠️ 知识库景点补充失败(不影响主流程): {e}")

            return {
                "attraction_pois": pois,
                "famous_attraction_pois": self._famous_pois,
            }
        except Exception as e:
            logger.warning(f"   ⚠️ 景点搜索失败: {e}")
            return {"attraction_pois": [], "famous_attraction_pois": []}

    def _collect_famous_names(self, attraction_svc) -> set:
        """收集"知名景点"名称

        判据: 命中景点榜单关键词(状元榜/必玩榜)。
        选择榜单作为判据的原因: 它是高德侧的知名度标记, 也已被系统用作排序加分,
        比"评分高"更贴近"名胜"(评分高的可能只是小众美术馆)。
        """
        hits = getattr(attraction_svc, "last_ranking_hits", None) or {}
        pois = getattr(attraction_svc, "last_ranking_pois", None) or {}
        words = set(self.settings.attraction_ranking_keywords)
        names = set()
        for poi_id, hit_words in hits.items():
            if not (set(hit_words) & words):
                continue
            poi = pois.get(poi_id)
            name = (poi.name or "").strip() if poi else ""
            if name:
                names.add(name)
        return names

    def _reserve_night_attractions(self, day_pois: List[POIInfo]) -> List[POIInfo]:
        """把夜间专属景点从白天候选池中移除, 返回保留名单

        只移除夜间候选里**排名靠前**的若干个(配置 night_reserved_attractions),
        且仅当移除后白天池仍有足够景点时才执行 —— 否则宁可让夜间与白天共享
        候选, 也不能把白天池削得太小导致排不出行程。
        """
        from ..services.attraction_service import get_attraction_service

        night_pool = getattr(self, "_night_pool", []) or []
        if not night_pool or not day_pois:
            return []

        reserve_n = min(self.settings.night_reserved_attractions, len(night_pool))
        reserved_names = {(p.name or "").strip() for p in night_pool[:reserve_n]}
        reserved_names.discard("")

        remaining = [p for p in day_pois if (p.name or "").strip() not in reserved_names]
        # 白天池至少留够 12 个, 否则放弃预留
        if len(remaining) < 12:
            logger.info(
                f"   🌙 夜间预留跳过(白天池仅 {len(remaining)} 个, 不足12)"
            )
            return []

        removed = len(day_pois) - len(remaining)
        day_pois[:] = remaining
        logger.info(
            f"   🌙 夜间预留 {removed} 个景点供夜间使用(白天不占用), "
            f"白天池剩 {len(remaining)} 个"
        )
        return sorted(reserved_names)

    def _search_night_attractions(self, state: GraphState) -> dict:
        """节点1b: 搜索夜间可去景点 (服务直调, 不走LLM)

        用户要求"晚餐后也可以安排行程"。高德不提供营业时间, 故用关键词代理
        (夜游/灯光秀/夜市)筛出适合夜游的景点, 同样经黑白名单过滤。
        结果缓存到 self._night_pool, 供白天节点排除"夜间预留"景点。

        【注意】本节点必须在 _search_attractions 之前执行(见图的边定义):
        白天节点需要先知道哪些景点是夜间专属, 才能把它们从白天池里剔除。
        """
        request = state["request"]
        logger.info("🌙 步骤1: 搜索夜间可去景点...")
        try:
            from ..services.attraction_service import get_attraction_service

            pois = get_attraction_service().search_night_attractions(request.city)

            # 夜间景点也按酒店距离筛选, 但**上限更严**:
            # 白天去 60km 外的长城合理, 夜间去就不现实 ——
            # 实测夜间池含八达岭长城(59.9km)并被排成夜间行程。
            hotel_loc = request.hotel.location if request.hotel else None
            if hotel_loc and (hotel_loc.longitude or hotel_loc.latitude):
                before = len(pois)
                pois = self._rank_attractions_by_hotel(
                    pois, hotel_loc, max_km=self.settings.night_attraction_max_km
                )
                logger.info(
                    f"   🌙 夜间景点按 {self.settings.night_attraction_max_km:.0f}km 内筛选: "
                    f"{before} -> {len(pois)} 条"
                )

            self._night_pool = pois
            return {"night_attraction_pois": pois}
        except Exception as e:
            logger.warning(f"   ⚠️ 夜间景点搜索失败: {e}")
            self._night_pool = []
            return {"night_attraction_pois": []}

    def _rank_attractions_by_hotel(
        self,
        pois: List[POIInfo],
        hotel_loc: Location,
        max_km: Optional[float] = None,
    ) -> List[POIInfo]:
        """按到酒店的距离排序并截断候选池

        做法: 按距离升序 → 剔除超过上限的 → 截断到最近 N 个。

        max_km: 自定义距离上限; 不传则用 hotel_attraction_max_km(日间 60km)。
                夜间应传 night_attraction_max_km(更严), 因为白天能去的远郊景点
                晚上去不现实。

        注意: 上限设得较宽(日间 60km)是刻意的 —— 用户明确要求"距离较远时放弃
        关键名胜不合适", 所以距离不该承担排除关键景点的职责, 只做排序与截断。
        """
        s = self.settings
        limit_km = max_km if max_km is not None else s.hotel_attraction_max_km
        scored: List[Tuple[POIInfo, float]] = []
        for poi in pois:
            loc = poi.location
            if not loc or (not loc.longitude and not loc.latitude):
                scored.append((poi, float("inf")))
                continue
            dist = MultiAgentTripPlanner._haversine_m(
                hotel_loc.longitude, hotel_loc.latitude, loc.longitude, loc.latitude
            )
            scored.append((poi, dist))

        scored.sort(key=lambda x: x[1])

        # 距离上限过滤
        near = [(p, d) for p, d in scored if d <= limit_km * 1000]

        # 近处景点太少时放宽(小城市或酒店在郊区), 避免把候选筛空排不出行程
        min_needed = 6
        if len(near) < min_needed:
            near = scored[: max(min_needed, s.hotel_attraction_max_items)]

        # 截断到最近的 N 个
        near = near[: s.hotel_attraction_max_items]

        # 把距离写回 POI(通过临时属性), 供提示词展示真实距离
        result = []
        for poi, dist in near:
            if dist != float("inf"):
                poi._hotel_distance_m = int(dist)  # type: ignore[attr-defined]
            result.append(poi)
        return result

    def _get_weather(self, state: GraphState) -> dict:
        """节点2: 查询天气 (服务直调, 不走LLM)"""
        request = state["request"]
        logger.info("🌤️  步骤2: 查询天气...")
        try:
            weather = self.amap_service.get_weather(request.city)
            logger.info(f"   获取 {len(weather)} 天天气数据")
            return {"weather_info": weather}
        except Exception as e:
            logger.warning(f"   ⚠️ 天气查询失败: {e}")
            return {"weather_info": []}

    def _search_hotels(self, state: GraphState) -> dict:
        """节点3: 搜索酒店 (服务直调, 不走LLM)

        按所选住宿档次的价位区间 + 评分下限筛选, 而不是把偏好词直接当
        关键词丢给高德 —— 否则"经济型酒店"搜出来什么全看高德返回。
        """
        request = state["request"]
        logger.info("🏨 步骤3: 搜索酒店...")
        try:
            from ..services.hotel_service import get_hotel_service

            hotels = get_hotel_service().search_hotels(
                accommodation=request.accommodation,
                city=request.city,
                top_n=5,
            )
            logger.info(f"   找到 {len(hotels)} 家符合档次与价位的酒店")
            return {"hotel_pois": hotels}
        except Exception as e:
            logger.warning(f"   ⚠️ 酒店搜索失败: {e}")
            return {"hotel_pois": []}

    def _generate_trip_plan(self, state: GraphState) -> dict:
        """节点4: LLM 生成行程计划

        采用「文本生成 + JSON提取 + Pydantic校验」的通用方案, 兼容任何模型
        (包括不支持 function calling / json_schema 的 thinking 模型)。
        解析失败时携带错误信息自纠错重试一次, 仍失败则走备用计划。
        """
        request = state["request"]
        logger.info("📋 步骤4: LLM 生成行程计划...")
        try:
            planner_query = self._build_planner_query(request, state)
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", PLANNER_SYSTEM_PROMPT),
                ("human", "{query}"),
            ])
            chain = prompt_template | self.llm 

            for attempt in range(2):
                response = chain.invoke({"query": planner_query})
                content = response.content if hasattr(response, "content") else str(response)
                try:
                    trip_plan = self._parse_json_response(content)
                    logger.info("   ✅ 行程计划生成成功")
                    return {"trip_plan": trip_plan, "error": False}
                except Exception as e:
                    logger.warning(f"   ⚠️ 第{attempt + 1}次解析失败: {str(e)[:100]}")
                    # 自纠错: 把校验错误反馈给LLM, 要求重新生成
                    planner_query = (
                        f"你上一次输出的 JSON 不符合结构要求, 错误信息: {e}\n"
                        f"你上一次的输出是: {content[:2000]}\n"
                        f"请严格按照 system 中定义的 JSON 结构重新输出完整 JSON。\n\n"
                        f"原始需求:\n{planner_query}"
                    )

            raise ValueError("两次尝试均未能生成合法行程计划")
        except Exception as e:
            logger.warning(f"   ⚠️ LLM 生成行程失败: {e}")
            return {"error": True}

    def _fallback_plan(self, state: GraphState) -> dict:
        """节点5: 备用计划 (LLM失败时兜底)"""
        logger.info("   🛟 使用备用计划")
        return {"trip_plan": self._create_fallback_plan(state["request"]), "error": False}

    def _should_fallback(self, state: GraphState) -> str:
        """条件路由: LLM生成失败则走备用计划, 否则结束"""
        return "fallback_plan" if state.get("error") else "end"

    # ============ 图构建 ============

    def _build_graph(self):
        """构建 LangGraph 工作流"""
        # 1. 实例化图，指定全局数据结构
        graph = StateGraph(GraphState)
        # 2. 注册所有节点 (把工人拉进厂)
        graph.add_node("search_attractions", self._search_attractions)
        graph.add_node("search_night_attractions", self._search_night_attractions)
        graph.add_node("get_weather", self._get_weather)
        graph.add_node("search_hotels", self._search_hotels)
        graph.add_node("generate_trip_plan", self._generate_trip_plan)
        graph.add_node("fallback_plan", self._fallback_plan)
        
        # 3. 铺设传送带 (普通边: 顺次执行)
        # 顺序要求: 夜间景点必须先检索 —— 白天节点要用它的结果排除"夜间预留"
        # 景点, 否则夜间候选会被白天挑走, 导致后几天夜间无景点可排。
        graph.add_edge(START, "search_night_attractions")
        graph.add_edge("search_night_attractions", "search_attractions")
        graph.add_edge("search_attractions", "get_weather")
        graph.add_edge("get_weather", "search_hotels")
        graph.add_edge("search_hotels", "generate_trip_plan")
        # 4. 铺设智能分拣闸门 (条件边: 失败走兜底，成功则结束)
        graph.add_conditional_edges(
            "generate_trip_plan",
            self._should_fallback,
            {"fallback_plan": "fallback_plan", "end": END},
        )
        graph.add_edge("fallback_plan", END)
        return graph.compile()

    # ============ 对外接口 ============

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """使用 LangGraph 工作流生成旅行计划

        Args:
            request: 旅行请求

        Returns:
            旅行计划
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🚀 开始 LangGraph 工作流规划旅行...")
        logger.info(f"目的地: {request.city} | 日期: {request.start_date} 至 {request.end_date} | {request.travel_days}天")
        logger.info(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
        logger.info(f"{'='*60}\n")

        result = self.graph.invoke({"request": request})
        trip_plan = result["trip_plan"]

        # 天气: 用高德真实天气覆盖LLM生成的天气。
        # LLM 常因日期不足而把天气字段输出 null/0, 导致前端温度全显示0;
        # 数据节点已拿到高德真实天气(含温度), 直接回填即可, 也符合"服务直调"架构。
        real_weather = result.get("weather_info") or []
        if real_weather:
            trip_plan.weather_info = real_weather

        # 全行程景点去重: 同一景点可能被 LLM 排进多个时段或不同天(实测),
        # 这里做硬保证, 不依赖 LLM 服从提示词。
        trip_plan = self._dedupe_attractions(trip_plan)

        # 每天都安排夜间游览: 提示词已要求, 但 LLM 未必每天照做, 这里补齐。
        # 放在去重之后, 保证不会引入与前文重复的景点。
        trip_plan = self._ensure_evening_plans(trip_plan, result)

        # 每天至少一个知名景点(榜单命中的名胜): 避免出现"行程里一个名胜都没有"。
        # 放在夜间补齐之后, 只替换白天时段的普通景点, 不动夜间安排。
        trip_plan = self._ensure_famous_per_day(trip_plan, result)

        # 上午/下午数量兜底: 去重与上面的保底替换都可能把某段削到1个, 这里补齐到2个。
        # 放在最后执行, 保证它看到的是最终的景点组合。
        trip_plan = self._ensure_slot_counts(trip_plan, result)

        # 全程同一家酒店: 用户已在"选择酒店"页选定, 覆盖 LLM 输出（LLM 被要求
        # 不输出 hotel）。这样"全程只住这一家"是硬保证, 不依赖 LLM 服从。
        trip_plan = self._apply_selected_hotel(trip_plan, request)

        # 合并上午/下午/夜间三段的景点到 attractions, 供地图打点与统计使用
        for day in trip_plan.days:
            day.merge_attractions()

        # 兜底: 若LLM未返回预算, 前端预算页会异常, 这里自动补齐
        trip_plan = self._ensure_budget(trip_plan, request)

        # 按距离就近重排: 用户要求"地点距离相近安排"。
        # LLM 只在提示词里看到"考虑距离"却拿不到真实距离, 实际顺序接近随机,
        # 故生成后做一次后置优化(只改顺序, 不增删景点)。
        trip_plan = self._optimize_itinerary_distance(trip_plan)

        # 知识库增强: 给每个景点追加知识库详情(门票/开放时间/交通/避坑),
        # 让知识库内容真正落到前端每个景点上。失败/未启用时静默跳过。
        try:
            from ..services.rag_service import get_rag_service

            rag = get_rag_service()
            for day in trip_plan.days:
                for attr in day.attractions:
                    detail = rag.get_attraction_rag_text(attr.name, trip_plan.city)
                    if detail:
                        attr.description = f"{attr.description}\n\n——知识库参考——\n{detail}"
        except Exception as e:
            logger.warning(f"⚠️  知识库详情增强失败(不影响主流程): {e}")

        logger.info(f"\n{'='*60}")
        logger.info(f"✅ 旅行计划生成完成! 天数: {len(trip_plan.days)}")
        logger.info(f"{'='*60}\n")
        return trip_plan

    def get_agent_info(self) -> dict:
        """Agent 信息 (供健康检查使用)"""
        return {
            "name": "LangGraph 多智能体旅行规划系统",
            "framework": "langgraph",
            "nodes": ["search_attractions", "search_night_attractions", "get_weather", "search_hotels", "generate_trip_plan", "fallback_plan"],
        }

    # ============ 内部工具方法 ============

    @staticmethod
    def _parse_json_response(content: str) -> TripPlan:
        """从LLM响应中提取JSON并用Pydantic校验

        Args:
            content: LLM原始输出

        Returns:
            校验通过的 TripPlan

        Raises:
            ValueError: JSON提取失败或结构校验失败
        """
        # 1. 提取代码块中的JSON (支持 ```json 包裹)
        if "```" in content:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                content = match.group(1)

        # 2. 截取首尾花括号之间的内容
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("LLM响应中未找到JSON对象")

        # 3. 解析JSON并通过Pydantic校验
        data = json.loads(content[start:end + 1])
        return TripPlan.model_validate(data)

    def _build_planner_query(self, request: TripRequest, state: GraphState) -> str:
        """构建行程规划 prompt (将结构化数据转为文本供LLM参考)"""
        attraction_text = self._pois_to_text(state.get("attraction_pois", []))
        night_text = self._pois_to_text(state.get("night_attraction_pois", []))
        weather_text = self._weather_to_text(state.get("weather_info", []))

        # 酒店: 用户已选定一家, 全程都住这里。景点列表已按到该酒店的距离排序。
        if request.hotel:
            h = request.hotel
            coord = (
                f"{h.location.longitude},{h.location.latitude}"
                if h.location else "未知"
            )
            hotel_text = (
                f"{h.name} | 类型: {h.type or h.tier or request.accommodation} | "
                f"评分: {h.rating if h.rating is not None else '无'} | "
                f"地址: {h.address} | 坐标: {coord}\n"
                f"(用户已选定此酒店, 全程{request.travel_days}晚都住这里, "
                f"请围绕它安排景点与餐饮)"
            )
        else:
            hotel_text = f"用户未指定具体酒店, 住宿档次: {request.accommodation}"

        query = f"""请为以下旅行需求生成{request.city}的{request.travel_days}天行程计划:

**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
- 住宿档次: {request.accommodation}
- 旅行偏好: {', '.join(request.preferences) if request.preferences else '无'}

**住宿酒店(全程同一家):**
{hotel_text}

**可选景点(已按到酒店的距离由近到远排序):**
{attraction_text or '无'}

**夜间可去景点(晚餐后安排用; 高德无营业时间数据, 此为"适合夜游"的代理筛选结果):**
{night_text or '无(当晚不安排夜间行程)'}

**天气信息:**
{weather_text or '无'}
"""
        if request.free_text_input:
            query += f"\n**额外要求:** {request.free_text_input}\n"

        # RAG 增强: 检索城市旅游知识 + 相似历史行程, 注入 prompt 作为参考。
        # 知识库让行程更贴合当地实际(门票/交通/避坑), 历史行程让风格更稳定。
        # RAG 未启用或检索失败时跳过, 不影响正常生成。
        try:
            from ..services.rag_service import get_rag_service

            rag_context = get_rag_service().build_rag_context(request)
            if rag_context:
                query += f"\n\n{rag_context}\n"
        except Exception as e:
            logger.warning(f"⚠️ RAG 上下文注入失败(不影响生成): {e}")

        query += "\n请严格按照 system 中定义的 JSON 结构输出完整 JSON。"
        return query

    @staticmethod
    def _pois_to_text(pois: List[POIInfo]) -> str:
        """POI列表转为可读文本

        带上评分、人均消费与**到酒店的距离**。距离必须写出来:
        实测只排序不给距离数字时, LLM 看不到远近差异, 仍会挑到城市另一头的景点。
        同时附上坐标, 让 LLM 输出的 location 用真实值。
        """
        lines = []
        for i, poi in enumerate(pois, 1):
            coord = f"{poi.location.longitude},{poi.location.latitude}" if poi.location else ""
            parts = [f"{i}. {poi.name}"]
            # 到酒店的距离(由 _rank_attractions_by_hotel 写入)
            dist = getattr(poi, "_hotel_distance_m", None)
            if dist is not None:
                parts.append(f"距酒店 {dist / 1000:.1f}km")
            if poi.rating is not None:
                parts.append(f"评分 {poi.rating}")
            if poi.cost is not None:
                parts.append(f"人均 ¥{poi.cost:.0f}")
            if poi.cuisine:
                parts.append(f"类型 {poi.cuisine}")
            if coord:
                parts.append(f"坐标 {coord}")
            if poi.address:
                parts.append(f"地址 {poi.address}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    @staticmethod
    def _weather_to_text(weather_list: List[WeatherInfo]) -> str:
        """天气信息列表转为可读文本"""
        lines = []
        for w in weather_list:
            lines.append(
                f"{w.date}: 白天{w.day_weather} {w.day_temp}°C / 夜间{w.night_weather} {w.night_temp}°C, 风向{w.wind_direction} {w.wind_power}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_fallback_budget(
        request: TripRequest,
        days: List[DayPlan],
    ) -> Budget:
        """按 config 的单价口径兜底计算预算

        计价口径集中放在 config, 不再用 50/150/400 这种全档统一的固定值:
        - 餐饮按餐段区分 (早餐/午餐/晚餐人均差距很大)
        - 酒店按住宿档次取价位区间中值 (经济型与豪华酒店不该同一个价)
        行程已有实际费用时优先采信实际值, 缺失项才用配置单价兜底。
        """
        settings = get_settings()

        def meal_unit(meal_type: str) -> int:
            return settings.budget_meal_cost.get(
                meal_type, settings.budget_meal_cost_default
            )

        total_attractions = sum(a.ticket_price for d in days for a in d.attractions)
        total_meals = sum(m.estimated_cost for d in days for m in d.meals)
        total_hotels = sum(
            d.hotel.estimated_cost for d in days if d.hotel and d.hotel.estimated_cost
        )

        # 酒店兜底: 优先用首页滑块指定的价位区间中值; 未指定则用住宿档次的参考区间
        if request.hotel_price_range and len(request.hotel_price_range) == 2:
            low, high = request.hotel_price_range
            hotel_source = "首页指定区间"
        else:
            low, high = get_hotel_service().get_price_range(request.accommodation)
            hotel_source = f"{request.accommodation}档次参考区间"
        hotel_unit = (
            int((low + high) / 2)
            if high > low
            else settings.budget_hotel_per_night_default
        )

        total_attractions = total_attractions or 200
        if not total_meals:
            # 按每天午晚两餐估算(早餐已排除)
            total_meals = sum(meal_unit(t) for t in ("lunch", "dinner")) * request.travel_days
        total_hotels = total_hotels or hotel_unit * request.travel_days
        logger.info(f"   💰 酒店预算单价 ¥{hotel_unit}/晚 (来源: {hotel_source})")
        total_transportation = settings.budget_transport_per_day * request.travel_days

        return Budget(
            total_attractions=total_attractions,
            total_hotels=total_hotels,
            total_meals=total_meals,
            total_transportation=total_transportation,
            total=total_attractions + total_hotels + total_meals + total_transportation,
        )

    # ============ 每日行程距离优化 ============

    @staticmethod
    def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        """两点球面距离(米)"""
        radius = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = phi2 - phi1
        d_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(d_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        )
        return 2 * radius * math.asin(math.sqrt(a))

    @classmethod
    def _route_length(cls, items: List[Attraction]) -> float:
        """按给定顺序串起各景点的总路程(米); 缺坐标的项按0处理"""
        total = 0.0
        pts = [
            (a.location.longitude, a.location.latitude)
            for a in items
            if a.location and (a.location.longitude or a.location.latitude)
        ]
        for i in range(len(pts) - 1):
            total += cls._haversine_m(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        return total

    def _optimize_itinerary_distance(self, trip_plan: TripPlan) -> TripPlan:
        """按距离就近重排每日景点(最近邻法)

        适配分时段结构: **每个时段独立重排**(上午内部、下午内部),
        不跨时段搬运 —— 否则上午的景点可能被挪到下午, 打乱时间安排。

        只调整访问顺序, 不增删景点; 改善不足配置阈值时保留原顺序。
        """
        settings = get_settings()
        if not settings.itinerary_optimize_distance:
            return trip_plan

        # 各时段字段名
        slots = ("attractions_morning", "attractions_afternoon", "attractions_evening")

        for day in trip_plan.days:
            for slot in slots:
                items = getattr(day, slot)
                if len(items) < 3:
                    continue  # 少于3个点无需优化

                original = list(items)
                before = self._route_length(original)
                if before <= 0:
                    continue

                ordered = self._nearest_neighbor_order(original)
                after = self._route_length(ordered)
                gain = (before - after) / before if before else 0.0

                if gain >= settings.itinerary_optimize_min_gain:
                    logger.info(
                        f"   🚶 第{day.day_index + 1}天 {slot} 按距离重排: "
                        f"{before / 1000:.1f}km -> {after / 1000:.1f}km (省{gain * 100:.0f}%)"
                    )
                    setattr(day, slot, ordered)

        return trip_plan

    def _nearest_neighbor_order(self, items: List[Attraction]) -> List[Attraction]:
        """最近邻排序(固定首个点为起点, 每次挑最近的未访问点)"""
        remaining = list(items[1:])
        ordered = [items[0]]
        while remaining:
            cur = ordered[-1]
            cur_loc = cur.location
            if not cur_loc or (not cur_loc.longitude and not cur_loc.latitude):
                ordered.append(remaining.pop(0))
                continue

            def dist_to(a: Attraction) -> float:
                loc = a.location
                if not loc or (not loc.longitude and not loc.latitude):
                    return float("inf")
                return self._haversine_m(
                    cur_loc.longitude, cur_loc.latitude, loc.longitude, loc.latitude
                )

            nearest_idx = min(range(len(remaining)), key=lambda i: dist_to(remaining[i]))
            ordered.append(remaining.pop(nearest_idx))
        return ordered

    def _dedupe_attractions(self, trip_plan: TripPlan) -> TripPlan:
        """全行程景点去重 (同一景点只保留首次出现)

        为什么需要: 日间与夜间是两次独立检索, 可能返回同一景点; LLM 也可能把
        同一景点排进多个时段或不同天(实测出现过)。提示词虽已要求不重复,
        但不能只依赖 LLM 服从, 这里做硬保证。

        保留"首次出现"而直接删, 避免某天/某时段被清空 ——
        若删完某时段为空, 该字段即空数组(前端会跳过该时段渲染)。
        """
        seen: set = set()
        removed = 0
        for day in trip_plan.days:
            for slot in ("attractions_morning", "attractions_afternoon", "attractions_evening"):
                kept = []
                for attr in getattr(day, slot):
                    key = (attr.name or "").strip()
                    if not key:
                        kept.append(attr)
                        continue
                    if key in seen:
                        removed += 1
                        continue
                    seen.add(key)
                    kept.append(attr)
                setattr(day, slot, kept)

        if removed:
            logger.info(f"   🧹 全行程景点去重: 移除 {removed} 个重复景点")
        return trip_plan

    def _ensure_famous_per_day(self, trip_plan: TripPlan, state: GraphState) -> TripPlan:
        """保证每天至少有一个"知名景点"(榜单命中的名胜)

        用户反馈过"行程里没有名胜"。虽然实测那次的根因是旧代码, 但这类结果不该
        靠运气 —— 尤其在小城市或偏好很窄时, 候选池可能确实缺少知名景点。
        这里做保底: 某天若一个榜单景点都没有, 就用**尚未使用**的榜单景点替换
        该天一个普通景点(优先替换白天的普通项, 保留夜间安排)。

        只在候选池里确实存在知名景点时才动手; 若池中没有(候选耗尽或小城市),
        保持原样, 不强塞。
        """
        if not self.settings.itinerary_ensure_famous_per_day:
            return trip_plan

        famous_pool = state.get("famous_attraction_pois") or []
        if not famous_pool:
            return trip_plan

        used = {
            (a.name or "").strip()
            for d in trip_plan.days
            for a in (d.attractions_morning + d.attractions_afternoon + d.attractions_evening)
        }
        available = [p for p in famous_pool if (p.name or "").strip() not in used]
        if not available:
            return trip_plan

        fixed = 0
        for day in trip_plan.days:
            day_names = {
                (a.name or "").strip()
                for a in (day.attractions_morning + day.attractions_afternoon + day.attractions_evening)
            }
            if day_names & self._famous_names:
                continue  # 该天已有知名景点
            if not available:
                break

            # 优先替换下午最后一个普通景点, 否则上午
            for slot in ("attractions_afternoon", "attractions_morning"):
                items = getattr(day, slot)
                if not items:
                    continue
                poi = available.pop(0)
                items[-1] = Attraction(
                    name=poi.name,
                    address=poi.address or trip_plan.city,
                    location=poi.location or Location(longitude=0, latitude=0),
                    visit_duration=120,
                    description=(
                        f"{poi.name}是本城知名景点"
                        f"（命中景点榜单：{'/'.join(self.settings.attraction_ranking_keywords)}）。"
                    ),
                    category=poi.cuisine or "景点",
                    rating=poi.rating,
                )
                fixed += 1
                break

        if fixed:
            logger.info(f"   🏆 知名景点保底: 为 {fixed} 天补入名胜")
        return trip_plan

    def _ensure_slot_counts(self, trip_plan: TripPlan, state: GraphState) -> TripPlan:
        """补齐上午/下午的景点数量, 使每段达到配置值(默认各2个)

        为什么需要: 即使提示词要求"上午恰好2个、下午恰好2个", 后续处理仍可能
        把某段削到1个 —— 全行程去重会删掉重复项、知名景点保底会用替换的方式
        挤掉一项。用户反馈过"上下午行程有些只有一个", 故这里做数量兜底。

        补齐来源: 该天的**夜间候选池**(与白天景点不重叠, 因已预留)优先进攻,
        其次用白天候选池中尚未使用的景点。二者都按距酒店远近排序, 保持顺路。
        若候选确实耗尽则保持原状(不强凑重复景点)。
        """
        target = self.settings.day_slot_attractions
        day_pool = state.get("attraction_pois") or []
        night_pool = state.get("night_attraction_pois") or []

        filled = 0
        for day in trip_plan.days:
            for slot in ("attractions_morning", "attractions_afternoon"):
                items = getattr(day, slot)
                if len(items) >= target:
                    continue

                used = {
                    (a.name or "").strip()
                    for d in trip_plan.days
                    for a in (d.attractions_morning + d.attractions_afternoon + d.attractions_evening)
                }
                # 备考来源: 白天候选池 + 夜间候选池(后者通常未被白天占用)
                candidates = [p for p in (day_pool + night_pool)
                              if (p.name or "").strip() and (p.name or "").strip() not in used]
                # 去重后按评分降序(池子已按距酒店排序, 这里优先取质量高的)
                seen_names = set()
                uniq = []
                for p in candidates:
                    nm = (p.name or "").strip()
                    if nm in seen_names:
                        continue
                    seen_names.add(nm)
                    uniq.append(p)
                uniq.sort(key=lambda p: (p.rating or 0), reverse=True)

                while len(items) < target and uniq:
                    poi = uniq.pop(0)
                    items.append(Attraction(
                        name=poi.name,
                        address=poi.address or trip_plan.city,
                        location=poi.location or Location(longitude=0, latitude=0),
                        visit_duration=120,
                        description=f"{poi.name}（据高德POI数据补充）。",
                        category=poi.cuisine or "景点",
                        rating=poi.rating,
                    ))
                    filled += 1

        if filled:
            logger.info(f"   📐 上午/下午景点补齐: 新增 {filled} 个(每段目标 {target} 个)")
        return trip_plan

    def _ensure_evening_plans(self, trip_plan: TripPlan, state: GraphState) -> TripPlan:
        """保证每天都有夜间行程, 且每天数量符合配置(默认1个)

        用户要求"每天都安排夜间游览", 同时"夜间行程一天一个就够"。
        提示词已明确要求, 但 LLM 未必照做(实测会留空或给2个), 故这里做硬保证:
            - 多于配置数量的: 裁掉多余的
            - 为空的: 从尚未使用的夜间候选里补一个
        只使用尚未被使用的夜间候选, 避免与白天景点重复
        (去重已先行执行, 这里只需避开已用名称)。候选耗尽则跳过该天。
        """
        night_pool = state.get("night_attraction_pois") or []
        per_day = self.settings.night_attractions_per_day

        # 先裁掉多余的, 使每天不超过配置数量
        trimmed = 0
        for day in trip_plan.days:
            if len(day.attractions_evening) > per_day:
                trimmed += len(day.attractions_evening) - per_day
                day.attractions_evening = day.attractions_evening[:per_day]
        if trimmed:
            logger.info(f"   🌙 夜间行程裁剪: 移除 {trimmed} 个(每天限 {per_day} 个)")

        if not night_pool:
            return trip_plan

        used = {
            (a.name or "").strip()
            for d in trip_plan.days
            for a in (d.attractions_morning + d.attractions_afternoon + d.attractions_evening)
        }
        available = [p for p in night_pool if (p.name or "").strip() not in used]

        filled = 0
        for day in trip_plan.days:
            if day.attractions_evening:
                continue
            if not available:
                break
            poi = available.pop(0)
            day.attractions_evening = [
                Attraction(
                    name=poi.name,
                    address=poi.address or trip_plan.city,
                    location=poi.location or Location(longitude=0, latitude=0),
                    visit_duration=90,
                    description=f"{poi.name}适合夜间游览（夜景/灯光/夜市氛围）。",
                    category=poi.cuisine or "景点",
                    rating=poi.rating,
                )
            ]
            day.evening_desc = day.evening_desc or f"晚餐后前往{poi.name}夜游"
            filled += 1

        if filled:
            logger.info(f"   🌙 自动补充夜间行程: {filled} 天")
        return trip_plan

    def _apply_selected_hotel(self, trip_plan: TripPlan, request: TripRequest) -> TripPlan:
        """把用户选定的酒店填到每一天(全程只住这一家)

        用户要求"接下来的旅行只住这一个酒店"。这里直接覆盖, 不依赖 LLM 服从
        提示词 —— 保证结果确定。

        未选酒店时(直接调接口的场景)保留 LLM 输出, 不做覆盖。
        """
        if not request.hotel:
            logger.info("   ℹ️ 未指定酒店, 沿用 LLM 生成的住宿安排")
            return trip_plan

        h = request.hotel
        # 住宿预算: 取档次参考区间中值(高德不提供真实房价)
        price_range = request.hotel_price_range or []
        estimated = (
            int((price_range[0] + price_range[1]) / 2) if len(price_range) == 2 else 0
        )
        price_text = (
            f"参考¥{price_range[0]}-{price_range[1]}/晚(档次估算)" if len(price_range) == 2 else ""
        )

        hotel = Hotel(
            name=h.name,
            address=h.address,
            location=h.location,
            price_range=price_text,
            rating=str(h.rating) if h.rating is not None else "",
            distance="",
            type=h.type or h.tier or request.accommodation,
            estimated_cost=estimated,
        )

        for day in trip_plan.days:
            day.hotel = hotel
            day.accommodation = f"{h.name}({h.type or request.accommodation})"

        logger.info(f"   🏨 已填充全程住宿: {h.name}")
        return trip_plan

    def _ensure_budget(self, trip_plan: TripPlan, request: TripRequest) -> TripPlan:
        """若行程计划缺少预算, 按实际费用自动计算补齐"""
        if trip_plan.budget is not None:
            return trip_plan

        trip_plan.budget = self._build_fallback_budget(request, trip_plan.days)
        return trip_plan

    def _create_fallback_plan(self, request: TripRequest) -> TripPlan:
        """创建备用计划(当Agent失败时)"""
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")

        def mk_attr(label: str, idx: int, offset: float) -> Attraction:
            return Attraction(
                name=f"{request.city}{label}{idx + 1}",
                address=f"{request.city}市",
                location=Location(
                    longitude=116.4 + offset + idx * 0.005,
                    latitude=39.9 + offset + idx * 0.005,
                ),
                visit_duration=120,
                description=f"这是{request.city}的著名景点",
                category="景点",
            )

        days = []
        for i in range(request.travel_days):
            current_date = start_date + timedelta(days=i)
            offset = i * 0.01
            morning = [mk_attr("上午景点", j, offset) for j in range(2)]
            afternoon = [mk_attr("下午景点", j, offset + 0.02) for j in range(2)]

            day = DayPlan(
                date=current_date.strftime("%Y-%m-%d"),
                day_index=i,
                description=f"第{i+1}天行程",
                transportation=request.transportation,
                accommodation=request.accommodation,
                morning_desc=f"第{i+1}天上午游览",
                afternoon_desc=f"第{i+1}天下午游览",
                evening_desc="",
                attractions_morning=morning,
                attractions_afternoon=afternoon,
                attractions_evening=[],
                meals=[
                    Meal(type="lunch", name="待选择", description=f"第{i+1}天午餐, 可从景点周边候选餐厅中选择", estimated_cost=50),
                    Meal(type="dinner", name="待选择", description=f"第{i+1}天晚餐, 可从景点周边候选餐厅中选择", estimated_cost=80),
                ],
            )
            day.merge_attractions()
            days.append(day)

        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=[],
            overall_suggestions=f"这是为您规划的{request.city}{request.travel_days}日游行程,建议提前查看各景点的开放时间。",
            budget=self._build_fallback_budget(request, days),
        )


# 全局多智能体系统实例
_multi_agent_planner = None


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    """获取多智能体旅行规划系统实例(单例模式)"""
    global _multi_agent_planner

    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTripPlanner()

    return _multi_agent_planner
