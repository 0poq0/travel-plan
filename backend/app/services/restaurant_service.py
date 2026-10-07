"""餐厅推荐服务 (景点周边 · 榜单近似口径)

【重要口径声明】
高德"扫街榜"没有对外开放 API, 无法获取官方榜单排名。本模块的做法是:
用榜单词(状元榜 / 本地人爱去 / 烟火小店)作为**召回信号**去搜高德 POI,
再按 config 中可调的权重自行打分排序。结果属于"近似口径",
不等价于高德 App 内扫街榜的真实排名, 前端需如实标注。

工作流:
    三路榜单词召回(城市级) + 锚点周边搜索(景点级)
        → 按 poi_id 合并去重、记录命中的榜单词
        → 硬过滤(排除烧烤 / 丢弃无评分无价格 / 评分下限)
        → 加权打分(评分 / 距离 / 菜系 / 榜单加分 / 连锁降权)
        → 缓存候选池, 按价位区间过滤后返回 Top N

缓存设计:
    候选池按 "城市+锚点+餐段" 缓存(含得分明细)。用户拖价位滑块时只是
    在内存里重新过滤排序, 不会再次请求高德 —— 个人 key 只有约 3-5 QPS,
    不缓存的话拖一次滑块就会把配额打爆(项目里 poi.py 的节流代码就是这么来的)。
"""

import logging
import math
import threading
import time
from typing import Dict, List, Optional, Tuple, Union

from ..config import get_settings
from ..models.schemas import Location, POIInfo, RestaurantCandidate
from .amap_service import get_amap_service

logger = logging.getLogger(__name__)

# 高德餐饮大类编码 (place/around 与 place/text 的类型过滤都用它)
_AMAP_FOOD_TYPES = "050000"

# 榜单词召回时翻页数: 实测 offset=25 时最多约4页有效, 第10页返回空
_LIST_PAGES = 4

# 周边搜索翻页数(每页25条), 2页≈50家锚点附近的店, 够覆盖午晚两餐
_AROUND_PAGES = 2

# 距离衰减尺度(米): 指数衰减的距离常数。
# 用 800m 而不是搜索半径 2000m —— 因为吃午饭的合理半径就是几百米,
# 而线性衰减会把"2km"和"27km"算成差不多的分(实测因此让24公里外的店进了推荐榜)。
_DISTANCE_SCALE = 800.0

# 超出这个距离直接不进候选池。被榜单词召回的店可能远在市郊
# (实测"阳坊涮肉·昌平沙河店"距故宫27公里), 对当天行程毫无意义。
_MAX_DISTANCE = 3000.0


def _haversine_meters(loc1: Location, loc2: Location) -> float:
    """两坐标间球面距离(米)

    高德周边搜索本身会返回 distance 字段, 这里只在缺失时兜底
    (例如同时被关键字搜索和周边搜索捞到、但取自关键字搜索那条记录时)。
    """
    radius = 6371000.0
    phi1, phi2 = math.radians(loc1.latitude), math.radians(loc2.latitude)
    d_phi = phi2 - phi1
    d_lambda = math.radians(loc2.longitude - loc1.longitude)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


