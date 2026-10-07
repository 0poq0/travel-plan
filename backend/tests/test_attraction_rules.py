"""景点筛选单元测试 (离线, 用真实响应样例, 不发外部请求)

覆盖 attraction_service 的过滤逻辑 —— 这些规则是逐字段实测高德接口后定下的,
属于本项目的核心领域知识, 用测试固化下来避免被后续改动破坏。

关键规则来源(实测):
  - 餐饮编码 050xxx: 高德会把餐厅也标上"风景名胜相关;旅游景点",
    仅靠景点类目白名单拦不住, 必须按编码黑名单硬排除
  - 烧烤编码 050400: 只按关键词搜会混入"烤肉", 必须叠加编码判定
  - 烈士陵园编码 071900/071901(丧葬设施) 但带 110210(红色景区),
    故只能按白名单编码判定, 不能按"名称含陵园"排除
  - 景点父POI: 高德返回 parent 字段, 子项(动物园内部场馆)需按 parent 链迭代剪枝
"""

import pytest

from app.models.schemas import POIInfo, Location
from app.services.attraction_service import AttractionService


def make_poi(poi_id: str, name: str, typecode: str, poi_type: str,
             rating: float = 4.5, parent: str = "") -> POIInfo:
    """构造 POIInfo 测试数据"""
    return POIInfo(
        id=poi_id,
        name=name,
        type=poi_type,
        address="测试地址",
        location=Location(longitude=116.4, latitude=39.9),
        typecode=typecode,
        rating=rating,
        parent_id=parent,
    )


@pytest.fixture
def svc() -> AttractionService:
    return AttractionService()


# ============ 黑名单: 排除餐饮娱乐 ============

class TestBlacklist:
    """硬排除规则: 餐厅/KTV/酒吧/洗浴绝不能进景点"""

    def test_restaurant_by_typecode(self, svc):
        """餐饮编码 050xxx 必须排除

        实测陷阱: 高德会给餐厅同时标上"风景名胜;风景名胜相关;旅游景点",
        所以它们能通过景点类目白名单, 只能靠编码黑名单拦住。
        """
        poi = make_poi(
            "R1", "荣喜堂·老北京涮肉(前门大街店)", "110206|050117",
            "风景名胜;风景名胜相关;旅游景点|餐饮服务;中餐厅;火锅店",
        )
        assert svc._is_blacklisted(poi) is True

    def test_ktv_bar_by_typecode(self, svc):
        """KTV(080302)/酒吧(080304) 必须排除"""
        ktv = make_poi("K1", "魅KTV(王府井店)", "080302", "体育休闲服务;娱乐场所;KTV")
        bar = make_poi("B1", "某酒吧", "080304", "体育休闲服务;娱乐场所;酒吧")
        assert svc._is_blacklisted(ktv) is True
        assert svc._is_blacklisted(bar) is True

    def test_bath_spa_by_typecode(self, svc):
        """洗浴推拿 071400 必须排除(实测"泰仙宫足道"带 110205 寺庙道观码)"""
        spa = make_poi(
            "S1", "泰仙宫足道采耳养生(亚运村店)", "110205|071400",
            "风景名胜;风景名胜;寺庙道观|生活服务;洗浴推拿场所;洗浴推拿场所",
        )
        assert svc._is_blacklisted(spa) is True

    def test_normal_attraction_not_blacklisted(self, svc):
        """正常景点不应被误伤"""
        gugong = make_poi(
            "A1", "故宫博物院", "110201|140100",
            "风景名胜;风景名胜;世界遗产|科教文化服务;博物馆;博物馆",
        )
        assert svc._is_blacklisted(gugong) is False


# ============ 白名单: 保留红色景点 ============

