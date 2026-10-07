"""景点筛选服务 (编码白名单 + 硬排除黑名单)

【为什么需要这个模块】
原实现 `search_poi(preferences[0], city)` 直接把用户偏好词当关键词搜且不限类型:
    preference="美食" -> 返回全是餐厅(壹条龙涮肉/奥华餐厅/玺源居涮肉…)
    preference="购物" -> 返回全是商场
    preference="休闲" -> 返回 Blue Note酒吧/SPA/足道/洗浴中心
这些结果被拼进 prompt 的「可选景点」字段, LLM 便忠实照搬进每日景点,
于是"景点安排"里出现饭店 —— 根因在此, 不在 LLM。

【筛选策略】白名单为主, 黑名单强制否决:
1. 硬排除: typecode 命中黑名单前缀 或 名称命中排除词 -> 直接丢弃
   (实测编码: 餐饮 050xxx / KTV 080302 / 酒吧 080304 / 洗浴 071400)
2. 白名单: typecode 必须命中景点类前缀(1101/1102/1402/1403/1404/1405)
3. 评分下限过滤 (景点类POI只有 rating 可用, cost/tag 都不返回)
4. 剔除父POI的子POI (如"故宫博物院-午门"), 避免同一天重复安排同一景点

【红色景点必须保留】
烈士陵园/烈士之墓在高德里归入"生活服务;丧葬设施"(071900/071901),
若按类目名含"陵园"就排除会误杀。好在它们同时带 110210(红色景区) 或
110204(纪念馆), 因此按"编码前缀白名单"判定即可安全保留:
    白乙化烈士陵园  typecode=110210|071900  -> 保留
    马骏烈士之墓    typecode=071901|110210  -> 保留
"""

import logging
import random
from typing import Dict, List, Optional, Tuple

from ..config import get_settings
from ..models.schemas import Location, POIInfo
from .amap_service import get_amap_service

logger = logging.getLogger(__name__)

# 每个基础关键词翻页数 (实测 offset=25 时最多约4页有效)
_PAGES_PER_KEYWORD = 1

# 子POI识别: "故宫博物院-午门" 这类以父名+连字符+部件名构成。
# 用连字符且父名部分较长时判定为子POI。
_SUB_POI_SEPARATORS = ("-", "－", "·")


