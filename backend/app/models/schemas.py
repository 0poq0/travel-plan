"""数据模型定义"""

from typing import List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import date


# ============ 基础模型 ============
# 说明: Location / SelectedHotel 必须定义在请求模型之前 —— TripRequest 的注解
# 在类体执行时就要解析这些名称, 放到后面会直接 NameError(与 model_rebuild 无关)。

class Location(BaseModel):
    """地理位置"""
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class SelectedHotel(BaseModel):
    """用户在"选择酒店"页选定的酒店 (全程只住这一家)

    由前端在酒店选择页选定后随行程请求提交; 景点会按该酒店的位置筛选距离。
    """
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店坐标")
    rating: Optional[float] = Field(default=None, description="评分")
    type: str = Field(default="", description="酒店类型(高德末级类目)")
    poi_id: str = Field(default="", description="高德POI ID")
    tier: str = Field(default="", description="住宿档次, 如 经济型酒店")


# ============ 请求模型 ============

class TripRequest(BaseModel):
    """旅行规划请求"""
    city: str = Field(..., description="目的地城市", json_schema_extra={"example": "北京"})
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", json_schema_extra={"example": "2025-06-01"})
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", json_schema_extra={"example": "2025-06-03"})
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, json_schema_extra={"example": 3})
    transportation: str = Field(..., description="交通方式", json_schema_extra={"example": "公共交通"})
    accommodation: str = Field(..., description="住宿档次(首页所选)", json_schema_extra={"example": "经济型酒店"})
    preferences: List[str] = Field(default=[], description="旅行偏好标签", json_schema_extra={"example": ["红色精神", "博物馆藏"]})
    free_text_input: Optional[str] = Field(default="", description="额外要求", json_schema_extra={"example": "希望多安排一些博物馆"})
    # 用户在"选择酒店"页选定的酒店(全程只住这一家)。
    # 为空时(例如直接调接口)后端按住宿档次自动挑一家。
    hotel: Optional[SelectedHotel] = Field(
        default=None, description="用户选定的酒店(全程同一家)"
    )

    @property
    def hotel_price_range(self) -> Optional[List[int]]:
        """所选酒店档次对应的参考价位区间(用于住宿预算估算)

        高德不提供酒店实际房价, 故这里取档次的参考区间, 仅用于预算估算。
        """
        from ..config import get_settings

        if not self.accommodation:
            return None
        try:
            return list(get_settings().hotel_price_ranges.get(self.accommodation, []))
        except Exception:
            return None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "city": "北京",
                "start_date": "2025-06-01",
                "end_date": "2025-06-03",
                "travel_days": 3,
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "preferences": ["红色精神", "博物馆藏"],
                "free_text_input": "希望多安排一些博物馆",
                "hotel": {
                    "name": "格林豪泰快捷酒店(北京天通苑东地铁站店)",
                    "address": "北京市昌平区",
                    "location": {"longitude": 116.4, "latitude": 39.9},
                    "rating": 4.8,
                    "type": "经济型连锁酒店",
                    "tier": "经济型酒店",
                },
            }
        }
    )


class POISearchRequest(BaseModel):
    """POI搜索请求"""
    keywords: str = Field(..., description="搜索关键词", json_schema_extra={"example": "故宫"})
    city: str = Field(..., description="城市", json_schema_extra={"example": "北京"})
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """路线规划请求"""
    origin_address: str = Field(..., description="起点地址", json_schema_extra={"example": "北京市朝阳区阜通东大街6号"})
    destination_address: str = Field(..., description="终点地址", json_schema_extra={"example": "北京市海淀区上地十街10号"})
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")


# ============ 响应模型 ============

class Attraction(BaseModel):
    """景点信息"""
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    ticket_price: int = Field(default=0, description="门票价格(元)")


class Meal(BaseModel):
    """餐饮信息"""
    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")