class TestWhitelistRedTourism:
    """红色景点必须保留 —— 曾因"名字含陵园"险些被误杀"""

    def test_martyr_cemetery_kept(self, svc):
        """烈士陵园: 编码 110210(红色景区) 在白名单内, 必须保留

        实测编码: 白乙化烈士陵园 = 110210|071900
        其中 071900 属"生活服务;丧葬设施" —— 若按类目名排除会误杀。
        """
        poi = make_poi(
            "RED1", "白乙化烈士陵园", "110210|071900",
            "风景名胜;风景名胜;红色景区|生活服务;丧葬设施;丧葬设施",
        )
        assert svc._in_whitelist(poi) is True
        assert svc._is_blacklisted(poi) is False

    def test_martyr_tomb_kept(self, svc):
        """马骏烈士之墓: 编码顺序反过来 071901|110210, 同样要保留"""
        poi = make_poi(
            "RED2", "马骏烈士之墓", "071901|110210",
            "生活服务;丧葬设施;陵园|风景名胜;风景名胜;红色景区",
        )
        assert svc._in_whitelist(poi) is True
        assert svc._is_blacklisted(poi) is False

    def test_memorial_hall_kept(self, svc):
        """纪念馆 110204 在白名单内"""
        poi = make_poi("RED3", "中国人民抗日战争纪念馆", "110204",
                       "风景名胜;风景名胜;纪念馆")
        assert svc._in_whitelist(poi) is True

    def test_amusement_park_in_whitelist(self, svc):
        """游乐场 080501 在白名单内(欢乐谷等靠它进入候选)"""
        poi = make_poi("P1", "北京环球度假区", "080501",
                       "体育休闲服务;休闲场所;游乐场")
        assert svc._in_whitelist(poi) is True

    def test_karaoke_in_whitelist_range_but_blacklisted(self, svc):
        """回归: 加入 0805 时不能把 0803(KTV/酒吧) 一起放进来

        白名单前缀 0805 与黑名单前缀 0803 相近, 此用例防止以后手滑。
        """
        ktv = make_poi("K2", "酷秀KTV", "080302", "体育休闲服务;娱乐场所;KTV")
        assert svc._is_blacklisted(ktv) is True


# ============ 父子POI 迭代剪枝 ============

class TestSubPoiPruning:
    """父景点内部场馆(狮虎山/象馆等)必须剔除

    实测: 北京动物园的父子链是三层 ——
        北京动物园(id=X) -> 北京动物园-北区(id=Y) -> 狮虎山(parent=Y)
    只做一轮剪枝只能删掉"北区", 第二轮才删得掉"狮虎山"。
    且"狮虎山"名字里完全没有父级线索, 只能靠 parent ID 链。
    """

    def test_iterative_pruning_removes_grandchildren(self, svc):
        zoo = make_poi("X", "北京动物园", "110102", "风景名胜;公园广场;动物园")
        north = make_poi("Y", "北京动物园-北区", "110102",
                         "风景名胜;公园广场;动物园", parent="X")
        tiger = make_poi("Z", "狮虎山", "110102",
                         "风景名胜;公园广场;动物园", parent="Y")
        elephant = make_poi("W", "象馆", "110102",
                            "风景名胜;公园广场;动物园", parent="Y")

        result = svc._drop_sub_pois([zoo, north, tiger, elephant])
        names = [p.name for p in result]

        assert "北京动物园" in names, "父景点被误删"
        assert "北京动物园-北区" not in names, "第一层子项未剔除"
        assert "狮虎山" not in names, "第二层子项(孙子)未剔除 —— 迭代剪枝失效"
        assert "象馆" not in names, "第二层子项(孙子)未剔除"

    def test_orphan_child_kept_when_parent_absent(self, svc):
        """父级不在候选池时, 子项不应被无依据地删除"""
        tiger = make_poi("Z", "狮虎山", "110102",
                         "风景名胜;公园广场;动物园", parent="NOT_IN_POOL")
        result = svc._drop_sub_pois([tiger])
        assert len(result) == 1

    def test_hyphen_sub_poi_removed(self, svc):
        """带连字符的子项: 父名在池中时剔除"""
        tiananmen = make_poi("T1", "天安门", "110202", "风景名胜;风景名胜;国家级景点")
        tower = make_poi("T2", "天安门-城楼", "110202", "风景名胜;风景名胜;国家级景点")

        result = svc._drop_sub_pois([tiananmen, tower])
        names = [p.name for p in result]
        assert "天安门" in names
        assert "天安门-城楼" not in names


# ============ 偏好相关性 ============

class TestPreferenceRelevance:
    def test_animal_preference_matches_zoo(self, svc):
        zoo = make_poi("Z1", "北京动物园", "110102", "风景名胜;公园广场;动物园")
        assert svc._is_preference_relevant(zoo, ["动物世界"]) is True

    def test_animal_preference_rejects_museum(self, svc):
        museum = make_poi("M1", "故宫博物院", "110201|140100",
                          "风景名胜;风景名胜;世界遗产|科教文化服务;博物馆;博物馆")
        assert svc._is_preference_relevant(museum, ["动物世界"]) is False

    def test_playground_does_not_match_generic_sight(self, svc):
        """回归: '游乐场' 线索曾含"国家级景点", 导致什刹海等全被判定为相关"""
        shichahai = make_poi("SH1", "什刹海", "110202", "风景名胜;风景名胜;国家级景点")
        assert svc._is_preference_relevant(shichahai, ["游乐场"]) is False

    def test_playground_matches_amusement_park(self, svc):
        huanlegu = make_poi("HL1", "北京欢乐谷", "080501|110202",
                            "体育休闲服务;休闲场所;游乐场|风景名胜;风景名胜;国家级景点")
        assert svc._is_preference_relevant(huanlegu, ["游乐场"]) is True
