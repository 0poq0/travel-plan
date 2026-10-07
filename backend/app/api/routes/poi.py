"""POI相关API路由"""

import logging
import threading
import time
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ...models.schemas import Location, RestaurantListResponse
from ...services.amap_service import get_amap_service
from ...services.restaurant_service import get_restaurant_service

router = APIRouter(prefix="/poi", tags=["POI"])

logger = logging.getLogger(__name__)

# 高德个人开发者 key 有 QPS 限制(约3-5), 前端结果页会并发请求所有景点图片。
# 用信号量限制同时并发 + 最小间隔节流, 双保险防止 CUQPS_HAS_EXCEEDED_THE_LIMIT 超限。
_photo_semaphore = threading.BoundedSemaphore(3)
_PHOTO_MIN_INTERVAL = 0.4  # 高德图片调用最小间隔(秒), 0.4s/次 ≈ 2.5 QPS
_photo_last_call = 0.0
_photo_call_lock = threading.Lock()


def _rate_limited_photo_call(amap_service, name: str) -> Optional[str]:
    """带间隔节流的高德图片调用(线程安全)"""
    global _photo_last_call
    with _photo_call_lock:
        wait = _photo_last_call + _PHOTO_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _photo_last_call = time.monotonic()
    return amap_service.get_poi_photo_by_name(name)


class POIDetailResponse(BaseModel):
    """POI详情响应"""
    success: bool
    message: str
    data: Optional[dict] = None


@router.get(
    "/detail/{poi_id}",
    response_model=POIDetailResponse,
    summary="获取POI详情",
    description="根据POI ID获取详细信息,包括图片",
)
def get_poi_detail(poi_id: str):
    """
    获取POI详情 (同步端点, 线程池执行, 不阻塞事件循环)

    Args:
        poi_id: POI ID

    Returns:
        POI详情响应
    """
    amap_service = get_amap_service()
    result = amap_service.get_poi_detail(poi_id)

    return POIDetailResponse(
        success=True,
        message="获取POI详情成功",
        data=result,
    )


@router.get(
    "/search",
    summary="搜索POI",
    description="根据关键词搜索POI",
)
def search_poi(keywords: str, city: str = "北京"):
    """
    搜索POI (同步端点, 线程池执行, 不阻塞事件循环)

    Args:
        keywords: 搜索关键词
        city: 城市名称

    Returns:
        搜索结果
    """
    amap_service = get_amap_service()
    result = amap_service.search_poi(keywords, city)

    return {
        "success": True,
        "message": "搜索成功",
        "data": result,
    }


@router.get(
    "/restaurants",
    response_model=RestaurantListResponse,
    summary="获取景点周边餐厅候选",
    description=(
        "按餐段返回指定锚点(当天景点)周边的餐厅候选列表, 供用户自行选择。\n\n"
        "【口径说明】高德扫街榜无开放API, 这里用「状元榜/本地人爱去/烟火小店」"
        "作为关键词召回高德真实POI, 再按可配置权重打分排序, 属近似口径, "
        "不等价于高德App内扫街榜排名。评分/人均消费/招牌菜均为高德真实字段。\n\n"
        "候选池按「城市+锚点+餐段」缓存, 调整价位区间只做内存重排, 不会重复请求高德。"
    ),
)
def get_restaurants(
    city: str = Query(..., description="城市, 如 北京"),
    lng: Optional[float] = Query(default=None, description="锚点经度(当天首个景点)"),
    lat: Optional[float] = Query(default=None, description="锚点纬度"),
    meal_type: str = Query(default="lunch", description="餐段: lunch/dinner (早餐已排除)"),
    min_cost: Optional[float] = Query(default=None, description="人均消费下限(元)"),
    max_cost: Optional[float] = Query(default=None, description="人均消费上限(元)"),
):
    """
    获取餐厅候选列表 (同步端点, 线程池执行, 不阻塞事件循环)

    设计要点: 系统只给候选, 不替用户决定 —— 选择权在前端。

    Args:
        city: 城市
        lng/lat: 锚点坐标, 用于周边搜索与距离计算(缺省则退化为仅榜单词召回)
        meal_type: 餐段
        min_cost/max_cost: 价位区间(对应前端双滑块)

    Returns:
        餐厅候选列表响应
    """
    # 早餐已按需求排除: 榜单口径的店多为正餐馆子, 早餐场景无对应榜单
    if meal_type not in ("lunch", "dinner"):
        return RestaurantListResponse(
            success=False,
            message=f"不支持的餐段: {meal_type} (仅支持 lunch/dinner, 早餐已排除)",
            data=[],
        )

    anchor = None
    if lng is not None and lat is not None:
        anchor = Location(longitude=lng, latitude=lat)

    if min_cost is not None and max_cost is not None and min_cost > max_cost:
        min_cost, max_cost = max_cost, min_cost  # 滑块传反了也不报错, 直接纠正

    result = get_restaurant_service().get_candidates(
        city=city,
        anchor=anchor,
        meal_type=meal_type,
        min_cost=min_cost,
        max_cost=max_cost,
    )

    logger.info(
        f"餐厅候选: 城市={city} 餐段={meal_type} 区间=¥{min_cost}-{max_cost} "
        f"候选池={result['pool_size']} 过滤后={result['total']} 缓存={result['cached']}"
    )

    return RestaurantListResponse(
        success=True,
        message=result["scope_notice"],
        data=result["candidates"],
        total=result["total"],
        cached=result["cached"],
        price_range=result["price_range"],
    )


@router.get(
    "/photo",
    summary="获取景点图片",
    description="根据景点名称获取高德POI实景图(国内图源), 无图返回空由前端用占位图兜底",
)
def get_attraction_photo(name: str):
    """
    获取景点图片

    Args:
        name: 景点名称

    Returns:
        图片URL
    """
    # 高德POI图片 (国内图源); 信号量限并发 + 间隔节流限QPS, 防止CUQPS超限
    amap_service = get_amap_service()
    with _photo_semaphore:
        photo_url = _rate_limited_photo_call(amap_service, name)

    return {
        "success": True,
        "message": "获取图片成功",
        "data": {
            "name": name,
            "photo_url": photo_url,
        },
    }
