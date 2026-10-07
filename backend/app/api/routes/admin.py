"""管理接口: 清缓存 + 热重载配置

用途: 调参(如榜单权重/距离尺度/价位区间)后不必重启后端进程。
属于运维接口, 仅在本机开发场景使用, 未做鉴权。
"""

import logging

from fastapi import APIRouter, Query
from fastapi.middleware.cors import CORSMiddleware

from ...config import reload_settings
from ...services.attraction_service import get_attraction_service
from ...services.hotel_service import get_hotel_service
from ...services.restaurant_service import get_restaurant_service

router = APIRouter(prefix="/admin", tags=["管理"])

logger = logging.getLogger(__name__)


@router.post(
    "/clear-cache",
    summary="清空服务缓存",
    description=(
        "清空餐厅候选池等内存缓存。\n\n"
        "用途: 改完 config 或想强制重新打高德时调用一次, "
        "下次请求会重新构建候选池。"
    ),
)
def clear_cache(
    scope: str = Query(
        default="all",
        description="清理范围: all=全部 / restaurant=餐厅候选池",
    ),
):
    """清空服务缓存"""
    cleared = {}

    if scope in ("all", "restaurant"):
        cleared["restaurant_pool"] = get_restaurant_service().clear_cache()

    # 景点/酒店服务当前无持久缓存, 但调用一次可确保单例状态干净
    get_attraction_service()
    get_hotel_service()

    logger.info(f"🧹 缓存已清理: {cleared} (scope={scope})")
    return {
        "success": True,
        "message": f"缓存已清理: {cleared}",
        "cleared": cleared,
        "scope": scope,
    }


@router.post(
    "/reload-config",
    summary="热重载配置",
    description=(
        "重新读取 .env 与 config.py 的默认值, 使调参立即生效, 无需重启后端。\n\n"
        "生效范围: 服务层配置(榜单权重/距离尺度/价位区间/搜索半径等) —— "
        "这些服务每次调用都通过 get_settings() 读取, 且本接口原地覆盖字段值, "
        "故调参后立刻生效。\n\n"
        "同时会重建 CORS 中间件(它在启动时快照了 allow_origins)。\n\n"
        "**不生效的**: Python 日志级别(启动时一次性初始化)与任何需要重建进程的配置。\n"
        "若改了 Python 代码逻辑, 仍依赖 uvicorn 的 --reload(监视 app/ 目录)。"
    ),
)
def reload_config(clear_cache_too: bool = Query(default=True, description="是否同时清缓存")):
    """热重载配置(可选同时清缓存)"""
    result = reload_settings()

    # CORS 中间件在启动时就把 allow_origins 快照住了, 只更新 settings 不会生效,
    # 必须重建中间件 —— 否则"热重载"名义下 CORS 白名单改了却不起作用(实测)。
    cors_rebuilt = _rebuild_cors_middleware()
    result["cors_rebuilt"] = cors_rebuilt

    cleared = 0
    if clear_cache_too:
        # 配置变了, 旧候选池是按旧权重算的, 必须清掉否则新配置看不到效果
        cleared = get_restaurant_service().clear_cache()

    result["cache_cleared"] = cleared
    logger.info(
        f"♻️ 配置已热重载 (CORS重建={cors_rebuilt}, 清缓存 {cleared} 条)"
    )
    return result


def _rebuild_cors_middleware() -> bool:
    """按最新配置重建 CORS 中间件

    Starlette 的 CORSMiddleware 在构造时读取 allow_origins, 之后不会跟随
    settings 变化。这里把旧的实例替换掉: 调用其 __init__ 重新解析配置,
    即可让新的 CORS_ORIGINS 生效, 无需重启进程。
    """
    try:
        from ...api.main import app
        from ...config import get_settings

        settings = get_settings()
        wanted = settings.get_cors_origins_list()
        rebuilt = False
        for mw in app.user_middleware:
            if getattr(mw, "cls", None) is CORSMiddleware:
                mw.kwargs["allow_origins"] = wanted
                # 重建中间件栈, 使新参数生效
                app.middleware_stack = app.build_middleware_stack()
                rebuilt = True
                logger.info(f"   CORS 中间件已重建, allow_origins={wanted}")
                break
        return rebuilt
    except Exception as e:
        logger.warning(f"   ⚠️ CORS 中间件重建失败(不影响其余配置重载): {e}")
        return False