class RestaurantService:
    """餐厅候选服务 (单例)

    只负责"给出候选列表", 不替用户做选择 —— 选择权交给前端。
    """

    def __init__(self):
        self.settings = get_settings()
        self.amap = get_amap_service()
        # 候选池缓存: key -> (expire_ts, pool, price_range)
        self._cache: Dict[str, Tuple[float, List[RestaurantCandidate], List[float]]] = {}
        self._cache_lock = threading.Lock()

    # ============ 对外主入口 ============

    def get_candidates(
        self,
        city: str,
        anchor: Optional[Location] = None,
        meal_type: str = "lunch",
        min_cost: Optional[float] = None,
        max_cost: Optional[float] = None,
    ) -> dict:
        """获取某餐段的餐厅候选列表

        餐厅位置只以**该餐用餐时所在的那一个景点**为基准(与酒店无关):
        调用方按餐段挑好景点坐标传进来(午餐=吃午饭时所在的景点,
        晚餐=当天最后一个景点), 这里只搜这一个锚点, 不做多景点聚合。

        Args:
            city: 城市
            anchor: 该餐对应的那一个景点坐标
            meal_type: 餐段 lunch/dinner (早餐已按需求排除)
            min_cost: 价位下限(人均元)
            max_cost: 价位上限(人均元)

        Returns:
            dict: candidates / total / cached / price_range / scope_notice
        """
        cache_key, cached, pool, price_range = self._get_pool(city, anchor, meal_type)

        filtered = [
            c for c in pool
            if (min_cost is None or (c.cost is not None and c.cost >= min_cost))
            and (max_cost is None or (c.cost is not None and c.cost <= max_cost))
        ]

        top_n = self.settings.restaurant_top_n
        return {
            "candidates": filtered[:top_n],
            "total": len(filtered),
            "pool_size": len(pool),
            "cached": cached,
            "price_range": price_range,
            "cache_key": cache_key,
            # 前端据此如实标注口径, 不含糊
            "scope_notice": (
                "榜单为近似口径: 用「"
                + " / ".join(self.settings.restaurant_list_keywords)
                + "」作为关键词召回高德真实POI数据后自行打分排序, "
                "非高德官方扫街榜排名; 评分/人均消费/招牌菜均为高德真实字段。"
                "餐厅位置以该餐用餐时所在的景点为基准。"
            ),
        }

    # ============ 候选池构建(带缓存) ============

    def _get_pool(
        self,
        city: str,
        anchor: Optional[Location],
        meal_type: str,
    ) -> Tuple[str, bool, List[RestaurantCandidate], List[float]]:
        """取候选池, 命中缓存则直接复用(不打高德)"""
        if anchor:
            anchor_key = f"{anchor.longitude:.4f},{anchor.latitude:.4f}"
        else:
            anchor_key = "none"
        cache_key = f"{city}|{anchor_key}|{meal_type}"

        now = time.time()
        with self._cache_lock:
            hit = self._cache.get(cache_key)
            if hit and hit[0] > now:
                return cache_key, True, hit[1], hit[2]

        pool, price_range = self._build_pool(city, anchor)
        with self._cache_lock:
            self._cache[cache_key] = (
                now + self.settings.restaurant_cache_ttl,
                pool,
                price_range,
            )
        return cache_key, False, pool, price_range

    def _build_pool(
        self, city: str, anchor: Optional[Location]
    ) -> Tuple[List[RestaurantCandidate], List[float]]:
        """召回 → 去重 → 硬过滤 → 打分 → 排序, 得到完整候选池"""
        merged: Dict[str, POIInfo] = {}
        hits: Dict[str, List[str]] = {}

        # ---- 1. 三路榜单词召回 (平行关系: 取并集, 而非交集) ----
        for word in self.settings.restaurant_list_keywords:
            try:
                pois = self.amap.search_poi_pages(
                    word, city, pages=_LIST_PAGES, offset=25
                )
                logger.info(f"   🏷️  榜单词「{word}」召回 {len(pois)} 家")
            except Exception as e:
                logger.warning(f"   ⚠️  榜单词「{word}」召回失败: {e}")
                continue
            for poi in pois:
                if not poi.id:
                    continue
                merged.setdefault(poi.id, poi)
                hits.setdefault(poi.id, [])
                if word not in hits[poi.id]:
                    hits[poi.id].append(word)

        # ---- 2. 景点周边召回 (距离信息只有这个接口给) ----
        # 每餐只搜一个锚点: 就是该餐用餐时所在的那一个景点。
        if anchor:
            location_str = f"{anchor.longitude},{anchor.latitude}"
            try:
                around = self.amap.search_poi_around(
                    location_str,
                    types=_AMAP_FOOD_TYPES,
                    radius=self.settings.restaurant_search_radius,
                    offset=25,
                    page=1,
                )
                logger.info(
                    f"   📍 景点周边({self.settings.restaurant_search_radius}m)召回 {len(around)} 家"
                )
                for poi in around:
                    if not poi.id:
                        continue
                    # 周边搜索带 distance, 优先用它的记录覆盖(距离更准)
                    if poi.id not in merged or poi.distance is not None:
                        merged[poi.id] = poi
                    hits.setdefault(poi.id, [])
            except Exception as e:
                logger.warning(f"   ⚠️  景点周边召回失败: {e}")

        logger.info(f"   📦 合并去重后候选池: {len(merged)} 家")

        # ---- 3. 硬过滤 + 打分 ----
        candidates: List[RestaurantCandidate] = []
        for poi_id, poi in merged.items():
            if self._is_banned(poi):
                continue
            if poi.rating is None or poi.rating < self.settings.restaurant_rating_min:
                continue
            # 按需求: 无人均消费数据的直接丢弃(价位筛选无法进行)
            if poi.cost is None or poi.cost <= 0:
                continue
            candidate = self._score(poi, anchor, hits.get(poi_id, []))
            candidates.append(candidate)

        # 距离上限过滤: 榜单词召回的是城市级结果, 可能包含市郊的店
        # (实测"阳坊涮肉·昌平沙河店"距故宫 27 公里), 对当天行程无意义。
        # 只在锚点已知时才过滤 —— 没有锚点就没有距离概念。
        if anchor:
            candidates = [
                c for c in candidates
                if c.distance is not None and c.distance <= _MAX_DISTANCE
            ]

        candidates.sort(key=lambda c: c.score, reverse=True)

        costs = [c.cost for c in candidates if c.cost is not None]
        price_range = [min(costs), max(costs)] if costs else [0.0, 0.0]

        logger.info(
            f"   ✅ 过滤后候选 {len(candidates)} 家, 人均区间 {price_range[0]:.0f}-{price_range[1]:.0f}元"
        )
        return candidates, price_range

    # ============ 过滤规则 ============

    def _is_banned(self, poi: POIInfo) -> bool:
        """是否应排除

        烧烤必须走 typecode 判定: 实测只按关键词搜"烧烤"会混进"烤肉"
        (拾也·烤肉放题 / 戈拿旺巴西烤肉 / 明洞阿姨韩式酱蟹烤肉),
        加 types=050400(烧烤) 才干净, 所以这里双重判定。
        """
        for prefix in self.settings.restaurant_ban_typecode_prefix:
            if poi.typecode.startswith(prefix):
                return True
        # typecode 可能是复合值, 如 "050117|050121", 逐段比对
        for code in poi.typecode.split("|"):
            for prefix in self.settings.restaurant_ban_typecode_prefix:
                if code.strip().startswith(prefix):
                    return True
        for kw in self.settings.restaurant_ban_keywords:
            if kw and kw in poi.name:
                return True
        return False

    # ============ 打分 ============

    def _score(
        self,
        poi: POIInfo,
        anchor: Optional[Location],
        list_hits: List[str],
    ) -> RestaurantCandidate:
        """综合打分

        得分 = rating*W + distance*W + cuisine*W + 榜单加分 - 连锁降权
        """
        s = self.settings

        # 1. 评分项: 归一化到 0-1 (5分制为满分)
        rating_score = min(max((poi.rating or 0) / 5.0, 0.0), 1.0)

        # 2. 距离项
        #    优先用高德周边搜索的 distance; 若是纯关键字召回的店(没有 distance),
        #    则用锚点坐标本地算 haversine —— 否则这些店会拿到"距离未知"的高分,
        #    导致 24 公里外的店反超锚点隔壁的店(实测确实发生了)。
        distance = poi.distance
        has_location = bool(
            poi.location and (poi.location.longitude or poi.location.latitude)
        )
        if distance is None and anchor and has_location:
            distance = int(_haversine_meters(anchor, poi.location))

        if distance is None:
            # 距离确实算不出来(无锚点且非周边搜索)时给 0 分:
            # 给中性分会让"信息缺失"变成优势, 属于逻辑倒挂。
            distance_score = 0.0
            proximity = 0.0
        else:
            # 指数衰减: 800m 尺度下 150m≈0.83, 500m≈0.54, 2km≈0.08, 3km≈0.02。
            # 这样"隔壁的店"能实打实压过"2公里外但上了榜的店"。
            distance_score = math.exp(-distance / _DISTANCE_SCALE)
            proximity = distance_score

        # 3. 菜系项: 地方菜/特色菜加分, 快餐/饮品减分
        cuisine = poi.cuisine
        cuisine_score = s.restaurant_cuisine_bonus.get(cuisine, 0.0)
        cuisine_score += s.restaurant_cuisine_penalty.get(cuisine, 0.0)

        # 4. 榜单加分: 平行关系, 命中多个取最大值(不累加)。
        #    关键: 榜单加分必须做"邻近度门控"。否则 0.25 的固定加分
        #    (>距离满分 0.20)会让市郊的上榜店反超锚点隔壁的店 —— 实测
        #    24 公里外的翠满楼就是这样挤进 Top8 的。
        #    但门控不能压太狠: 直接用 proximity 当系数时, 891m 处的门控只有
        #    0.33, 榜单加分被压到 0.033, 上榜店(方砖厂69号炸酱面)反而掉到
        #    纯靠距离的店后面, 榜单词等于白召回。所以用 0.6 保底 + 0.4 距离
        #    调制: 既保住榜单的区分度, 又不给远处的店免死金牌。
        list_bonus = 0.0
        for word in list_hits:
            list_bonus = max(list_bonus, s.restaurant_list_bonus.get(word, 0.0))
        list_bonus *= 0.6 + 0.4 * proximity

        # 5. 连锁降权 (老字号白名单豁免)
        chain_penalty = 0.0
        whitelisted = any(w in poi.name for w in s.restaurant_chain_whitelist)
        if not whitelisted:
            if any(kw in poi.name for kw in s.restaurant_chain_keywords):
                chain_penalty = s.restaurant_chain_penalty

        total = (
            rating_score * s.restaurant_weight_rating
            + distance_score * s.restaurant_weight_distance
            + cuisine_score * s.restaurant_weight_cuisine
            + list_bonus
            + chain_penalty
        )

        return RestaurantCandidate(
            poi_id=poi.id,
            name=poi.name,
            cuisine=cuisine,
            address=poi.address,
            location=poi.location,
            rating=poi.rating,
            cost=poi.cost,
            distance=distance,
            signature_dishes=poi.signature_dishes[:6],  # 只留前6个招牌菜, 前端别太挤
            list_hits=list_hits,
            business_area=poi.business_area,
            score=round(total, 4),
            score_detail={
                "rating": round(rating_score * s.restaurant_weight_rating, 4),
                "distance": round(distance_score * s.restaurant_weight_distance, 4),
                "cuisine": round(cuisine_score * s.restaurant_weight_cuisine, 4),
                "list_bonus": round(list_bonus, 4),
                "chain_penalty": round(chain_penalty, 4),
                "chain_whitelisted": whitelisted,
            },
        )

    # ============ 缓存维护 ============

    def clear_cache(self) -> int:
        """清空候选池缓存, 返回清掉的条目数 (调参后可用)"""
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
        return count


# 全局单例
_restaurant_service: Optional[RestaurantService] = None
_restaurant_lock = threading.Lock()


def get_restaurant_service() -> RestaurantService:
    """获取餐厅推荐服务实例(单例模式)"""
    global _restaurant_service
    if _restaurant_service is None:
        with _restaurant_lock:
            if _restaurant_service is None:
                _restaurant_service = RestaurantService()
    return _restaurant_service
