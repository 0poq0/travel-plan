"""酒店选择服务 (按住宿档次筛选 · 基于真实可得字段)

【重要限制 - 实测确认, 不要被代码里的"价位区间"误导】
高德 POI 接口**不提供酒店价格**:
    biz_ext.cost            恒为 []
    biz_ext.lowest_price    恒为 []
    详情接口全字段扫描无任何价格语义字段
只有餐饮类 POI 的 biz_ext.cost 才有人均消费值。
所以"按价位区间筛选酒店"在物理上做不到 —— config 里的 hotel_price_ranges
**只用于预算估算**(给出该档次的参考价位), 不参与真实筛选。

真实可用的档次信号是:
    1. type 字段末级类目 —— "经济型连锁酒店" / "五星级宾馆" / "旅馆招待所" 等
    2. biz_ext.rating    —— 评分, 覆盖率 100%
故本服务按"类型关键词吻合度 + 评分"筛选排序, 并对不吻合档次的酒店降权。
降权而非直接剔除: 实测 45% 的酒店 type 只是泛泛的"宾馆酒店", 信息量为零,
硬性剔除会把结果砍到几乎没有。
"""

import logging
from typing import Dict, List, Optional, Tuple

from ..config import get_settings
from ..models.schemas import POIInfo
from .amap_service import get_amap_service

logger = logging.getLogger(__name__)

# 高德住宿服务大类编码
_AMAP_HOTEL_TYPES = "100000"

# 召回页数: 住宿POI比餐饮少, 2页≈50家足够筛选
_HOTEL_PAGES = 2

# 综合分权重: 评分主导, 档次吻合度次之
_W_RATING = 0.7
_W_TIER = 0.3


