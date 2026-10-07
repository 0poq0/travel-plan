"""配置管理模块"""

from typing import List
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# 加载当前目录的 .env
load_dotenv()

# LLM配置字段在环境变量留空时回退的默认值
_LLM_FIELD_DEFAULTS = {
    "llm_model": "gpt-4o",
    "llm_temperature": 0.7,
    "llm_timeout": 60,
}


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,  # 控制是否环境变量匹配字段时是否区分大小写。
        extra="ignore",  # 忽略未声明的环境变量
    )

    # 应用基本配置
    app_name: str = "LangChain智能旅行助手"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS配置 - 使用字符串,在代码中分割
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = ""

    # LLM配置 (LangChain ChatOpenAI, 兼容任意OpenAI格式端点)
    # 优先读取 LLM_* 命名, 同时兼容 OPENAI_* 旧命名
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY"),  # 多别名备选，按顺序寻找环境变量，优先去找环境变量 LLM_API_KEY如果找不到 LLM_API_KEY，自动退而求其次读取 OPENAI_API_KEY
    )
    llm_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_BASE_URL"),
    )
    llm_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices(
            "LLM_MODEL_ID", "LLM_MODEL", "OPENAI_MODEL", "OPENAI_MODEL_NAME"
        ),
    )
    llm_temperature: float = 0.7
    llm_timeout: int = 60

    # RAG 嵌入模型配置 (千问 text-embedding-v4, 阿里云百炼 DashScope)
    # 未配置时 RAG 功能自动降级禁用, 不影响旅行规划主流程
    dashscope_api_key: str = Field(default="")
    embedding_model: str = Field(default="text-embedding-v4")

    # ============ 餐厅推荐配置 (景点周边榜单近似推荐) ============
    # 【口径声明】高德"扫街榜"没有对外开放 API, 无法取到官方榜单排名。
    # 这里用榜单词去召回高德 POI, 再按下面的权重自行打分排序, 属于"近似口径",
    # 不等价于高德 App 内扫街榜的真实排名。所有参数集中在此, 便于调参。
    #
    # 榜单词召回高德 POI (三词实测零重叠, 是平行的三路召回, 取并集而非交集)
    # 顺序即优先级: 状元榜置首, 且其命中加分为三档最高, 体现"状元榜优先"。
    restaurant_list_keywords: List[str] = ["状元榜", "本地人爱去", "烟火小店"]

    # 各榜单词的命中加分 (平行关系: 命中任一即加分; 多词命中取最大值, 不累加)
    # 【量级很重要】最初设成 0.25/0.15/0.10, 结果远超距离分量满分(0.20),
    # 导致 2851m 外的"状元榜"店稳压 508m 的店, 整个推荐榜被状元榜垄断。
    # 榜单应当是"打破平局"的权重而非主导力量, 故收敛到 0.12 以内。
    # 用户要求"状元榜优先", 故把状元榜拉到明显高于另两档(0.18 vs 0.05/0.04)。
    # 【取舍】实测状元榜店铺普遍在1.5km外, 而距离按800m尺度指数衰减惩罚较重,
    # 权重设 0.12 时状元榜最好只排到第10名(前8条里一家都没有, 用户看不到"优先")。
    # 提到 0.18 可让 1.7km 处的状元榜店进入前8, 但仍受邻近度门控约束,
    # 不会让 3km 外的店反超锚点隔壁的好店。
    restaurant_list_bonus: dict = {
        "状元榜": 0.18,      # 特色菜/地方菜为主, 精准度最高 -> 优先
        "本地人爱去": 0.05,
        "烟火小店": 0.04,
    }

    # 打分权重: 最终得分 = 各分量加权求和 + 榜单加分×邻近度门控 - 连锁降权
    # 菜系项在代码里已按具体类目给分, 其权重直接作用于类目加减分值。
    # 注意 sum(rating+distance) 应明显大于 list_bonus 上限, 否则榜单会架空距离。
    restaurant_weight_rating: float = 0.40      # 评分(归一化到 0-1), 主导项
    restaurant_weight_distance: float = 0.20    # 距离(指数衰减), 次主导
    restaurant_weight_cuisine: float = 0.15     # 菜系类型(地方菜/特色菜加分)
    restaurant_rating_min: float = 3.5          # 评分下限, 解析不出评分的直接丢弃
    # 周边搜索半径(米)。每餐只以"吃饭时所在的那一个景点"为圆心,
    # 故半径与距离上限保持一致: 搜索半径外的店本来也不该进推荐。
    restaurant_search_radius: int = 2000
    restaurant_top_n: int = 8                   # 每餐返回候选数量

    # 烧烤排除: 实测只按关键词会混进"烤肉"(拾也·烤肉放题/戈拿旺巴西烤肉),
    # 必须叠加 typecode 前缀 050400(烧烤) 才干净, 故双重判定
    restaurant_ban_typecode_prefix: List[str] = ["050400"]
    restaurant_ban_keywords: List[str] = ["烧烤", "烤串", "BBQ", "烤肉", "铁板烧"]

    # 连锁品牌降权 (实测"本地人爱去"会召回海底捞/大鸭梨/王品等连锁,
    # 与"烟火小店"意图冲突, 故降权)
    restaurant_chain_keywords: List[str] = [
        "海底捞", "麦当劳", "肯德基", "必胜客", "汉堡王", "星巴克",
        "喜茶", "奈雪的茶", "瑞幸", "西贝", "外婆家", "绿茶餐厅",
        "探鱼", "太二", "九毛九", "大鸭梨", "紫光园", "王品",
        "呷哺", "老乡鸡", "乡村基", "真功夫", "永和大王", "吉野家",
    ]
    # 连锁降权分 (负值)
    restaurant_chain_penalty: float = -0.20
    # 老字号白名单: 命中连锁词也不降权 (它们是真正的"必吃", 不该被当成连锁打压)
    restaurant_chain_whitelist: List[str] = [
        "东来顺", "全聚德", "便宜坊", "鸿宾楼", "烤肉宛",
    ]

    # 菜系加分/减分 (按高德 type 字段末级类目匹配)
    restaurant_cuisine_bonus: dict = {
        "特色/地方风味餐厅": 0.06,
        "清真菜馆": 0.05,
        "中式素菜馆": 0.04,
        "火锅店": 0.03,
        "中餐厅": 0.02,
    }
    restaurant_cuisine_penalty: dict = {
        "快餐厅": -0.06,
        "饮品店": -0.08,
        "冷饮店": -0.08,
        "咖啡厅": -0.05,
        "甜品店": -0.05,
        # 实测"萬春金福下午茶"曾以4.9分排到午餐第一, 但下午茶不是正餐,
        # 午晚两餐列表里不该优先出现
        "下午茶": -0.10,
        "糕饼店": -0.06,
        "茶艺馆": -0.06,
    }

    # 候选池缓存有效期(秒): 同一"城市+锚点+餐段"在有效期内复用,
    # 避免拖价位滑块时反复打高德(个人 key 仅约 3-5 QPS)
    restaurant_cache_ttl: int = 1800

    # ============ 酒店档次配置 ============
    # 【重要限制 - 实测确认】高德 POI 接口**不提供酒店价格**:
    #   biz_ext.cost              恒为 [] (空数组)
    #   biz_ext.lowest_price      恒为 []
    #   详情接口全字段扫描无任何价格语义字段(discount_num/groupbuy_num 也恒为0)
    # 只有餐饮类 POI 的 biz_ext.cost 才有人均消费值。
    # 因此 hotel_price_ranges **只能用于预算估算, 不能用于真实筛选** ——
    # 早期版本按 cost 过滤酒店是无效的(所有酒店都无价格, 过滤等于没做)。
    #
    # 真实可用的档次信号是 type 字段的末级类目(如"经济型连锁酒店"/"五星级宾馆")
    # 与 biz_ext.rating, 故筛选改用 hotel_tier_type_keywords + 评分。
    hotel_price_ranges: dict = {
        # 百元档: 用户要求"酒店民宿之类的有100元以下的"。
        # 【限制】高德不提供酒店价格, 无法按 <100 元筛; 但"青年旅舍/旅馆招待所/
        # 客栈"这类类型本身就是百元档, 故按类型识别, 参考价取 ¥100/晚。
        "青旅/招待所": [50, 150],
        "经济型酒店": [100, 350],
        "舒适型酒店": [350, 700],
        "豪华酒店": [700, 2500],
        "民宿": [150, 800],
    }
    hotel_price_range_default: List[int] = [200, 800]
    hotel_rating_min: float = 3.5

    # 各档次在 type 字段**末级类目**中应出现的关键词 (用于档次分流)
    # 关键: 必须只比对末级类目。高德 type 形如
    #   "住宿服务;宾馆酒店;经济型连锁酒店"
    # 中类"宾馆酒店"出现在几乎所有酒店里, 若拿它去子串匹配整串,
    # 经济型连锁店会被误判成舒适型(实测发生过)。
    # 归属原则: 每个末级类型只归一个档次, 不重叠。
    hotel_tier_type_keywords: dict = {
        # 百元档: 这些类型的真实市场价普遍在百元以下(青旅床位/小招待所/客栈)
        "青旅/招待所": ["青年旅舍", "旅馆招待所", "客栈"],
        "经济型酒店": ["经济型连锁酒店", "青年旅舍", "客栈"],
        "舒适型酒店": ["三星级宾馆", "四星级宾馆", "宾馆酒店", "商务酒店", "公寓式酒店"],
        "豪华酒店": ["五星级宾馆", "豪华", "度假村", "高尔夫"],
        "民宿": ["民宿", "农家乐", "度假村", "旅馆招待所"],
    }
    # 档次吻合/不吻合时的加减分 (0-1 综合分上的调整)
    hotel_tier_match_bonus: float = 0.15
    hotel_tier_mismatch_penalty: float = -0.20
    # 是否剔除"明确属于其他档次"的酒店。
    # True: 豪华档不会出现经济型连锁店(推荐更干净);
    # False: 只降权不剔除(结果更多但会有跨档混入)。
    hotel_drop_tier_mismatch: bool = True
    # 酒店召回关键词: 用中性词广搜, 再按末级类目分档。
    # 实测直接用"豪华酒店"当关键词只召回 50 家且仅 1 家真五星(关键词噪声大),
    # 而中性词广搜可得 100 家且类型分布完整(宾馆酒店/经济型连锁/五星/四星/三星)。
    hotel_search_keywords: str = "酒店|宾馆|民宿|旅馆"

    # ============ 预算兜底单价 (LLM 未返回预算时使用) ============
    # 按餐段区分, 而不是午晚统一。实测早餐/午晚餐人均差距很大。
    budget_meal_cost: dict = {
        "breakfast": 25,
        "lunch": 60,
        "dinner": 90,
    }
    budget_meal_cost_default: int = 60      # 未知餐段兜底
    budget_transport_per_day: int = 50      # 市内交通 元/天
    # 酒店兜底单价: 未指定/未匹配档位时使用; 匹配到档位则取区间中值
    budget_hotel_per_night_default: int = 400

    # ============ 景点筛选配置 ============
    # 原实现把用户偏好词("美食"/"购物"/"休闲")直接当关键词搜且不限类型,
    # 导致餐厅、商场、洗浴中心被当作"可选景点"喂给 LLM, 最终排进每日景点。
    # 现在改为「编码白名单 + 硬排除黑名单」双重判定。
    #
    # 白名单(按 typecode 前缀匹配) —— 只保留真正有游览价值的场所:
    attraction_type_whitelist: List[str] = [
        "1101",   # 公园广场: 公园(110101)/动物园(110102)/植物园(110103)/水族馆(110104)/城市广场
        "1102",   # 风景名胜: 国家级景点/世界遗产/红色景区/纪念馆/寺庙道观/教堂
        "1402",   # 博物馆
        "1403",   # 美术馆
        "1404",   # 展览馆
        "1405",   # 科技馆/天文馆
        "0805",   # 体育休闲服务;休闲场所;游乐场(080501) —— 主题乐园/游乐园
    ]
    # 硬排除(按 typecode 前缀, 优先级高于白名单)
    # 实测编码: 餐饮 050xxx / KTV 080302 / 酒吧 080304 / 洗浴推拿 071400
    # 注意: 不要把 0805 当黑名单 —— 那是游乐场(欢乐谷/石景山游乐园的编码)。
    # "娱乐休闲场所"也未加入: 该码过宽, 容易误伤合法景点, 具体场所由
    # attraction_name_blacklist(网吧/棋牌/电玩/健身房等)兜住。
    attraction_type_blacklist: List[str] = [
        "050",    # 餐饮服务 -> 饭店/餐厅/火锅/小吃
        "0803",   # 娱乐场所 -> KTV/酒吧/夜总会/歌舞厅/LiveHouse
        "0714",   # 洗浴推拿 -> 洗浴中心/温泉/足疗/SPA
        "0706",   # 娱乐休闲场所
    ]
    # 名称关键词硬排除(兜底: 有些场所类型标注不全, 靠名字兜住)
    # 注意: 不要加"陵园/墓", 烈士陵园属于红色景区(110210)必须保留
    attraction_name_blacklist: List[str] = [
        "饭店", "餐厅", "火锅", "烧烤", "小吃", "咖啡馆",
        "KTV", "ktv", "酒吧", "夜总会", "歌舞厅", "livehouse", "LiveHouse",
        "洗浴", "温泉", "足疗", "按摩", "推拿", "SPA", "spa", "桑拿",
        "网吧", "棋牌", "电玩", "健身房", "美容", "美发",
    ]
    # 景点评分下限(实测可用字段只有 rating, cost/tag 景点类POI不返回)
    attraction_rating_min: float = 3.5
    # 是否剔除父POI的子POI(如"故宫博物院-午门"/"故宫博物院-神武门")
    # 实测100条景点里23条是这种子POI, 会造成同一天重复安排同一景点
    attraction_drop_sub_poi: bool = True
    # 子POI的结构性后缀: 名称含分隔符且后缀是这些"部件词"时, 判定为父景点的内部子项。
    # 例: "中央美术学院-美术馆(花家地新馆)"、"故宫博物院-神武门"。
    # 注意不要加"后海/前海"这类本身即独立景点的地名。
    attraction_sub_poi_suffixes: List[str] = [
        "门", "殿", "楼", "阁", "亭", "塔", "馆", "厅", "堂", "园中", "宫",
        "入口", "出口", "停车场", "售票处", "游客中心", "广场店", "新馆", "旧馆",
        "东门", "西门", "南门", "北门", "角楼", "城墙", "码头",
    ]

    # 景点搜索关键词: 只用中性景点词召回。
    # 【重要】不能再用用户偏好词(美食/购物/休闲)当关键词: 实测即便限定了景点类型,
    # "美食"会搜出"雍和宫大街四十三号院""甘肃厅""萨利宅院"这类无意义碎点,
    # "休闲"会搜出"泰仙宫足道采耳养生""吉雅幸福时光精油禅院"这类足道/精油店
    # (它们带了 110205寺庙道观 / 110200风景名胜 编码, 纯靠类型判不掉)。
    # 偏好改由 attraction_preference_clues 映射到景点类目来影响排序。
    attraction_base_keywords: List[str] = ["景点", "公园", "博物馆", "风景名胜", "美术馆"]

    # ============ 景点状元榜 ============
    # 实测: 景点类 keywords="状元榜" 确实能召回上过榜的景点, 但数量很少
    # (北京仅 3 条: 故宫博物院/雍和宫/北海公园), 正好印证"景点也有上状元榜的"。
    # 补一个同为榜单语义的"必玩榜"(北京 23 条, 质量高: 故宫/环球度假区/颐和园/
    # 天坛/欢乐谷), 让榜单样本足够影响排序。
    # 不采用"必去榜/人气榜/打卡榜": 实测召回的多是温泉度假村/休闲场所, 噪声大。
    # 注意: 餐厅的状元榜关键词(restaurant_list_keywords)保持不变, 二者互不影响。
    attraction_ranking_keywords: List[str] = ["状元榜", "必玩榜"]
    # 命中景点榜单的排序加分 (加在 0-1 归一化评分上)
    attraction_ranking_bonus: float = 0.30

    # ============ 夜间可去景点 (关键词代理) ============
    # 【限制】高德免费接口不提供营业时间(景点类 POI 的 opentime 基本为空),
    # 无法判定"晚上是否真的开门"。这里用关键词代理筛出"适合夜游"的景点。
    # 实测(北京, 仅保留景点类目):
    #   夜游   -> 八达岭长城/天坛公园/故宫/什刹海/欢乐谷      (质量高)
    #   灯光秀 -> 环球度假区/古北水镇/八达岭长城/司马台/亮马河水岸 (质量高)
    #   夜市   -> 南锣鼓巷/什刹海/雁栖湖                    (可用)
    # 弃用: 夜景/夜景观光/观景台 (count=600 泛词, 返回无关景点)、
    #       酒吧街 (全是酒吧)、美食街 (混入餐厅, 与"景点"定义冲突)。
    attraction_night_keywords: List[str] = ["夜游", "灯光秀", "夜市"]
    # 是否保证每天至少安排一个"知名景点"。
    # 判据用**景点榜单命中**(状元榜/必玩榜) —— 那是高德侧的知名度标记,
    # 也被系统用作排序加分, 是判断"名胜"最可靠的现成信号。
    # 用户反馈过"不勾偏好就没有名胜", 虽然实测是旧代码所致, 但这类情况
    # 不该靠运气, 故加保底: 某天若一个榜单景点都没有, 用未使用的榜单景点替换
    # 该天一个普通景点。
    itinerary_ensure_famous_per_day: bool = True
    # 夜间景点候选数量上限。
    # 用户要求"夜间行程一天一个就够", 故按天数取候选即可; 给到 12 是为多天行程
    # 留出选不同景点的余量(全行程景点强制去重, 太少会导致后面几天没得排)。
    attraction_night_top_n: int = 12
    # 每天安排的夜间景点数量(用户要求一天一个)
    night_attractions_per_day: int = 1
    # 夜间景点的距离上限(km)。**必须比白天更严**:
    # 白天去 60km 外的长城合理, 但夜间游览安排在 60km 外不现实 ——
    # 实测夜间池里混入了八达岭长城(59.9km)/慕田峪长城, 被排成夜间行程。
    night_attraction_max_km: float = 20.0
    # 上午/下午每段应安排的景点数量(用户要求"每个时段两个")。
    # 用 _ensure_slot_counts 做数量兜底: 去重或知名景点保底替换后某段若不足,
    # 自动从候选池补齐(实测出现过上下午只剩1个的情况)。
    day_slot_attractions: int = 2
    # 为夜间专属保留的景点数量(从白天候选池中移除这些)。
    # 为什么需要: 夜间候选(夜游/灯光秀/夜市)基本是白天候选的子集, LLM 会顺手
    # 把南锣鼓巷/什刹海这类排进白天, 去重后夜间可补的候选就没了 ——
    # 实测导致第2、3天夜间为空(夜间池 20km 内仅6个, 被挑走3个)。
    # 预留后由系统专供夜间使用, 保证每天都排得上。
    night_reserved_attractions: int = 8

    # 偏好标签 -> 相关景点类目关键词 (用于排序加权)
    # 只做"加分排序", 不做"排他过滤": 保证任何偏好下都能选出真实景点,
    # 同时让相关类目优先出现。
    # 注意: 不要映射到"展览馆" —— 该末级类目大量对应会展中心/博览会场馆,
    # 实测会把"南登录厅""中关村展示交易中心"这类非旅游场馆顶到前排。
    attraction_preference_clues: dict = {
        # 红色精神: 红色景区/纪念馆/旧址/烈士设施
        "红色精神": ["红色景区", "纪念馆", "旧址", "烈士", "革命", "纪念"],
        # 自然风景: 公园/国家级景点/山湖/广场
        "自然风景": ["公园", "风景名胜", "国家级景点", "动物园", "水族馆", "城市广场"],
        # 人文风光: 寺庙道观/古城/世界遗产/国家级景点
        "人文风光": ["寺庙道观", "古城", "世界遗产", "国家级景点", "古建", "教堂", "文化街"],
        # 博物馆藏: 博物馆/展览馆/科技馆
        "博物馆藏": ["博物馆", "展览馆", "科技馆", "美术馆"],
        # 动物世界: 动物园(110102)/水族馆(110104)
        "动物世界": ["动物园", "水族馆", "海洋馆", "动物"],
        # 游乐场: 高德游乐场编码是 080501(体育休闲), 但欢乐谷等同时带
        # 110202(国家级景点)才进得了白名单。**线索里不能放"国家级景点"** ——
        # 那会让什刹海/恭王府等所有国家级景点都被误判成游乐场(实测)。
        # 故只按"游乐/乐园"字样匹配, 具体游乐场靠 080501 编码定向召回。
        "游乐场": ["游乐", "乐园"],
    }
    # 偏好命中时的排序加分 (加在 0-1 归一化评分上)。
    # 不宜过大: 设成 0.5 时会把"展览馆"类场馆整体顶到前排(实测),
    # 0.25 足以改变同评分段内的次序, 又不会压过评分差异。
    attraction_preference_bonus: float = 0.25

    # 候选池中"非偏好相关"景点保留的比例。
    # 原先"相关项够 top_n 就只用相关项", 导致**天坛/北海这类高分名胜被偏好门槛
    # 整体排除在候选池外**, LLM 根本没机会选 —— 这与"不要因距离放弃关键名胜"
    # 是同一类错误: 用次要信号把关键景点排除了。
    # 现保留约 30% 名额给全城高分景点, 让偏好只影响排序而非决定生死。
    attraction_non_preference_ratio: float = 0.3

    # 偏好 -> 定向召回用的 POI 类型编码
    # 为何需要: 基础关键词(景点/公园/博物馆...)的召回池里根本没有动物园、
    # 水族馆、游乐场这类 POI, 所以"动物世界""游乐场"偏好此前完全失效
    # (实测返回的仍是通用高分景点)。这里为每个偏好补充一路定向召回。
    attraction_preference_type_codes: dict = {
        "动物世界": ["110102", "110104"],   # 动物园 / 水族馆
        "游乐场": ["080501"],               # 游乐场(欢乐谷/石景山游乐园)
        "博物馆藏": ["1402", "1403", "1404", "1405"],  # 博物馆/美术馆/展览馆/科技馆
        "红色精神": ["110204", "110210"],   # 纪念馆 / 红色景区
        "人文风光": ["110205", "110202"],   # 寺庙道观 / 国家级景点
        "自然风景": ["110101", "110103"],   # 公园 / 植物园
    }
    # 偏好定向召回的翻页数
    # 必须给足页数: 父子剪枝依赖高德 parent ID 链, 而中间层节点(如"北京动物园-东区")
    # 只在翻到第4页时才会出现。实测 pages=1 时池中无中间层, 导致"狮虎山""象馆"
    # 的 parent 永远匹配不上、无法剔除; pages=4 时中间层全在池中, 剪枝即生效。
    attraction_preference_pages: int = 4

    # 偏好 -> 定向召回用的搜索关键词
    # 关键: 不能用偏好词本身当关键词。实测 keywords="红色精神" 只匹配到 2 条
    # (高德里没有叫"红色精神"的POI), 而 keywords="红色景区|纪念馆" 能拿 50 条。
    # 故每个偏好都要配一组真实存在的场所类关键词。
    attraction_preference_search_keywords: dict = {
        "红色精神": "红色景区|纪念馆|革命旧址|烈士",
        "自然风景": "公园|植物园|风景区",
        "人文风光": "寺庙|古城|文化街|遗址",
        "博物馆藏": "博物馆|美术馆|科技馆",
        "动物世界": "动物园|水族馆",
        "游乐场": "游乐场|主题乐园|欢乐谷",
    }

    # ============ 每日行程排程(按距离就近) ============
    # 用户要求"地点距离相近安排"。LLM 只在提示词里看到"考虑距离"但拿不到
    # 真实距离, 实际排序是随机的。故在生成行程后做一次后置优化:
    # 保持当天景点集合不变, 用最近邻法重排访问顺序, 减少往返奔波。
    itinerary_optimize_distance: bool = True
    # 重排后若总路程没有改善达到该比例, 则回退原顺序(避免为了微小收益打乱节奏)
    itinerary_optimize_min_gain: float = 0.05

    # ============ 行程排程(酒店距离只作参考) ============
    # 该配置经历了三轮调整, 记录原因以免再走回头路:
    #   1) 最初"只排序不筛选" -> LLM 看不到距离, 景点散在全城 20-30km;
    #   2) 随后收紧到 12km + 截断 12 个 -> 过度集中(平均3.3km), 住哪儿就只能逛
    #      那一小片, **天坛/故宫这类关键名胜会被距离直接排除掉, 这显然是错的**;
    #   3) 现在: 范围放宽到全城, 候选池给足, 距离**只用于排序与展示, 不承担排除职责**。
    # 用户明确要求"距离较远时放弃关键名胜不合适, 减少距离的影响"。
    hotel_attraction_max_km: float = 60.0
    hotel_attraction_max_items: int = 36

    # 日志配置
    log_level: str = "INFO"

    
    # @field_validator：Pydantic 字段校验钩子
    # 在环境变量赋值给类字段之前 / 之后，拦截值，自定义处理逻辑。
    @field_validator("llm_model", "llm_temperature", "llm_timeout", mode="before")
    @classmethod
    def _empty_env_to_default(cls, v, info):
        """环境变量为空字符串时回退到默认值,避免覆盖默认配置"""
        if v == "" or v is None:
            return _LLM_FIELD_DEFAULTS.get(info.field_name)
        return v

    def get_cors_origins_list(self) -> List[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(",")]


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