class AttractionService:
    """景点候选服务(单例)"""

    def __init__(self):
        self.settings = get_settings()
        self.amap = get_amap_service()
        # 最近一次 search_attractions 的榜单命中, 供调用方判断"哪些是知名景点"
        # (用于 _ensure_famous_per_day 保底, 避免行程里一个名胜都没有)。
        self.last_ranking_hits: Dict[str, List[str]] = {}
        self.last_ranking_pois: Dict[str, POIInfo] = {}

    # ============ 对外入口 ============

    def search_attractions(
        self,
        city: str,
        preferences: Optional[List[str]] = None,
        top_n: int = 20,
    ) -> List[POIInfo]:
        """按偏好搜索并筛选真实景点

        Args:
            city: 城市
            preferences: 用户偏好标签, 用于排序加权(不再直接当关键词)
            top_n: 返回条数上限

        Returns:
            经过白/黑名单筛选与排序的景点列表
        """
        preferences = preferences or []
        types = "|".join(self.settings.attraction_type_whitelist)

        # ---- 1. 中性关键词多路召回并合并去重 ----
        merged: Dict[str, POIInfo] = {}
        for kw in self.settings.attraction_base_keywords:
            try:
                pois = self.amap.search_poi_pages_typed(
                    keywords=kw,
                    city=city,
                    types=types,
                    pages=_PAGES_PER_KEYWORD,
                    offset=25,
                )
            except Exception as e:
                logger.warning(f"   ⚠️  景点召回「{kw}」失败: {e}")
                continue
            for poi in pois:
                if poi.id and poi.id not in merged:
                    merged[poi.id] = poi

        # 偏好词**不再作为召回关键词**。实测即便限定了景点类型:
        #   "美食" -> 甘肃厅 / 萨利宅院 / 雍和宫大街四十三号院 (无意义碎点)
        #   "休闲" -> 泰仙宫足道采耳养生 / 吉雅幸福时光精油禅院 (足道/精油店)
        # 后者的 typecode 带 110205(寺庙道观)/110200(风景名胜), 靠类型白名单
        # 拦不住, 只能从源头不搜。

        # ---- 1b. 偏好定向召回 ----
        # 基础关键词的池子里没有动物园/水族馆/游乐场这类 POI, 导致"动物世界"
        # "游乐场"偏好完全失效(实测返回的仍是通用高分景点)。这里按偏好对应的
        # 类型编码补一路定向召回, 保证该偏好的目标类目一定进入候选池。
        pref_codes = self.settings.attraction_preference_type_codes
        pref_keywords = self.settings.attraction_preference_search_keywords
        for pref in preferences:
            codes = pref_codes.get(pref)
            if not codes:
                continue
            # 关键词必须换成真实存在的场所类词: 实测 keywords="红色精神" 只召回 2 条,
            # 换成"红色景区|纪念馆|革命旧址|烈士"能召回 50 条。
            kw = pref_keywords.get(pref, pref)
            try:
                pois = self.amap.search_poi_pages_typed(
                    keywords=kw,
                    city=city,
                    types="|".join(codes),
                    pages=self.settings.attraction_preference_pages,
                    offset=25,
                )
            except Exception as e:
                logger.warning(f"   ⚠️  偏好「{pref}」定向召回失败: {e}")
                continue
            added = 0
            for poi in pois:
                if poi.id and poi.id not in merged:
                    merged[poi.id] = poi
                    added += 1
            logger.info(
                f"   🎯 偏好「{pref}」定向召回 +{added} 条 "
                f"(关键词 {kw} | 编码 {'|'.join(codes)})"
            )

        # ---- 1c. 景点状元榜召回 ----
        # 实测景点类 keywords="状元榜" 确实能召回上过榜的景点, 但数量很少
        # (北京仅 3 条: 故宫/雍和宫/北海公园), 故叠加同为榜单语义的"必玩榜"
        # (北京 23 条, 质量高: 故宫/环球度假区/颐和园/天坛/欢乐谷)。
        # 命中的景点在排序阶段获得榜单加分。
        # 注意: 餐厅侧的 restaurant_list_keywords 是独立配置, 二者互不影响。
        ranking_hits: Dict[str, List[str]] = {}
        for kw in self.settings.attraction_ranking_keywords:
            try:
                pois = self.amap.search_poi_pages_typed(
                    keywords=kw,
                    city=city,
                    types=types,
                    pages=self.settings.attraction_preference_pages,
                    offset=25,
                )
            except Exception as e:
                logger.warning(f"   ⚠️  景点榜单「{kw}」召回失败: {e}")
                continue
            added = 0
            for poi in pois:
                if not poi.id:
                    continue
                if poi.id not in merged:
                    merged[poi.id] = poi
                    added += 1
                ranking_hits.setdefault(poi.id, [])
                if kw not in ranking_hits[poi.id]:
                    ranking_hits[poi.id].append(kw)
            logger.info(
                f"   🏆 景点榜单「{kw}」召回 {len(pois)} 条 (新增 {added} 条)"
            )

        logger.info(f"   📥 景点候选池共 {len(merged)} 条")

        # ---- 2. 过滤 (父子剪枝 + 黑白名单 + 评分下限) ----
        # 复用 _filter_pool, 与夜间景点检索走完全相同的标准
        before = len(merged)
        kept = self._filter_pool(list(merged.values()))
        logger.info(f"   🔎 景点筛选: {before} -> {len(kept)} 条 (已排除子POI/餐饮娱乐/低评分)")

        # ---- 4. 偏好筛选 + 排序 ----
        # 指定了偏好时, 优先只给与偏好相关的景点(相关性门槛), 不足 top_n 才用
        # 通用高分景点补位。否则"动物世界"里会混进故宫、天坛这些无关景点
        # (实测发生过), 用户勾了偏好却看到一半无关内容。
        scored = [
            (p, self._preference_score(p, preferences, ranking_hits.get(p.id, [])))
            for p in kept
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        # 榜单命中情况记入日志, 便于确认"景点状元榜"是否真的起作用
        hit_count = sum(1 for p in kept if ranking_hits.get(p.id))
        # 保存榜单命中结果(供调用方判断知名景点)
        self.last_ranking_hits = {
            p.id: list(ranking_hits[p.id]) for p in kept if ranking_hits.get(p.id)
        }
        self.last_ranking_pois = {p.id: p for p in kept if ranking_hits.get(p.id)}
        if hit_count:
            top_hits = [
                f"{p.name}({'/'.join(ranking_hits[p.id])})"
                for p, _ in scored[:5]
                if ranking_hits.get(p.id)
            ]
            logger.info(f"   🏆 候选池中榜单景点 {hit_count} 条; 前5名含: {top_hits or '无'}")

        if preferences:
            relevant = [(p, s) for p, s in scored if self._is_preference_relevant(p, preferences)]
            relevant_ids = {id(p) for p, _ in relevant}

            # 关键: 不能"相关项够了就只用相关项", 那会把天坛/北海这类高分名胜
            # 整体排除在候选池外, LLM 连选项都看不到(实测问题)。
            # 为全城高分景点保留约 30% 名额 —— 偏好只影响排序, 不决定生死。
            keep_non_pref = max(1, int(top_n * self.settings.attraction_non_preference_ratio))
            others = [(p, s) for p, s in scored if id(p) not in relevant_ids]

            targeted = relevant[: top_n - keep_non_pref]
            filler = others[:keep_non_pref]
            ordered = targeted + filler

            # 名额没用满时(相关项或无关项不足), 用剩余高分项补足
            if len(ordered) < top_n:
                chosen_ids = {id(p) for p, _ in ordered}
                for p, s in scored:
                    if len(ordered) >= top_n:
                        break
                    if id(p) not in chosen_ids:
                        ordered.append((p, s))
                        chosen_ids.add(id(p))

            logger.info(
                f"   🎯 偏好相关 {len(relevant)} 条 → 取 {len(targeted)} 条; "
                f"另保留 {len(filler)} 个高分名胜(非偏好相关)以防关键景点被偏好门槛排除"
            )
            return [p for p, _ in ordered[:top_n]]

        return [p for p, _ in scored[:top_n]]

    def search_night_attractions(
        self,
        city: str,
        top_n: Optional[int] = None,
    ) -> List[POIInfo]:
        """检索"夜间可去"的景点

        【限制】高德免费接口不提供营业时间, 无法确知某景点晚上是否开门。
        这里用关键词代理(夜游/灯光秀/夜市)筛出"适合夜游"的景点,
        并复用与日间相同的黑白名单过滤(排除餐厅/KTV/酒吧/洗浴等),
        保证夜间安排里不会出现饭店或足疗店。
        """
        s = self.settings
        top_n = top_n or s.attraction_night_top_n
        types = "|".join(s.attraction_type_whitelist)

        merged: Dict[str, POIInfo] = {}
        for kw in s.attraction_night_keywords:
            try:
                pois = self.amap.search_poi_pages_typed(
                    keywords=kw,
                    city=city,
                    types=types,
                    pages=1,
                    offset=25,
                )
            except Exception as e:
                logger.warning(f"   ⚠️  夜间景点「{kw}」召回失败: {e}")
                continue
            for poi in pois:
                if poi.id and poi.id not in merged:
                    merged[poi.id] = poi
            logger.info(f"   🌙 夜间关键词「{kw}」召回 {len(pois)} 条")

        kept = self._filter_pool(list(merged.values()))
        kept.sort(key=lambda p: (p.rating or 0), reverse=True)
        result = kept[:top_n]
        logger.info(
            f"   🌙 夜间可去景点 {len(result)} 条: "
            f"{[p.name for p in result]}"
        )
        return result

    def _filter_pool(self, pois: List[POIInfo]) -> List[POIInfo]:
        """对候选池套用父子剪枝 + 黑白名单 + 评分下限

        抽成共用方法, 保证日间与夜间景点走完全相同的过滤标准
        (否则夜景里可能混进酒吧/餐厅)。
        """
        # 父子剪枝必须在其他过滤之前(否则父级被剔除后子项成孤儿, 剪不掉)
        pool = (
            self._drop_sub_pois(pois)
            if self.settings.attraction_drop_sub_poi
            else list(pois)
        )

        kept = []
        for poi in pool:
            if self._is_blacklisted(poi):
                continue
            if not self._in_whitelist(poi):
                continue
            if (
                poi.rating is not None
                and poi.rating < self.settings.attraction_rating_min
            ):
                continue
            kept.append(poi)

        # 过滤后二次剪枝: 清理父级被过滤剔除后产生的孤儿子项
        if self.settings.attraction_drop_sub_poi:
            kept = self._drop_sub_pois(kept)
        return kept

    def _is_preference_relevant(self, poi: POIInfo, preferences: List[str]) -> bool:
        """该景点是否与用户勾选的偏好相关"""
        s = self.settings
        codes = self._codes(poi)
        text = f"{poi.name} {poi.type}"
        for pref in preferences:
            pref_codes = s.attraction_preference_type_codes.get(pref, [])
            if pref_codes and any(c.startswith(pc) for c in codes for pc in pref_codes):
                return True
            for clue in s.attraction_preference_clues.get(pref, []):
                if clue and clue in text:
                    return True
        return False

    # ============ 过滤规则 ============

    @staticmethod
    def _codes(poi: POIInfo) -> List[str]:
        """POI 的 typecode 列表 (高德可能返回复合值 '110210|071900')"""
        if not poi.typecode:
            return []
        return [c.strip() for c in poi.typecode.split("|") if c.strip()]

    def _is_blacklisted(self, poi: POIInfo) -> bool:
        """硬排除: 类型编码命中黑名单, 或名称命中排除词

        优先级最高 —— 即使该 POI 同时带了景点类目(实测"荣喜堂·老北京涮肉"
        就同时带 风景名胜;风景名胜相关;旅游景点), 也要按饭店排除。
        """
        for code in self._codes(poi):
            for prefix in self.settings.attraction_type_blacklist:
                if code.startswith(prefix):
                    return True
        name = poi.name or ""
        return any(kw in name for kw in self.settings.attraction_name_blacklist)

    def _in_whitelist(self, poi: POIInfo) -> bool:
        """是否属于景点类目(typecode 前缀命中白名单)"""
        for code in self._codes(poi):
            for prefix in self.settings.attraction_type_whitelist:
                if code.startswith(prefix):
                    return True
        return False

    @staticmethod
    def _is_sub_poi(poi: POIInfo) -> bool:
        """是否为父POI的子POI, 如 "故宫博物院-午门" / "天坛公园-祈年殿"

        判定: 名称含分隔符, 且分隔符前部分不短(避免误伤 "什刹海-后海"
        这类本身即独立景点的名称 —— 那种父名部分较短, 保留)。
        """
        name = poi.name or ""
        for sep in _SUB_POI_SEPARATORS:
            if sep in name:
                head, _, tail = name.partition(sep)
                # 父名 >=4 字且子项是具体建筑/门/殿 -> 判为子POI
                if len(head) >= 4 and tail and len(tail) <= 8:
                    return True
        return False

    def _has_parent_in(self, poi: POIInfo, names: set) -> bool:
        """该POI是否是某个父景点的子项

        两种判定(任一成立即剔除):
        1. 父级在候选池中: 池里已有"天安门" -> 剔除"天安门-城楼"
        2. 后缀是结构性部件词: "中央美术学院-美术馆(花家地新馆)" 这类
           父级不在池中, 但后缀含"新馆/门/殿/馆"等部件词 -> 也剔除

        只按分隔符前部分精确匹配父名, 不做子串匹配, 避免误伤。
        """
        name = (poi.name or "").strip()
        suffixes = self.settings.attraction_sub_poi_suffixes
        for sep in _SUB_POI_SEPARATORS:
            if sep not in name:
                continue
            head, _, tail = name.partition(sep)
            head, tail = head.strip(), tail.strip()
            if not head or not tail:
                continue
            # 判定1: 父级在候选池中
            if len(head) >= 2 and head in names and head != name:
                return True
            # 判定2: 后缀是结构性部件词
            if any(suf and suf in tail for suf in suffixes):
                return True
        return False

    @classmethod
    def _drop_sub_pois(cls, pois: List[POIInfo]) -> List[POIInfo]:
        """剔除隶属于同批候选中某个景点的子项

        【主判据】高德 parent 字段: 子项会带父POI的ID。
        必须**迭代剪枝** —— 存在中间层级, 只做一轮会漏。实测北京动物园:
            北京动物园        parent=[]            (父级)
            北京动物园-北区    parent=北京动物园      (第1层)
            狮虎山/象馆/猩猩馆 parent=北区/西区       (第2层, 名字里毫无父级线索)
        一轮剪枝只删掉第1层, 第2层的"狮虎山""象馆"仍在池中且父级已消失。
        故反复剔除"父级仍在池中"的项, 直到不再变化。

        【兜底】名称判据(带分隔符且父名命中/后缀为部件词), 用于 parent 缺失的情况。
        """
        kept = list(pois)
        while True:
            ids = {p.id for p in kept if p.id}
            before = len(kept)
            kept = [
                p for p in kept
                if not (p.parent_id and p.parent_id in ids and p.parent_id != p.id)
            ]
            if len(kept) == before:
                break

        # 名称兜底
        names = [(p.name or "").strip() for p in kept]
        result: List[POIInfo] = []
        for i, poi in enumerate(kept):
            name = names[i]
            if not name:
                result.append(poi)
                continue
            is_sub = False
            for j, other in enumerate(names):
                if i == j or not other or len(other) >= len(name):
                    continue
                if name.startswith(other):
                    is_sub = True
                    break
            if not is_sub:
                for sep in _SUB_POI_SEPARATORS:
                    if sep in name:
                        head, _, tail = name.partition(sep)
                        head, tail = head.strip(), tail.strip()
                        if head and head in names and head != name:
                            is_sub = True
                        elif tail and any(
                            s and s in tail
                            for s in cls._sub_poi_suffixes()
                        ):
                            is_sub = True
                        break
            if not is_sub:
                result.append(poi)
        return result

    @classmethod
    def _sub_poi_suffixes(cls) -> List[str]:
        """结构性部件词(用于无父级可依时的兜底判定)"""
        return get_settings().attraction_sub_poi_suffixes

    # ============ 偏好排序 ============

    def _preference_score(
        self,
        poi: POIInfo,
        preferences: List[str],
        ranking_hits: Optional[List[str]] = None,
    ) -> float:
        """综合排序分: 评分 + 景点榜单加分 + 偏好映射加分

        偏好只影响"排序", 不影响"能否入选" —— 任何偏好下得到的都是真实景点。

        ranking_hits: 该景点命中的景点榜单关键词(状元榜/必玩榜)。
        景点状元榜加分权重高于偏好加分 —— 用户明确要求"景点也有上状元榜的",
        上了榜的景点应当优先。
        """
        s = self.settings
        score = (poi.rating or 0) / 5.0
        text = f"{poi.name} {poi.type}"
        codes = self._codes(poi)

        # ① 景点榜单命中 -> 加权(最高优先级)
        if ranking_hits:
            score += s.attraction_ranking_bonus

        for pref in preferences:
            # ② 类型编码精确命中该偏好的定向类目 -> 加分(最可靠)
            pref_codes = s.attraction_preference_type_codes.get(pref, [])
            if pref_codes and any(
                c.startswith(pc) for c in codes for pc in pref_codes
            ):
                score += s.attraction_preference_bonus
                continue

            # ③ 类目名/名称命中偏好线索词 -> 加分
            for clue in s.attraction_preference_clues.get(pref, []):
                if clue and clue in text:
                    score += s.attraction_preference_bonus
                    break  # 同一偏好只加一次, 避免多类目命中导致分数爆炸

        return score

    # ============ 展示辅助 ============

    @staticmethod
    def describe(poi: POIInfo) -> str:
        """转成供 LLM 参考的一行文本"""
        last = poi.cuisine
        parts = [poi.name, f"类型: {last}"]
        if poi.rating is not None:
            parts.append(f"评分: {poi.rating}")
        if poi.address:
            parts.append(f"地址: {poi.address}")
        if poi.location and (poi.location.longitude or poi.location.latitude):
            parts.append(f"坐标: {poi.location.longitude},{poi.location.latitude}")
        return " | ".join(parts)


# 全局单例
_attraction_service: Optional[AttractionService] = None


def get_attraction_service() -> AttractionService:
    """获取景点服务实例(单例模式)"""
    global _attraction_service
    if _attraction_service is None:
        _attraction_service = AttractionService()
    return _attraction_service
