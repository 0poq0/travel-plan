"""高德地图服务封装 (httpx 直调高德 REST API)"""

import logging
import threading
import time

import httpx
from typing import List, Dict, Any, Optional
from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo

logger = logging.getLogger(__name__)

# 高德 REST API 基础地址
AMAP_BASE_URL = "https://restapi.amap.com"


class AmapService:
    """高德地图服务封装类

    通过高德开放平台 Web 服务 API 提供: POI搜索、天气查询、路线规划、地理编码、POI详情。
    相比原来基于 MCP 的实现, 直调 REST API 无需启动外部 MCP 服务进程, 自包含、易调试。
    """

    def __init__(self):
        """初始化服务"""
        settings = get_settings()
        self.api_key = settings.amap_api_key
        if not self.api_key:
            raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")

        self.client = httpx.Client(timeout=10)
        # 图片URL内存缓存: name -> (url, expire_ts), 避免重复调用高德消耗配额/QPS
        self._photo_cache: Dict[str, tuple] = {}
        # QPS熔断时间戳: 触发CUQPS超限后, 该时间之前不再调用高德图片接口
        self._photo_blocked_until = 0.0
        # 全局调用节流: 个人开发者 key 的 QPS 上限约 3-5, 餐厅推荐需要连续翻页
        # (3个榜单词 × 4页 + 周边搜索), 不节流必然触发 CUQPS_HAS_EXCEEDED_THE_LIMIT,
        # 实测会导致榜单词召回整体失败、候选池从189家塌到23家。
        self._call_lock = threading.Lock()
        self._last_call_ts = 0.0
        self._min_call_interval = 0.34  # 秒/次 ≈ 2.9 QPS

    def _throttle(self) -> None:
        """全局调用节流: 保证任意两次高德请求间隔不小于 _min_call_interval

        用进程级锁+时间戳, 保证多线程(FastAPI 线程池)并发时也不会挤爆 QPS。
        """
        with self._call_lock:
            wait = self._last_call_ts + self._min_call_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call_ts = time.monotonic()

    def _get(self, path: str, params: Dict[str, Any]) -> dict:
        """GET 请求高德 API, 统一注入 key 并校验响应

        带节流与 QPS 超限重试: 触发 CUQPS_HAS_EXCEEDED_THE_LIMIT 时退避重试,
        避免瞬时并发把整批召回打挂。

        Args:
            path: API路径, 如 /v3/place/text
            params: 查询参数

        Returns:
            高德响应JSON(dict)

        Raises:
            ValueError: 高德返回 status != 1 且重试仍失败时
        """
        request_params = {**params, "key": self.api_key}
        max_attempts = 3
        last_error = ""

        for attempt in range(max_attempts):
            self._throttle()
            resp = self.client.get(f"{AMAP_BASE_URL}{path}", params=request_params)
            resp.raise_for_status()

            data = resp.json()
            if data.get("status") == "1":
                return data

            info = data.get("info", "未知错误")
            last_error = info
            # 仅对 QPS 超限这类瞬时错误退避重试; 其他错误(如 key 无效)直接抛出
            if "CUQPS" in info and attempt < max_attempts - 1:
                backoff = 0.8 * (attempt + 1)
                logger.warning(
                    f"高德QPS超限, {backoff:.1f}s 后重试 ({attempt + 1}/{max_attempts}): {path}"
                )
                time.sleep(backoff)
                continue
            raise ValueError(f"高德API错误: {info}")

        raise ValueError(f"高德API错误(重试{max_attempts}次仍失败): {last_error}")

    @staticmethod   # 静态方法装饰器，无需实例化即可调用，不需要读取或修改类里面的任何属性（所以连 self 参数都不需要传）
    def _parse_location(location: str) -> Location:
        """解析高德坐标字符串 "经度,纬度" 为 Location"""
        lon, lat = location.split(",")
        return Location(longitude=float(lon), latitude=float(lat))

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """把高德返回的数值字段安全转 float

        高德字段类型不稳定: 可能是 "4.7" / 4.7 / [] (空数组) / "" 等。
        实测"坤宁宫东院餐厅"的 biz_ext.cost 就是 []，必须容错，否则解析直接炸。
        """
        if value is None or isinstance(value, (list, dict)):
            return None
        try:
            text = str(value).strip()
            return float(text) if text else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_str(value: Any) -> str:
        """把高德返回的字符串字段安全转 str

        高德字段类型不稳定: 无值时可能返回 [] (空数组) 而不是 "",
        实测周边搜索的 address 就会返回 [], 直接丢给 Pydantic 会校验失败。
        """
        if value is None or isinstance(value, (list, dict)):
            return ""
        return str(value)

    @staticmethod
    def _parse_poi(item: dict) -> POIInfo:
        """把高德原始 pois 项解析为 POIInfo (含深度字段)

        biz_ext(评分/人均消费) 仅餐饮、酒店、景点、影院类POI才有;
        tag 在美食类POI上代表特色菜; distance 仅周边搜索才返回。
        """
        location = item.get("location", "")
        biz_ext = item.get("biz_ext") or {}
        if not isinstance(biz_ext, dict):
            biz_ext = {}
        distance = AmapService._to_float(item.get("distance"))
        location_raw = AmapService._to_str(location)
        return POIInfo(
            id=AmapService._to_str(item.get("id")),
            name=AmapService._to_str(item.get("name")),
            type=AmapService._to_str(item.get("type")),
            address=AmapService._to_str(item.get("address")),
            location=AmapService._parse_location(location_raw) if location_raw else Location(longitude=0, latitude=0),
            tel=AmapService._to_str(item.get("tel")) or None,
            typecode=AmapService._to_str(item.get("typecode")),
            rating=AmapService._to_float(biz_ext.get("rating")),
            cost=AmapService._to_float(biz_ext.get("cost")),
            tag=AmapService._to_str(item.get("tag")),
            business_area=AmapService._to_str(item.get("business_area")),
            distance=int(distance) if distance is not None else None,
            # parent: 高德返回的父POI ID(无父级时为空数组), 用于剔除
            # "动物园内部场馆""乐园内单项"这类父子重复
            parent_id=AmapService._to_str(item.get("parent")),
        )

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        """搜索POI (兴趣点)

        Args:
            keywords: 搜索关键词, 如 "故宫" / "酒店"
            city: 城市, 如 "北京"
            citylimit: 是否仅搜索城市范围内

        Returns:
            POI信息列表
        """
        data = self._get("/v3/place/text", {
            "keywords": keywords,
            "city": city,
            "citylimit": str(citylimit).lower(),
            "offset": 10,
            "page": 1,
            "extensions": "all",
        })

        return [self._parse_poi(item) for item in data.get("pois", [])]

    def search_poi_around(
        self,
        location: str,
        keywords: str = "",
        types: str = "050000",
        radius: int = 2000,
        offset: int = 25,
        page: int = 1,
    ) -> List[POIInfo]:
        """周边搜索POI (按坐标搜半径内的POI)

        相比关键字搜索, 周边搜索的优势是返回 distance 字段(距中心点米数),
        因此"景点附近吃饭"应当用这个接口, 而不是关键字搜索。

        Args:
            location: 中心点坐标 "经度,纬度"
            keywords: 关键词, 可为空(仅按类型搜)
            types: POI类型编码, 默认 050000(餐饮服务)
            radius: 搜索半径(米), 最大 50000
            offset: 每页条数, 官方建议不超过 25
            page: 页码

        Returns:
            POI信息列表(含 distance 字段)
        """
        params: Dict[str, Any] = {
            "location": location,
            "types": types,
            "radius": radius,
            "offset": offset,
            "page": page,
            "extensions": "all",
        }
        if keywords:
            params["keywords"] = keywords

        data = self._get("/v3/place/around", params)
        return [self._parse_poi(item) for item in data.get("pois", [])]

    def search_poi_pages_typed(
        self,
        keywords: str,
        city: str,
        types: str,
        pages: int = 4,
        offset: int = 25,
    ) -> List[POIInfo]:
        """关键字搜索并翻页, 可指定 POI 类型编码 (合并多页结果)

        实测高德 place/text 在 offset=25 时只能翻到第4页, 第10页返回空,
        因此 pages 上限按 4 控制, 再多也是白跑配额。

        Args:
            keywords: 关键词
            city: 城市
            types: POI类型编码, 如 050000(餐饮) / 100000(住宿)
            pages: 翻几页 (实测最多约4页有效)
            offset: 每页条数

        Returns:
            多页合并后的POI列表
        """
        merged: List[POIInfo] = []
        for page in range(1, pages + 1):
            data = self._get("/v3/place/text", {
                "keywords": keywords,
                "city": city,
                "citylimit": "true",
                "types": types,
                "offset": offset,
                "page": page,
                "extensions": "all",
            })
            items = data.get("pois", [])
            if not items:
                break  # 翻到空页提前结束, 省配额
            merged.extend(self._parse_poi(item) for item in items)
        return merged

    def search_poi_pages(
        self,
        keywords: str,
        city: str,
        pages: int = 4,
        offset: int = 25,
    ) -> List[POIInfo]:
        """关键字搜索餐饮POI并翻页 (餐饮类型的便捷封装)

        Args:
            keywords: 关键词
            city: 城市
            pages: 翻几页
            offset: 每页条数

        Returns:
            多页合并后的POI列表
        """
        return self.search_poi_pages_typed(
            keywords=keywords,
            city=city,
            types="050000",
            pages=pages,
            offset=offset,
        )

    def get_weather(self, city: str) -> List[WeatherInfo]:
        """查询天气 (未来4天预报)

        高德天气接口需要城市编码(adcode), 因此先地理编码城市名获取 adcode。

        Args:
            city: 城市名称, 如 "北京"

        Returns:
            天气信息列表
        """
        # 1. 地理编码获取城市 adcode
        geocodes = self.geocode(city)
        if not geocodes:
            return []
        adcode = geocodes[0].get("adcode", "")

        # 2. 查询天气预报
        data = self._get("/v3/weather/weatherInfo", {
            "city": adcode,
            "extensions": "all",
        })

        weather_list = []
        for forecast in data.get("forecasts", []):
            for cast in forecast.get("casts", []):
                weather_list.append(WeatherInfo(
                    date=cast.get("date", ""),
                    day_weather=cast.get("dayweather", ""),
                    night_weather=cast.get("nightweather", ""),
                    day_temp=cast.get("daytemp", 0),
                    night_temp=cast.get("nighttemp", 0),
                    wind_direction=cast.get("daywind", ""),
                    wind_power=cast.get("daypower", ""),
                ))
        return weather_list

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> Dict[str, Any]:
        """规划路线

        高德路线接口需要经纬度, 因此先对起终点地址做地理编码。

        Args:
            origin_address: 起点地址
            destination_address: 终点地址
            origin_city: 起点城市 (可提高地理编码精度)
            destination_city: 终点城市
            route_type: 路线类型 (walking/driving/transit)

        Returns:
            路线信息 (distance/duration/route_type/description)
        """
        # 1. 地理编码起终点
        origin_geocodes = self.geocode(origin_address, origin_city)
        dest_geocodes = self.geocode(destination_address, destination_city)
        if not origin_geocodes or not dest_geocodes:
            return {}
        origin = origin_geocodes[0].get("location", "")
        destination = dest_geocodes[0].get("location", "")
        if not origin or not destination:
            return {}

        # 2. 根据路线类型选择接口
        if route_type == "driving":
            path = "/v3/direction/driving"
        elif route_type == "transit":
            path = "/v3/direction/transit/integrated"
        else:
            path = "/v3/direction/walking"

        data = self._get(path, {
            "origin": origin,
            "destination": destination,
        })

        paths = data.get("route", {}).get("paths", [])
        if not paths:
            return {}
        first = paths[0]
        distance = float(first.get("distance", 0))
        duration = int(first.get("duration", 0))

        return {
            "distance": distance,
            "duration": duration,
            "route_type": route_type,
            "description": f"全程约{distance / 1000:.1f}公里,预计{duration // 60}分钟",
        }

    def geocode(self, address: str, city: Optional[str] = None) -> List[dict]:
        """地理编码 (地址/城市名转经纬度与adcode)

        Args:
            address: 地址或城市名
            city: 城市 (可选, 提高解析精度)

        Returns:
            高德 geocodes 列表, 每项含 location/adcode 等字段
        """
        params = {"address": address}
        if city:
            params["city"] = city
        data = self._get("/v3/geocode/geo", params)
        return data.get("geocodes", [])

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """获取POI详情 (含图片等扩展信息)

        Args:
            poi_id: POI ID

        Returns:
            POI详情原始数据(dict)
        """
        data = self._get("/v3/place/detail", {
            "id": poi_id,
            "extensions": "all",
        })
        pois = data.get("pois", [])
        return pois[0] if pois else {}

    def get_poi_photo_by_name(self, name: str) -> Optional[str]:
        """根据景点名称获取图片URL (国内图源: 高德POI图片)

        Unsplash等国外图源在国内网络不稳定, 因此优先使用高德POI自带的实景图片。
        先全国搜索该名称POI, 取第一个结果的 photos; 搜索无图则再查详情。

        Args:
            name: 景点名称

        Returns:
            图片URL (http自动转https以兼容前端混合内容限制); 无图返回None
        """
        # 命中缓存直接返回 (1小时有效), 避免重复消耗高德配额
        cached = self._photo_cache.get(name)
        if cached and cached[1] > time.time():
            return cached[0]

        # QPS熔断: 刚触发过CUQPS超限时, 短时间内直接返回None, 避免继续加重超限
        if time.time() < self._photo_blocked_until:
            return None

        try:
            # 1. 全国搜索该名称的POI
            data = self._get("/v3/place/text", {
                "keywords": name,
                "offset": 1,
                "page": 1,
                "extensions": "all",
            })
            pois = data.get("pois", [])
            if not pois:
                return None

            # 2. 搜索结果自带 photos 字段
            photos = pois[0].get("photos") or []

            # 3. 搜索无图则查详情
            if not photos:
                poi_id = pois[0].get("id", "")
                if poi_id:
                    detail = self.get_poi_detail(poi_id)
                    photos = detail.get("photos") or []

            url = photos[0].get("url", "") if photos else ""
            if not url:
                return None
            # 高德图片URL为http时转https, 避免前端https页面被混合内容拦截
            url = url if url.startswith("https://") else url.replace("http://", "https://", 1)

            # 写入缓存 (1小时有效), 注意缓存None不写入以支持失败后重试
            self._photo_cache[name] = (url, time.time() + 3600)
            return url
        except Exception as e:
            # CUQPS超限(QPS超限)时熔断30秒, 让并发的其他请求短路, 避免集体触发超限
            if "CUQPS_HAS_EXCEEDED_THE_LIMIT" in str(e):
                self._photo_blocked_until = time.time() + 30
            logger.warning(f"高德获取图片失败: {e}")
            return None


# 创建全局服务实例
_amap_service = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例(单例模式)"""
    global _amap_service

    if _amap_service is None:
        _amap_service = AmapService()

    return _amap_service