def reload_settings() -> dict:
    """热重载配置 (不重启进程)

    用途: 调参后无需重启后端。做法是重新读取 .env 并重建 Settings,
    然后**替换全局 settings 对象的内容**。

    注意必须原地更新(而不是重新绑定模块变量): 其他模块通过
    `from ..config import get_settings` / 持有 settings 引用来读配置,
    若只做 `settings = Settings()` 重新绑定, 那些已持有的引用仍指向旧对象,
    配置看起来"没生效"。这里用 model_copy 原地覆盖字段值。

    Returns:
        dict: 重载结果与关键配置摘要
    """
    global settings

    # 重新读取 .env (覆盖已有环境变量, 使改动生效)
    load_dotenv(override=True)
    fresh = Settings()

    # 原地覆盖字段, 保证已持有引用的调用方也能读到新值
    for field_name in fresh.model_fields:
        object.__setattr__(settings, field_name, getattr(fresh, field_name))

    summary = {
        "restaurant_list_keywords": list(settings.restaurant_list_keywords),
        "restaurant_list_bonus": dict(settings.restaurant_list_bonus),
        "attraction_ranking_keywords": list(settings.attraction_ranking_keywords),
        "attraction_ranking_bonus": settings.attraction_ranking_bonus,
        "attraction_preference_bonus": settings.attraction_preference_bonus,
        "hotel_price_ranges": dict(settings.hotel_price_ranges),
        "attraction_search_radius": settings.restaurant_search_radius,
    }
    return {"success": True, "message": "配置已热重载", "config": summary}