class DayPlan(BaseModel):
    """单日行程

    景点按时间段拆分(用户要求"景点游览分上下午区域, 排版在上下午之间加午餐,
    并且在晚餐后也可以安排行程"):
        attractions_morning   上午
        (午餐 meals 中的 lunch)
        attractions_afternoon 下午
        (晚餐 meals 中的 dinner)
        attractions_evening   晚餐后 / 夜间可去的景点
    attractions 为三段合并后的完整列表, 供地图打点与导出等场景使用。
    """
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="住宿酒店(全程同一家)")
    # 分时段景点
    attractions_morning: List[Attraction] = Field(default=[], description="上午景点")
    attractions_afternoon: List[Attraction] = Field(default=[], description="下午景点")
    attractions_evening: List[Attraction] = Field(
        default=[], description="晚餐后/夜间可去的景点"
    )
    # 三段合并(由后端填充, 前端地图与统计使用)
    attractions: List[Attraction] = Field(default=[], description="全部景点(三段合并)")
    meals: List[Meal] = Field(default=[], description="餐饮列表(午/晚)")
    # 当日行程说明的分段描述(可选, 便于前端排版)
    morning_desc: str = Field(default="", description="上午行程概述")
    afternoon_desc: str = Field(default="", description="下午行程概述")
    evening_desc: str = Field(default="", description="夜间行程概述")

    def merge_attractions(self) -> None:
        """把三段景点合并进 attractions(供地图/统计使用)"""
        merged: List[Attraction] = []
        merged.extend(self.attractions_morning)
        merged.extend(self.attractions_afternoon)
        merged.extend(self.attractions_evening)
        self.attractions = merged


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位; None(无天气数据)转0"""
        if v is None:
            return 0
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """旅行计划"""
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")


class POIInfo(BaseModel):
    """POI信息

    除基础字段外, 补充高德 extensions=all 才会返回的深度信息:
    rating/cost(仅餐饮、酒店、景点、影院类POI有值)、tag(美食特色菜)、
    typecode(分类编码, 用于精准排除烧烤等)、distance(仅周边搜索有值)。
    """
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")
    typecode: str = Field(default="", description="POI分类编码, 如 050117")
    rating: Optional[float] = Field(default=None, description="评分(仅餐饮/酒店/景点/影院)")
    cost: Optional[float] = Field(default=None, description="人均消费(元)")
    tag: str = Field(default="", description="特色内容, 美食类POI为特色菜列表")
    business_area: str = Field(default="", description="所属商圈")
    distance: Optional[int] = Field(default=None, description="距中心点距离(米, 仅周边搜索)")
    parent_id: str = Field(default="", description="父POI ID, 用于剔除父子重复(如动物园内部场馆)")

    @property
    def cuisine(self) -> str:
        """末级菜系类目, 如 '餐饮服务;中餐厅;火锅店' -> '火锅店'"""
        return self.type.split(";")[-1].strip() if self.type else ""

    @property
    def signature_dishes(self) -> List[str]:
        """招牌菜列表 (tag 字段按逗号切分, 是高德真实特色菜而非推测)"""
        if not self.tag:
            return []
        return [t.strip() for t in self.tag.split(",") if t.strip()]


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


# ============ 餐厅推荐模型 ============

class RestaurantCandidate(BaseModel):
    """餐厅候选 (供用户自行选择, 系统不代为决定)

    榜单口径为近似: 用榜单词召回高德POI后自行打分排序, 非高德官方扫街榜排名。
    """
    poi_id: str = Field(..., description="高德POI ID")
    name: str = Field(..., description="餐厅名称")
    cuisine: str = Field(default="", description="菜系末级类目, 如 火锅店")
    address: str = Field(default="", description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    rating: Optional[float] = Field(default=None, description="评分")
    cost: Optional[float] = Field(default=None, description="人均消费(元)")
    distance: Optional[int] = Field(default=None, description="距锚点(当天景点)距离(米)")
    signature_dishes: List[str] = Field(default=[], description="招牌菜/卖什么(高德真实tag)")
    list_hits: List[str] = Field(default=[], description="命中的榜单词(近似口径)")
    business_area: str = Field(default="", description="所属商圈")
    score: float = Field(default=0.0, description="综合得分")
    score_detail: dict = Field(default={}, description="得分明细, 便于调参排查")


class RestaurantListResponse(BaseModel):
    """餐厅候选列表响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[RestaurantCandidate] = Field(default=[], description="餐厅候选列表")
    total: int = Field(default=0, description="候选池总数(过滤前)")
    cached: bool = Field(default=False, description="是否命中候选池缓存")
    price_range: List[float] = Field(default=[], description="候选池人均消费区间[min, max]")


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


# ============ 错误响应 ============

class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")


# 重建模型: TripRequest 引用了在其后定义的 SelectedHotel(跨定义前向引用),
# 模块加载完成后统一解析一次, 避免实例化时出现未解析引用错误。
TripRequest.model_rebuild()
Hotel.model_rebuild()
DayPlan.model_rebuild()
TripPlan.model_rebuild()
RestaurantCandidate.model_rebuild()
RestaurantListResponse.model_rebuild()