class HotelService:
    """酒店候选服务(单例)"""

    def __init__(self):
        self.settings = get_settings()
        self.amap = get_amap_service()

    def get_price_range(self, accommodation: str) -> List[int]:
        """取某住宿档次的**参考**价位区间 [最低, 最高] 元/晚

        注意: 这是预算估算用的参考区间, 不是筛选条件 ——
        高德不提供酒店价格, 无法据此过滤真实酒店。
        """
        ranges: Dict[str, List[int]] = self.settings.hotel_price_ranges
        if accommodation in ranges:
            return ranges[accommodation]
        # 模糊匹配: "经济型酒店"/"经济" 这类都能命中
        for tier, rng in ranges.items():
            if tier and (tier in accommodation or accommodation in tier):
                return rng
        return list(self.settings.hotel_price_range_default)

    def _tier_keywords(self, accommodation: str) -> List[str]:
        """取该档次对应的类型关键词"""
        mapping: Dict[str, List[str]] = self.settings.hotel_tier_type_keywords
        if accommodation in mapping:
            return mapping[accommodation]
        for tier, kws in mapping.items():
            if tier and (tier in accommodation or accommodation in tier):
                return kws
        return []

    def _tier_fit(self, poi: POIInfo, keywords: List[str]) -> Optional[bool]:
        """酒店档次是否吻合所选档次

        只比对 type 的**末级类目**, 例如 "住宿服务;宾馆酒店;经济型连锁酒店"
        取 "经济型连锁酒店"。若拿关键词去子串匹配整串, 中类"宾馆酒店"
        (几乎出现在所有酒店里)会把经济型连锁店误判成舒适型。

        Returns:
            True=吻合, False=明确属于其他档次, None=类型信息不足(判断不了)
        """
        if not keywords:
            return None
        last = poi.cuisine  # POIInfo.cuisine 即 type 的末级类目
        if not last:
            return None
        if any(kw in last for kw in keywords):
            return True
        # 明确属于其他档次的末级类目 -> 判定为不吻合
        other_kws = [
            kw
            for tier, kws in self.settings.hotel_tier_type_keywords.items()
            for kw in kws
        ]
        if any(kw in last for kw in other_kws):
            return False
        return None  # 例如"住宿服务相关", 无从判断

    def search_hotels(
        self,
        accommodation: str,
        city: str,
        top_n: int = 5,
    ) -> List[POIInfo]:
        """按住宿档次搜索并排序酒店

        Args:
            accommodation: 住宿偏好, 如 "经济型酒店"
            city: 城市
            top_n: 返回条数

        Returns:
            按综合分降序排列的酒店POI列表
        """
        low, high = self.get_price_range(accommodation)
        keywords = self._tier_keywords(accommodation)
        logger.info(
            f"🏨 酒店筛选: 档次={accommodation} 参考价位=¥{low}-{high} "
            f"(高德无酒店价格, 价位仅供预算估算)"
        )

        try:
            # 用中性词广搜住宿POI, 再按末级类目分档。
            # 不用档次词当关键词: 实测搜"豪华酒店"只召回50家且仅1家真五星。
            pois = self.amap.search_poi_pages_typed(
                keywords=self.settings.hotel_search_keywords,
                city=city,
                types=_AMAP_HOTEL_TYPES,
                pages=4,
                offset=25,
            )
        except Exception as e:
            logger.warning(f"   ⚠️  酒店搜索失败: {e}")
            return []

        logger.info(f"   召回 {len(pois)} 家")

        # 补一轮档次定向召回: 广搜池里小众档次(尤其民宿)可能几乎没有吻合项,
        # 导致结果被无关酒店填满(实测民宿档出现过 0 家吻合、全是住宿服务相关)。
        # 这里用档次词再搜一轮并入池, 由下面的分流逻辑统一处理。
        if accommodation:
            try:
                extra = self.amap.search_poi_pages_typed(
                    keywords=accommodation,
                    city=city,
                    types=_AMAP_HOTEL_TYPES,
                    pages=2,
                    offset=25,
                )
                if extra:
                    logger.info(f"   档次定向召回补充 {len(extra)} 家")
                    pois.extend(extra)
            except Exception as e:
                logger.warning(f"   ⚠️  档次定向召回失败(不影响主流程): {e}")

        # 去重: 实测分页召回时同一 POI 会跨页重复返回
        # (如"北京京通宾馆"出现3次、"希尔顿欢朋"出现2次), 必须按 id 去重
        deduped: Dict[str, POIInfo] = {}
        for poi in pois:
            if not poi.id:
                continue
            deduped.setdefault(poi.id, poi)
        if len(deduped) != len(pois):
            logger.info(f"   去重后 {len(deduped)} 家 (原始 {len(pois)} 家)")
        pois = list(deduped.values())

        # 档次分流: 吻合的进入主榜, 类型信息不足的只用于补位,
        # 明确属于其他档次的按配置剔除。否则"豪华酒店"里会混进如家、青年酒店。
        matched: List[Tuple[POIInfo, float]] = []
        unknown: List[Tuple[POIInfo, float]] = []
        dropped_rating = 0
        dropped_tier = 0
        for poi in pois:
            if poi.rating is not None and poi.rating < self.settings.hotel_rating_min:
                dropped_rating += 1
                continue
            fit = self._tier_fit(poi, keywords)
            if fit is False and self.settings.hotel_drop_tier_mismatch:
                dropped_tier += 1
                continue
            entry = (poi, self._score(poi, fit))
            (matched if fit is True else unknown).append(entry)

        logger.info(
            f"   档次分流: 吻合 {len(matched)} 家 / 类型未知 {len(unknown)} 家 "
            f"(评分过低剔除 {dropped_rating}, 档次不符剔除 {dropped_tier})"
        )

        # 先排吻合的, 不够再用类型未知的补位。
        # 注意: 这些"未知"酒店类型只是泛泛的"住宿服务相关", 很可能是低档次,
        # 塞进豪华档可能名不副实 —— 但没有更可靠的判据能进一步区分,
        # 故仍用于补位, 并与吻合项区分(前端可据此提示)。
        matched.sort(key=lambda x: x[1], reverse=True)
        unknown.sort(key=lambda x: x[1], reverse=True)

        result = [poi for poi, _ in matched[:top_n]]
        remaining = top_n - len(result)
        if remaining > 0:
            filled = [poi for poi, _ in unknown[:remaining]]
            if filled:
                logger.info(
                    f"   其中 {len(filled)} 家 type 信息不足, 作为补位返回(档次不确定)"
                )
            result.extend(filled)
        return result

    def _score(self, poi: POIInfo, tier_fit: Optional[bool]) -> float:
        """综合分 = 评分归一化×0.7 + 档次吻合度×0.3"""
        rating_score = min(max((poi.rating or 0) / 5.0, 0.0), 1.0)

        s = self.settings
        if tier_fit is True:
            tier_score = s.hotel_tier_match_bonus
        elif tier_fit is False:
            tier_score = s.hotel_tier_mismatch_penalty
        else:
            tier_score = 0.0  # 类型信息不足, 不加不减

        return rating_score * _W_RATING + tier_score * _W_TIER

    def list_hotels_by_tier(
        self,
        tier: str,
        city: str,
        limit: int = 30,
    ) -> dict:
        """列出某住宿档次的酒店 (供"选择酒店"页展示)

        返回结果带坐标, 前端据此在地图上标出所有酒店。

        Args:
            tier: 住宿档次, 如 "经济型酒店"
            city: 城市
            limit: 返回条数上限

        Returns:
            dict: hotels / total / tier / price_range(参考)
        """
        hotels = self.search_hotels(accommodation=tier, city=city, top_n=limit)

        # 只返回有坐标的酒店; 没有坐标的无法在地图上标点
        items = []
        no_location = 0
        for h in hotels:
            loc = h.location
            if not loc or (not loc.longitude and not loc.latitude):
                no_location += 1
            items.append({
                "poi_id": h.id,
                "name": h.name,
                "address": h.address,
                "type": h.cuisine,
                "rating": h.rating,
                "location": (
                    {"longitude": loc.longitude, "latitude": loc.latitude}
                    if loc and (loc.longitude or loc.latitude) else None
                ),
            })

        return {
            "tier": tier,
            "city": city,
            "total": len(items),
            "hotels": items,
            "price_range": self.get_price_range(tier),
            "no_location": no_location,
            "notice": (
                "高德接口不提供酒店实际房价, 仅提供名称/类型/评分/坐标; "
                "价位区间为该档次的参考估算值。"
            ),
        }

    def describe(self, poi: POIInfo, accommodation: str) -> str:
        """把酒店POI转成一行可读文本(供 LLM 参考与前端展示)

        如实说明"价格未知"而不是编一个价格 —— 高德不提供酒店价格。
        """
        low, high = self.get_price_range(accommodation)
        rating = f"{poi.rating}分" if poi.rating is not None else "无评分"
        parts = [poi.name, poi.type or "住宿"]
        parts.append(f"评分: {rating}")
        parts.append(f"参考价位: ¥{low}-{high}/晚(按所选档次估算, 高德不提供实际房价)")
        if poi.address:
            parts.append(f"地址: {poi.address}")
        if poi.location and (poi.location.longitude or poi.location.latitude):
            parts.append(f"坐标: {poi.location.longitude},{poi.location.latitude}")
        return " | ".join(parts)


# 全局单例
_hotel_service: Optional[HotelService] = None


def get_hotel_service() -> HotelService:
    """获取酒店服务实例(单例模式)"""
    global _hotel_service
    if _hotel_service is None:
        _hotel_service = HotelService()
    return _hotel_service