# 验证必要的配置
def validate_config():
    """验证配置是否完整"""
    errors = []
    warnings = []

    if not settings.amap_api_key:
        errors.append("AMAP_API_KEY未配置")

    if not settings.llm_api_key:
        warnings.append("LLM_API_KEY或OPENAI_API_KEY未配置,LLM功能可能无法使用")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        print("\n⚠️  配置警告:")
        for w in warnings:
            print(f"  - {w}")

    return True


# 打印配置信息(用于调试)
def print_config():
    """打印当前配置(隐藏敏感信息)"""
    print(f"应用名称: {settings.app_name}")
    print(f"版本: {settings.app_version}")
    print(f"服务器: {settings.host}:{settings.port}")
    print(f"高德地图API Key: {'已配置' if settings.amap_api_key else '未配置'}")

    print(f"LLM API Key: {'已配置' if settings.llm_api_key else '未配置'}")
    print(f"LLM Base URL: {settings.llm_base_url or 'https://api.openai.com/v1 (官方默认)'}")
    print(f"LLM Model: {settings.llm_model}")
    print(f"LLM Temperature: {settings.llm_temperature}")
    print(f"LLM Timeout: {settings.llm_timeout}s")
    print(f"RAG 嵌入模型: {settings.embedding_model} ({'已配置' if settings.dashscope_api_key else '未配置(自动禁用)'})")
    print(f"日志级别: {settings.log_level}")


if __name__ == "__main__":
    print("当前配置:")
    settings = Settings()
    print_config()
