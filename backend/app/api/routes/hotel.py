"""酒店相关 API 路由

供前端"选择酒店"页使用: 按首页选定的住宿档次列出候选酒店,
返回名称/类型/评分/地址/坐标(坐标用于地图打点)。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...services.hotel_service import get_hotel_service

router = APIRouter(prefix="/hotel", tags=["酒店"])

logger = logging.getLogger(__name__)


class HotelItem(BaseModel):
    """酒店条目"""
    poi_id: str = Field(default="", description="高德POI ID")
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="地址")
    type: str = Field(default="", description="酒店类型(高德末级类目)")
    rating: Optional[float] = Field(default=None, description="评分")
    location: Optional[dict] = Field(default=None, description="坐标 {longitude, latitude}")


class HotelListResponse(BaseModel):
    """酒店列表响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息, 含数据口径说明")
    data: list[HotelItem] = Field(default=[], description="酒店列表")
    total: int = Field(default=0, description="总数")
    tier: str = Field(default="", description="住宿档次")
    price_range: list[int] = Field(default=[], description="该档次参考价位区间 [低, 高]")
    no_location: int = Field(default=0, description="无坐标的酒店数(无法在地图打点)")


@router.get(
    "/list",
    response_model=HotelListResponse,
    summary="按住宿档次列出酒店",
    description=(
        "按首页选定的住宿档次列出候选酒店, 供用户选定一家。\n\n"
        "【重要】高德接口**不提供酒店实际房价**(biz_ext.cost 恒为空数组), "
        "因此无法按价格筛选或展示真实房价; 返回的 price_range 是该档次的"
        "**参考估算区间**, 仅用于预算估算。档次筛选依据是高德的类型类目与评分。"
    ),
)
def list_hotels(
    city: str = Query(..., description="城市, 如 北京"),
    tier: str = Query(..., description="住宿档次, 如 经济型酒店"),
    limit: int = Query(default=30, ge=1, le=60, description="返回条数上限"),
):
    """按住宿档次列出酒店 (同步端点, 线程池执行)"""
    result = get_hotel_service().list_hotels_by_tier(
        tier=tier, city=city, limit=limit
    )
    logger.info(
        f"酒店列表: 城市={city} 档次={tier} -> {result['total']} 家 "
        f"(参考价位 ¥{result['price_range'][0]}-{result['price_range'][1]})"
    )
    return HotelListResponse(
        success=True,
        message=result["notice"],
        data=result["hotels"],
        total=result["total"],
        tier=result["tier"],
        price_range=result["price_range"],
        no_location=result["no_location"],
    )
