<template>
  <div class="result-container">
    <!-- 页面头部 -->
    <div class="page-header">
      <a-button class="back-button" size="large" @click="goBack">
        ← 返回首页
      </a-button>
      <a-space size="middle">
        <a-button v-if="!editMode" @click="toggleEditMode" type="default">
          ✏️ 编辑行程
        </a-button>
        <a-button v-else @click="saveChanges" type="primary">
          💾 保存修改
        </a-button>
        <a-button v-if="editMode" @click="cancelEdit" type="default">
          ❌ 取消编辑
        </a-button>

        <!-- 导出按钮 -->
        <a-dropdown v-if="!editMode">
          <template #overlay>
            <a-menu>
              <a-menu-item key="image" @click="exportAsImage">
                📷 导出为图片
              </a-menu-item>
              <a-menu-item key="pdf" @click="exportAsPDF">
                📄 导出为PDF
              </a-menu-item>
            </a-menu>
          </template>
          <a-button type="default">
            📥 导出行程 <DownOutlined />
          </a-button>
        </a-dropdown>
      </a-space>
    </div>

    <div v-if="tripPlan" class="content-wrapper">
      <!-- 侧边导航 -->
      <div class="side-nav">
        <a-affix :offset-top="80">
          <a-menu mode="inline" :selected-keys="[activeSection]" @click="scrollToSection">
            <a-menu-item key="overview">
              <span>📋 行程概览</span>
            </a-menu-item>
            <a-menu-item key="budget" v-if="tripPlan.budget">
              <span>💰 预算明细</span>
            </a-menu-item>
            <a-menu-item key="map">
              <span>📍 景点地图</span>
            </a-menu-item>
            <a-sub-menu key="days" title="📅 每日行程">
              <a-menu-item v-for="(day, index) in tripPlan.days" :key="`day-${index}`">
                第{{ day.day_index + 1 }}天
              </a-menu-item>
            </a-sub-menu>
            <a-menu-item key="weather" v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0">
              <span>🌤️ 天气信息</span>
            </a-menu-item>
          </a-menu>
        </a-affix>
      </div>

      <!-- 主内容区 -->
      <div class="main-content">
        <!-- 顶部信息区:左侧概览+预算,右侧地图 -->
        <div class="top-info-section">
          <!-- 左侧:行程概览和预算明细 -->
          <div class="left-info">
            <!-- 行程概览 -->
            <a-card id="overview" :title="`${tripPlan.city}旅行计划`" :bordered="false" class="overview-card">
              <template #extra>
                <span class="overview-days">{{ tripPlan.days.length }} 天行程</span>
              </template>
              <div class="overview-content">
                <div class="info-item">
                  <span class="info-label">📅 日期</span>
                  <span class="info-value">{{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}</span>
                </div>
                <!-- 行程统计 -->
                <div class="overview-stats">
                  <div class="stat-box">
                    <div class="stat-num">{{ tripPlan.days.length }}</div>
                    <div class="stat-label">天行程</div>
                  </div>
                  <div class="stat-box">
                    <div class="stat-num">{{ totalAttractions }}</div>
                    <div class="stat-label">个景点</div>
                  </div>
                  <div class="stat-box">
                    <div class="stat-num">¥{{ formatMoney(tripPlan.budget?.total || 0) }}</div>
                    <div class="stat-label">预估总预算</div>
                  </div>
                </div>
                <div class="info-item">
                  <span class="info-label">💡 旅行建议</span>
                  <span class="info-value">{{ tripPlan.overall_suggestions }}</span>
                </div>
              </div>
            </a-card>

            <!-- 预算明细 -->
            <a-card id="budget" v-if="tripPlan.budget" title="💰 预算明细" :bordered="false" class="budget-card">
              <div class="budget-grid">
                <div class="budget-item">
                  <div class="budget-label">景点门票</div>
                  <div class="budget-value">¥{{ formatMoney(tripPlan.budget.total_attractions) }}</div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">酒店住宿</div>
                  <div class="budget-value">¥{{ formatMoney(tripPlan.budget.total_hotels) }}</div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">餐饮费用</div>
                  <div class="budget-value">¥{{ formatMoney(tripPlan.budget.total_meals) }}</div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">交通费用</div>
                  <div class="budget-value">¥{{ formatMoney(tripPlan.budget.total_transportation) }}</div>
                </div>
              </div>
              <div class="budget-total">
                <span class="total-label">预估总费用</span>
                <span class="total-value">¥{{ formatMoney(tripPlan.budget.total) }}</span>
              </div>
            </a-card>
          </div>

          <!-- 右侧:地图 -->
          <div class="right-map">
            <a-card id="map" title="📍 景点地图" :bordered="false" class="map-card">
              <div id="amap-container" style="width: 100%; height: 100%"></div>
            </a-card>
          </div>
        </div>

        <!-- 每日行程:可折叠 -->
        <a-card title="📅 每日行程" :bordered="false" class="days-card">
          <a-collapse v-model:activeKey="activeDays" accordion>
            <a-collapse-panel
              v-for="(day, index) in tripPlan.days"
              :key="index"
              :id="`day-${index}`"
            >
              <template #header>
                <div class="day-header">
                  <span class="day-title">第{{ day.day_index + 1 }}天</span>
                  <span class="day-date">{{ day.date }}</span>
                </div>
              </template>

              <!-- 行程基本信息 -->
              <div class="day-info">
                <div class="info-row">
                  <span class="label">📝 行程描述:</span>
                  <span class="value">{{ day.description }}</span>
                </div>
                <div class="info-row">
                  <span class="label">🚗 交通方式:</span>
                  <span class="value">{{ day.transportation }}</span>
                </div>
                <div class="info-row">
                  <span class="label">🏨 住宿:</span>
                  <span class="value">{{ day.accommodation }}</span>
                </div>
              </div>

              <!-- 分时段行程: 上午 → 午餐 → 下午 → 晚餐 → 夜间 -->
              <a-divider orientation="left">🌅 上午行程</a-divider>
              <div v-if="day.morning_desc" class="slot-desc">{{ day.morning_desc }}</div>
              <AttractionSlot
                :items="day.attractions_morning"
                :edit-mode="editMode"
                :photos="attractionPhotos"
                @move="(i, d) => moveAttraction(day.day_index, 'attractions_morning', i, d)"
                @remove="i => deleteAttraction(day.day_index, 'attractions_morning', i)"
              />

              <!-- 午餐 (夹在上午与下午之间) -->
              <a-divider orientation="left">🍽️ 午餐</a-divider>
              <MealPicker
                v-for="meal in day.meals.filter(m => m.type === 'lunch')"
                :key="meal.type"
                :meal="meal"
                :day-index="day.day_index"
                :edit-mode="editMode"
                :picker="getPicker(day.day_index, meal.type)"
                @load="loadRestaurants(day.day_index, 'lunch')"
                @change-range="onPriceRangeChange(day.day_index, 'lunch')"
                @select="c => selectRestaurant(day.day_index, 'lunch', c)"
              />

              <a-divider orientation="left">🌇 下午行程</a-divider>
              <div v-if="day.afternoon_desc" class="slot-desc">{{ day.afternoon_desc }}</div>
              <AttractionSlot
                :items="day.attractions_afternoon"
                :edit-mode="editMode"
                :photos="attractionPhotos"
                @move="(i, d) => moveAttraction(day.day_index, 'attractions_afternoon', i, d)"
                @remove="i => deleteAttraction(day.day_index, 'attractions_afternoon', i)"
              />

              <!-- 晚餐 -->
              <a-divider orientation="left">🍽️ 晚餐</a-divider>
              <MealPicker
                v-for="meal in day.meals.filter(m => m.type === 'dinner')"
                :key="meal.type"
                :meal="meal"
                :day-index="day.day_index"
                :edit-mode="editMode"
                :picker="getPicker(day.day_index, meal.type)"
                @load="loadRestaurants(day.day_index, 'dinner')"
                @change-range="onPriceRangeChange(day.day_index, 'dinner')"
                @select="c => selectRestaurant(day.day_index, 'dinner', c)"
              />

              <!-- 夜间行程 (晚餐后) -->
              <template v-if="day.attractions_evening && day.attractions_evening.length">
                <a-divider orientation="left">🌙 夜间行程</a-divider>
                <div v-if="day.evening_desc" class="slot-desc">{{ day.evening_desc }}</div>
                <AttractionSlot
                  :items="day.attractions_evening"
                  :edit-mode="editMode"
                  :photos="attractionPhotos"
                  @move="(i, d) => moveAttraction(day.day_index, 'attractions_evening', i, d)"
                  @remove="i => deleteAttraction(day.day_index, 'attractions_evening', i)"
                />
              </template>

              <!-- 住宿: 全程同一家 -->
              <a-divider v-if="day.hotel" orientation="left">🏨 住宿（全程同一家）</a-divider>
              <a-card v-if="day.hotel" size="small" class="hotel-card">
                <template #title>
                  <span class="hotel-title">{{ day.hotel.name }}</span>
                </template>
                <a-descriptions :column="2" size="small">
                  <a-descriptions-item label="地址">{{ day.hotel.address }}</a-descriptions-item>
                  <a-descriptions-item label="类型">{{ day.hotel.type }}</a-descriptions-item>
                  <a-descriptions-item label="参考价位">{{ day.hotel.price_range || '—' }}</a-descriptions-item>
                  <a-descriptions-item label="评分">{{ day.hotel.rating || '—' }}</a-descriptions-item>
                </a-descriptions>
              </a-card>

            </a-collapse-panel>
          </a-collapse>
        </a-card>

        <a-card id="weather" v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0" title="🌤️ 天气信息" class="weather-section" :bordered="false">
        <a-list
          :data-source="tripPlan.weather_info"
          :grid="{ gutter: 16, column: 3 }"
        >
          <template #renderItem="{ item }">
            <a-list-item>
              <a-card size="small" class="weather-card">
                <div class="weather-date">{{ item.date }}</div>
                <div class="weather-info-row">
                  <span class="weather-icon">☀️</span>
                  <div>
                    <div class="weather-label">白天</div>
                    <div class="weather-value">{{ item.day_weather }} {{ item.day_temp }}°C</div>
                  </div>
                </div>
                <div class="weather-info-row">
                  <span class="weather-icon">🌙</span>
                  <div>
                    <div class="weather-label">夜间</div>
                    <div class="weather-value">{{ item.night_weather }} {{ item.night_temp }}°C</div>
                  </div>
                </div>
                <div class="weather-wind">
                  💨 {{ item.wind_direction }} {{ item.wind_power }}
                </div>
              </a-card>
            </a-list-item>
          </template>
        </a-list>
        </a-card>
      </div>
    </div>

    <a-empty v-else description="没有找到旅行计划数据">
      <template #image>
        <div style="font-size: 80px;">🗺️</div>
      </template>
      <template #description>
        <span style="color: #999;">暂无旅行计划数据,请先创建行程</span>
      </template>
      <a-button type="primary" @click="goBack">返回首页创建行程</a-button>
    </a-empty>

    <!-- 回到顶部按钮 -->
    <a-back-top :visibility-height="300">
      <div class="back-top-button">
        ↑
      </div>
    </a-back-top>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, computed } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { DownOutlined } from '@ant-design/icons-vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import type { TripPlan, RestaurantCandidate } from '@/types'
import { updateHistory, fetchRestaurants } from '@/services/api'
import AttractionSlot from '@/components/AttractionSlot.vue'
import MealPicker from '@/components/MealPicker.vue'

/** 景点时段字段名 */
type SlotKey = 'attractions_morning' | 'attractions_afternoon' | 'attractions_evening'

const router = useRouter()
const tripPlan = ref<TripPlan | null>(null)
const editMode = ref(false)
const originalPlan = ref<TripPlan | null>(null)
const attractionPhotos = ref<Record<string, string>>({})
const activeSection = ref('overview')
const activeDays = ref<number[]>([0]) // 默认展开第一天
const historyRecordId = ref<number>(0) // 从历史打开时的记录 id (0=新规划)
let map: any = null

// 统计所有景点数量
const totalAttractions = computed(() => {
  if (!tripPlan.value) return 0
  return tripPlan.value.days.reduce((sum, day) => sum + day.attractions.length, 0)
})

// 金额千分位格式化
const formatMoney = (value: number): string => {
  return (value || 0).toLocaleString('zh-CN')
}

onMounted(async () => {
  const data = sessionStorage.getItem('tripPlan')
  if (data) {
    tripPlan.value = JSON.parse(data)
    // 历史打开时记录 id (供编辑保存写回数据库); 新规划则为 0
    historyRecordId.value = Number(sessionStorage.getItem('tripPlanId') || '0')
    // 加载景点图片
    await loadAttractionPhotos()
    // 等待DOM渲染完成后初始化地图
    await nextTick()
    initMap()
  }
})

const goBack = () => {
  router.push('/')
}

// 滚动到指定区域
const scrollToSection = ({ key }: { key: string }) => {
  activeSection.value = key
  // 每日行程: 先展开对应面板再滚动定位
  if (key.startsWith('day-')) {
    const dayIndex = Number(key.replace('day-', ''))
    activeDays.value = [dayIndex]
    nextTick(() => {
      document.getElementById(key)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return
  }
  document.getElementById(key)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// 切换编辑模式
const toggleEditMode = () => {
  editMode.value = true
  // 保存原始数据用于取消编辑
  originalPlan.value = JSON.parse(JSON.stringify(tripPlan.value))
  message.info('进入编辑模式')
}

// 保存修改
const saveChanges = async () => {
  editMode.value = false
  // 更新sessionStorage (始终保留当前渲染数据)
  if (tripPlan.value) {
    sessionStorage.setItem('tripPlan', JSON.stringify(tripPlan.value))
  }
  // 从历史打开时: 把编辑结果持久化回数据库, 下次打开历史仍是编辑后的内容
  if (historyRecordId.value && tripPlan.value) {
    try {
      await updateHistory(historyRecordId.value, tripPlan.value)
      message.success('修改已保存到历史记录')
    } catch (error: any) {
      message.error(error.message || '保存失败, 修改仅保留在本地')
    }
  } else {
    message.success('修改已保存')
  }

  // 重新初始化地图以反映更改
  if (map) {
    map.destroy()
  }
  nextTick(() => {
    initMap()
  })
}

// 取消编辑
const cancelEdit = () => {
  if (originalPlan.value) {
    tripPlan.value = JSON.parse(JSON.stringify(originalPlan.value))
  }
  editMode.value = false
  message.info('已取消编辑')
}

// 删除景点 (按所在时段)
const deleteAttraction = (dayIndex: number, slot: SlotKey, attrIndex: number) => {
  if (!tripPlan.value) return

  const day = tripPlan.value.days[dayIndex]
  const list = day[slot] as any[]
  if (list.length <= 1) {
    message.warning('该时段至少需要保留一个景点')
    return
  }

  list.splice(attrIndex, 1)
  refreshMergedAttractions(day)
  message.success('景点已删除')
}

// 移动景点顺序 (仅在该时段内部移动, 不跨时段)
const moveAttraction = (
  dayIndex: number,
  slot: SlotKey,
  attrIndex: number,
  direction: 'up' | 'down'
) => {
  if (!tripPlan.value) return

  const day = tripPlan.value.days[dayIndex]
  const attractions = day[slot] as any[]

  if (direction === 'up' && attrIndex > 0) {
    [attractions[attrIndex], attractions[attrIndex - 1]] = [attractions[attrIndex - 1], attractions[attrIndex]]
  } else if (direction === 'down' && attrIndex < attractions.length - 1) {
    [attractions[attrIndex], attractions[attrIndex + 1]] = [attractions[attrIndex + 1], attractions[attrIndex]]
  }
  refreshMergedAttractions(day)
}

/** 三段景点变动后重新合并, 保证地图与统计使用的是最新数据 */
const refreshMergedAttractions = (day: any) => {
  day.attractions = [
    ...(day.attractions_morning || []),
    ...(day.attractions_afternoon || []),
    ...(day.attractions_evening || [])
  ]
}

// ============ 餐厅候选择 (景点周边) ============
// 设计: 系统只给候选列表, 由用户自行选择; 不替用户决定。
// 榜单为近似口径 —— 后端用「状元榜/本地人爱去/烟火小店」召回高德真实POI
// 后自行打分排序, 非高德官方扫街榜排名。评分/人均/招牌菜均为高德真实字段。

interface MealPickerState {
  loading: boolean
  candidates: RestaurantCandidate[]
  /** 候选池的人均区间, 用于初始化滑块范围 */
  bounds: number[]
  range: number[]
  total: number
  loaded: boolean
  /** 后端候选池缓存命中的标志, 用于提示"未重复请求高德" */
  cached: boolean
  scopeNotice: string
  error: string
  /** 该餐锚定的景点名, 界面上说明"按哪个景点搜的" */
  anchorName: string
}

const mealPickers = ref<Record<string, MealPickerState>>({})

/** 取某个餐段的选择状态 (没有则初始化)。key = dayIndex:mealType */
const getPicker = (dayIndex: number, mealType: string): MealPickerState => {
  const key = `${dayIndex}:${mealType}`
  if (!mealPickers.value[key]) {
    mealPickers.value[key] = {
      loading: false,
      candidates: [],
      // 默认区间做宽一些, 真正的上下界在首次拿到候选池后按实际数据收敛
      bounds: [0, 200],
      range: mealType === 'dinner' ? [50, 200] : [30, 150],
      total: 0,
      loaded: false,
      cached: false,
      scopeNotice: '',
      error: '',
      anchorName: ''
    }
  }
  return mealPickers.value[key]
}

/**
 * 取某餐用餐时"所在的那一个景点"作为锚点
 *
 * 规则(按用户的行程直觉):
 *   - 午餐: 上午通常逛前两个景点, 故取当天第 2 个景点; 只有 1 个景点时取第 1 个
 *   - 晚餐: 一天逛完在最后一个景点附近收尾, 故取当天最后一个景点
 * 只用一个点, 不做多景点聚合, 与后端"单锚点"设计一致。
 */
const getMealAnchor = (
  dayIndex: number,
  mealType: string
): { lng: number; lat: number; name: string } | null => {
  const day = tripPlan.value?.days[dayIndex]
  const attractions = day?.attractions || []
  if (!attractions.length) return null

  let target
  if (mealType === 'lunch') {
    target = attractions.length >= 2 ? attractions[1] : attractions[0]
  } else {
    target = attractions[attractions.length - 1]
  }
  if (!target) return null

  const loc = target.location
  if (!loc || (!loc.longitude && !loc.latitude)) return null
  return { lng: loc.longitude, lat: loc.latitude, name: target.name }
}

/** 加载某餐段的餐厅候选 */
const loadRestaurants = async (dayIndex: number, mealType: 'lunch' | 'dinner') => {
  const picker = getPicker(dayIndex, mealType)
  picker.loading = true
  picker.error = ''
  try {
    const anchor = getMealAnchor(dayIndex, mealType)
    picker.anchorName = anchor?.name || ''
    const res = await fetchRestaurants({
      city: tripPlan.value?.city || '',
      meal_type: mealType,
      lng: anchor?.lng,
      lat: anchor?.lat,
      min_cost: picker.range[0],
      max_cost: picker.range[1]
    })
    if (!res.success) {
      picker.error = res.message || '获取候选餐厅失败'
      return
    }
    picker.candidates = res.data
    picker.total = res.total
    picker.cached = res.cached
    picker.scopeNotice = res.message
    picker.loaded = true
    // 首次拿到候选池后, 用真实价格区间收敛滑块范围
    if (res.price_range && res.price_range.length === 2 && res.price_range[1] > 0) {
      picker.bounds = [
        Math.floor(res.price_range[0]),
        Math.ceil(res.price_range[1])
      ]
      // 若当前区间把结果全滤空了, 自动放宽到全量区间, 避免用户看到空列表
      if (!res.data.length) {
        picker.range = [...picker.bounds]
        await loadRestaurants(dayIndex, mealType)
      }
    }
  } catch (e: any) {
    picker.error = e.message || '获取候选餐厅失败'
  } finally {
    picker.loading = false
  }
}

/** 滑块变化: 候选池已缓存, 重排不打高德, 故可放心实时调用 */
const onPriceRangeChange = (dayIndex: number, mealType: 'lunch' | 'dinner') => {
  loadRestaurants(dayIndex, mealType)
}

/** 选定某家餐厅, 回填到该餐, 并同步刷新预算 */
const selectRestaurant = (
  dayIndex: number,
  mealType: 'lunch' | 'dinner',
  candidate: RestaurantCandidate
) => {
  if (!tripPlan.value) return
  const day = tripPlan.value.days[dayIndex]
  const meal = day.meals.find(m => m.type === mealType)
  if (!meal) return

  meal.name = candidate.name
  meal.poi_id = candidate.poi_id
  meal.address = candidate.address
  meal.location = candidate.location
  meal.rating = candidate.rating
  meal.cost = candidate.cost
  meal.distance = candidate.distance
  meal.tags = candidate.signature_dishes
  meal.estimated_cost = candidate.cost
  meal.selected = true
  meal.description = `人均约¥${candidate.cost ?? '-'} | 距景点${candidate.distance ?? '-'}米`

  // 选中后收起候选列表
  getPicker(dayIndex, mealType).loaded = false

  recalcMealBudget()
  message.success(`已选择「${candidate.name}」`)
}

/** 同步三餐预算 (选择餐厅后人均消费会变) */
const recalcMealBudget = () => {
  if (!tripPlan.value || !tripPlan.value.budget) return
  const totalMeals = tripPlan.value.days.reduce(
    (sum, day) => sum + day.meals.reduce((s, m) => s + (m.estimated_cost || 0), 0),
    0
  )
  const b = tripPlan.value.budget
  b.total_meals = totalMeals
  b.total = b.total_attractions + b.total_hotels + totalMeals + b.total_transportation
}

// dishesText / distanceText / getMealLabel 已迁移到 MealPicker 组件,
// getAttractionImage / handleImageError 已迁移到 AttractionSlot 组件。

// 加载所有景点图片
const loadAttractionPhotos = async () => {
  if (!tripPlan.value) return

  const promises: Promise<void>[] = []

  tripPlan.value.days.forEach(day => {
    day.attractions.forEach(attraction => {
      const promise = fetch(`http://localhost:8000/api/poi/photo?name=${encodeURIComponent(attraction.name)}`)
        .then(res => res.json())
        .then(data => {
          if (data.success && data.data.photo_url) {
            attractionPhotos.value[attraction.name] = data.data.photo_url
          }
        })
        .catch(err => {
          console.error(`获取${attraction.name}图片失败:`, err)
        })

      promises.push(promise)
    })
  })

  await Promise.all(promises)
}

// getAttractionImage / handleImageError 已在 AttractionSlot 组件中实现,
// 该组件通过 photos 属性接收这里加载好的图片映射。

// 导出为图片
const exportAsImage = async () => {
  try {
    message.loading({ content: '正在生成图片...', key: 'export', duration: 0 })

    const element = document.querySelector('.main-content') as HTMLElement
    if (!element) {
      throw new Error('未找到内容元素')
    }

    // 创建一个独立的容器
    const exportContainer = document.createElement('div')
    exportContainer.style.width = element.offsetWidth + 'px'
    exportContainer.style.backgroundColor = '#f5f7fa'
    exportContainer.style.padding = '20px'

    // 复制所有内容
    exportContainer.innerHTML = element.innerHTML

    // 处理地图截图
    const mapContainer = document.getElementById('amap-container')
    if (mapContainer && map) {
      const mapCanvas = mapContainer.querySelector('canvas')
      if (mapCanvas) {
        const mapSnapshot = mapCanvas.toDataURL('image/png')
        const exportMapContainer = exportContainer.querySelector('#amap-container')
        if (exportMapContainer) {
          exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
        }
      }
    }

    // 移除所有ant-card类,替换为纯div
    const cards = exportContainer.querySelectorAll('.ant-card')
    cards.forEach((card) => {
      const cardEl = card as HTMLElement
      try {
        cardEl.className = '' // 移除所有类
        cardEl.style.setProperty('background-color', '#ffffff')
        cardEl.style.setProperty('border-radius', '12px')
        cardEl.style.setProperty('box-shadow', '0 4px 12px rgba(0, 0, 0, 0.1)')
        cardEl.style.setProperty('margin-bottom', '20px')
        cardEl.style.setProperty('overflow', 'hidden')
      } catch (err) {
        console.error('设置卡片样式失败:', err)
      }
    })

    // 处理卡片头部
    const cardHeads = exportContainer.querySelectorAll('.ant-card-head')
    cardHeads.forEach((head) => {
      const headEl = head as HTMLElement
      try {
        headEl.style.setProperty('background-color', '#667eea')
        headEl.style.setProperty('color', '#ffffff')
        headEl.style.setProperty('padding', '16px 24px')
        headEl.style.setProperty('font-size', '18px')
        headEl.style.setProperty('font-weight', '600')
      } catch (err) {
        console.error('设置卡片头部样式失败:', err)
      }
    })

    // 处理卡片内容
    const cardBodies = exportContainer.querySelectorAll('.ant-card-body')
    cardBodies.forEach((body) => {
      const bodyEl = body as HTMLElement
      bodyEl.style.setProperty('background-color', '#ffffff')
      bodyEl.style.setProperty('padding', '24px')
    })

    // 处理酒店卡片头部
    const hotelCards = exportContainer.querySelectorAll('.hotel-card')
    hotelCards.forEach((card) => {
      const head = card.querySelector('.ant-card-head') as HTMLElement
      if (head) {
        head.style.setProperty('background-color', '#1976d2')
      }
      (card as HTMLElement).style.setProperty('background-color', '#e3f2fd')
    })

    // 处理天气卡片
    const weatherCards = exportContainer.querySelectorAll('.weather-card')
    weatherCards.forEach((card) => {
      (card as HTMLElement).style.setProperty('background-color', '#e0f7fa')
    })

    // 处理预算总计
    const budgetTotal = exportContainer.querySelector('.budget-total')
    if (budgetTotal) {
      const el = budgetTotal as HTMLElement
      el.style.setProperty('background-color', '#667eea')
      el.style.setProperty('color', '#ffffff')
      el.style.setProperty('padding', '20px')
      el.style.setProperty('border-radius', '12px')
      el.style.setProperty('margin-bottom', '20px')
    }

    // 处理预算项
    const budgetItems = exportContainer.querySelectorAll('.budget-item')
    budgetItems.forEach((item) => {
      const el = item as HTMLElement
      el.style.setProperty('background-color', '#f5f7fa')
      el.style.setProperty('padding', '16px')
      el.style.setProperty('border-radius', '8px')
      el.style.setProperty('margin-bottom', '12px')
    })

    // 添加到body(隐藏)
    exportContainer.style.position = 'absolute'
    exportContainer.style.left = '-9999px'
    document.body.appendChild(exportContainer)

    const canvas = await html2canvas(exportContainer, {
      backgroundColor: '#f5f7fa',
      scale: 2,
      logging: false,
      useCORS: true,
      allowTaint: true
    })

    // 移除容器
    document.body.removeChild(exportContainer)

    // 转换为图片并下载
    const link = document.createElement('a')
    link.download = `旅行计划_${tripPlan.value?.city}_${new Date().getTime()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()

    message.success({ content: '图片导出成功!', key: 'export' })
  } catch (error: any) {
    console.error('导出图片失败:', error)
    message.error({ content: `导出图片失败: ${error.message}`, key: 'export' })
  }
}

// 导出为PDF
const exportAsPDF = async () => {
  try {
    message.loading({ content: '正在生成PDF...', key: 'export', duration: 0 })

    const element = document.querySelector('.main-content') as HTMLElement
    if (!element) {
      throw new Error('未找到内容元素')
    }

    // 创建一个独立的容器
    const exportContainer = document.createElement('div')
    exportContainer.style.width = element.offsetWidth + 'px'
    exportContainer.style.backgroundColor = '#f5f7fa'
    exportContainer.style.padding = '20px'

    // 复制所有内容
    exportContainer.innerHTML = element.innerHTML

    // 处理地图截图
    const mapContainer = document.getElementById('amap-container')
    if (mapContainer && map) {
      const mapCanvas = mapContainer.querySelector('canvas')
      if (mapCanvas) {
        const mapSnapshot = mapCanvas.toDataURL('image/png')
        const exportMapContainer = exportContainer.querySelector('#amap-container')
        if (exportMapContainer) {
          exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
        }
      }
    }

    // 移除所有ant-card类,替换为纯div
    const cards = exportContainer.querySelectorAll('.ant-card')
    cards.forEach((card) => {
      const cardEl = card as HTMLElement
      try {
        cardEl.className = ''
        cardEl.style.setProperty('background-color', '#ffffff')
        cardEl.style.setProperty('border-radius', '12px')
        cardEl.style.setProperty('box-shadow', '0 4px 12px rgba(0, 0, 0, 0.1)')
        cardEl.style.setProperty('margin-bottom', '20px')
        cardEl.style.setProperty('overflow', 'hidden')
      } catch (err) {
        console.error('设置卡片样式失败:', err)
      }
    })

    // 处理卡片头部
    const cardHeads = exportContainer.querySelectorAll('.ant-card-head')
    cardHeads.forEach((head) => {
      const headEl = head as HTMLElement
      try {
        headEl.style.setProperty('background-color', '#667eea')
        headEl.style.setProperty('color', '#ffffff')
        headEl.style.setProperty('padding', '16px 24px')
        headEl.style.setProperty('font-size', '18px')
        headEl.style.setProperty('font-weight', '600')
      } catch (err) {
        console.error('设置卡片头部样式失败:', err)
      }
    })

    // 处理卡片内容
    const cardBodies = exportContainer.querySelectorAll('.ant-card-body')
    cardBodies.forEach((body) => {
      const bodyEl = body as HTMLElement
      bodyEl.style.setProperty('background-color', '#ffffff')
      bodyEl.style.setProperty('padding', '24px')
    })

    // 处理酒店卡片头部
    const hotelCards = exportContainer.querySelectorAll('.hotel-card')
    hotelCards.forEach((card) => {
      const head = card.querySelector('.ant-card-head') as HTMLElement
      if (head) {
        head.style.setProperty('background-color', '#1976d2')
      }
      (card as HTMLElement).style.setProperty('background-color', '#e3f2fd')
    })

    // 处理天气卡片
    const weatherCards = exportContainer.querySelectorAll('.weather-card')
    weatherCards.forEach((card) => {
      (card as HTMLElement).style.setProperty('background-color', '#e0f7fa')
    })

    // 处理预算总计
    const budgetTotal = exportContainer.querySelector('.budget-total')
    if (budgetTotal) {
      const el = budgetTotal as HTMLElement
      el.style.setProperty('background-color', '#667eea')
      el.style.setProperty('color', '#ffffff')
      el.style.setProperty('padding', '20px')
      el.style.setProperty('border-radius', '12px')
      el.style.setProperty('margin-bottom', '20px')
    }

    // 处理预算项
    const budgetItems = exportContainer.querySelectorAll('.budget-item')
    budgetItems.forEach((item) => {
      const el = item as HTMLElement
      el.style.setProperty('background-color', '#f5f7fa')
      el.style.setProperty('padding', '16px')
      el.style.setProperty('border-radius', '8px')
      el.style.setProperty('margin-bottom', '12px')
    })

    // 添加到body(隐藏)
    exportContainer.style.position = 'absolute'
    exportContainer.style.left = '-9999px'
    document.body.appendChild(exportContainer)

    const canvas = await html2canvas(exportContainer, {
      backgroundColor: '#f5f7fa',
      scale: 2,
      logging: false,
      useCORS: true,
      allowTaint: true
    })

    // 移除容器
    document.body.removeChild(exportContainer)

    const imgData = canvas.toDataURL('image/png')
    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4'
    })

    const imgWidth = 210 // A4宽度(mm)
    const imgHeight = (canvas.height * imgWidth) / canvas.width

    // 如果内容高度超过一页,分页处理
    let heightLeft = imgHeight
    let position = 0

    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight)
    heightLeft -= 297 // A4高度

    while (heightLeft > 0) {
      position = heightLeft - imgHeight
      pdf.addPage()
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight)
      heightLeft -= 297
    }

    pdf.save(`旅行计划_${tripPlan.value?.city}_${new Date().getTime()}.pdf`)

    message.success({ content: 'PDF导出成功!', key: 'export' })
  } catch (error: any) {
    console.error('导出PDF失败:', error)
    message.error({ content: `导出PDF失败: ${error.message}`, key: 'export' })
  }
}

// 初始化地图
const initMap = async () => {
  try {
    const AMap = await AMapLoader.load({
      key: import.meta.env.VITE_AMAP_WEB_JS_KEY,  // 高德地图Web端(JS API) Key
      version: '2.0',
      plugins: ['AMap.Marker', 'AMap.Polyline', 'AMap.InfoWindow']
    })

    // 创建地图实例
    map = new AMap.Map('amap-container', {
      zoom: 12,
      center: [116.397128, 39.916527], // 默认中心点(北京)
      viewMode: '3D'
    })

    // 添加景点标记
    addAttractionMarkers(AMap)

    message.success('地图加载成功')
  } catch (error) {
    console.error('地图加载失败:', error)
    message.error('地图加载失败')
  }
}

// 添加景点标记
const addAttractionMarkers = (AMap: any) => {
  if (!tripPlan.value) return

  const markers: any[] = []
  const allAttractions: any[] = []

  // 收集所有景点
  tripPlan.value.days.forEach((day, dayIndex) => {
    day.attractions.forEach((attraction, attrIndex) => {
      if (attraction.location && attraction.location.longitude && attraction.location.latitude) {
        allAttractions.push({
          ...attraction,
          dayIndex,
          attrIndex
        })
      }
    })
  })

  // 创建标记
  allAttractions.forEach((attraction, index) => {
    const marker = new AMap.Marker({
      position: [attraction.location.longitude, attraction.location.latitude],
      title: attraction.name,
      label: {
        content: `<div style="background: #4CAF50; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px;">${index + 1}</div>`,
        offset: new AMap.Pixel(0, -30)
      }
    })

    // 创建信息窗口
    const infoWindow = new AMap.InfoWindow({
      content: `
        <div style="padding: 10px;">
          <h4 style="margin: 0 0 8px 0;">${attraction.name}</h4>
          <p style="margin: 4px 0;"><strong>地址:</strong> ${attraction.address}</p>
          <p style="margin: 4px 0;"><strong>游览时长:</strong> ${attraction.visit_duration}分钟</p>
          <p style="margin: 4px 0;"><strong>描述:</strong> ${attraction.description}</p>
          <p style="margin: 4px 0; color: #1890ff;"><strong>第${attraction.dayIndex + 1}天 景点${attraction.attrIndex + 1}</strong></p>
        </div>
      `,
      offset: new AMap.Pixel(0, -30)
    })

    // 点击标记显示信息窗口
    marker.on('click', () => {
      infoWindow.open(map, marker.getPosition())
    })

    markers.push(marker)
  })

  // 添加标记到地图
  map.add(markers)

  // 自动调整视野以包含所有标记
  if (allAttractions.length > 0) {
    map.setFitView(markers)
  }

  // 绘制路线
  drawRoutes(AMap, allAttractions)
}

// 绘制路线
const drawRoutes = (AMap: any, attractions: any[]) => {
  if (attractions.length < 2) return

  // 按天分组绘制路线
  const dayGroups: any = {}
  attractions.forEach(attr => {
    if (!dayGroups[attr.dayIndex]) {
      dayGroups[attr.dayIndex] = []
    }
    dayGroups[attr.dayIndex].push(attr)
  })

  // 为每天的景点绘制路线
  Object.values(dayGroups).forEach((dayAttractions: any) => {
    if (dayAttractions.length < 2) return

    const path = dayAttractions.map((attr: any) => [
      attr.location.longitude,
      attr.location.latitude
    ])

    const polyline = new AMap.Polyline({
      path: path,
      strokeColor: '#1890ff',
      strokeWeight: 4,
      strokeOpacity: 0.8,
      strokeStyle: 'solid',
      showDir: true // 显示方向箭头
    })

    map.add(polyline)
  })
}
</script>

<style scoped>
.result-container {
  min-height: 100vh;
  background: transparent;
  padding: 40px 20px;
}

.page-header {
  max-width: 1200px;
  margin: 0 auto 30px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  animation: fadeInDown 0.6s ease-out;
}

.back-button {
  border-radius: 8px;
  font-weight: 500;
}

/* 内容布局 */
.content-wrapper {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  gap: 24px;
}

.side-nav {
  width: 240px;
  flex-shrink: 0;
}

.side-nav :deep(.ant-menu) {
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.93);
  backdrop-filter: blur(16px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow: 0 12px 36px rgba(2, 6, 23, 0.35);
}

.side-nav :deep(.ant-menu-item) {
  margin: 4px 8px;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.side-nav :deep(.ant-menu-item-selected) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.side-nav :deep(.ant-menu-item:hover) {
  background: rgba(102, 126, 234, 0.1);
}

.main-content {
  flex: 1;
  min-width: 0;
}

/* 景点图片样式 */
.attraction-image-wrapper {
  position: relative;
  margin-bottom: 12px;
  border-radius: 8px;
  overflow: hidden;
}

/* 景点描述: 保留换行, 展示知识库多行详情 (门票/开放时间/交通/避坑) */
.attraction-desc {
  white-space: pre-line;
  color: #666;
  font-size: 13px;
  line-height: 1.6;
}

.attraction-image {
  width: 100%;
  height: 200px;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.attraction-image-wrapper:hover .attraction-image {
  transform: scale(1.05);
}

.attraction-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.badge-number {
  font-size: 18px;
}

.price-tag {
  position: absolute;
  top: 12px;
  right: 12px;
  background: rgba(255, 77, 79, 0.9);
  color: white;
  padding: 4px 12px;
  border-radius: 12px;
  font-weight: bold;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* 天气卡片样式 */
.weather-card {
  background: linear-gradient(135deg, #e0f7fa 0%, #b2ebf2 100%);
  border: none !important;
  transition: all 0.3s ease;
}

.weather-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
}

.weather-date {
  font-size: 16px;
  font-weight: bold;
  color: #00796b;
  margin-bottom: 12px;
  text-align: center;
}

.weather-info-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.weather-icon {
  font-size: 24px;
}

.weather-label {
  font-size: 12px;
  color: #666;
}

.weather-value {
  font-size: 16px;
  font-weight: 600;
  color: #00796b;
}

.weather-wind {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 121, 107, 0.2);
  text-align: center;
  color: #00796b;
  font-size: 14px;
}

/* 回到顶部按钮 */
.back-top-button {
  width: 50px;
  height: 50px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: bold;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  cursor: pointer;
  transition: all 0.3s ease;
}

.back-top-button:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
}

/* 酒店卡片样式 */
.hotel-card {
  background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
  border: none !important;
}

.hotel-card :deep(.ant-card-head) {
  background: linear-gradient(135deg, #1976d2 0%, #1565c0 100%);
}

.hotel-title {
  color: white !important;
  font-weight: 600;
}

/* 顶部信息区布局 */
.top-info-section {
  display: flex;
  gap: 20px;
  margin-bottom: 20px;
}

.left-info {
  flex: 0 0 400px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.right-map {
  flex: 1;
}

/* 行程概览卡片 */
.overview-card {
  height: fit-content;
}

.overview-days {
  color: #667eea;
  font-weight: 600;
  font-size: 13px;
  background: rgba(102, 126, 234, 0.1);
  padding: 4px 12px;
  border-radius: 12px;
}

.overview-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 概览统计 */
.overview-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 4px 0;
}

.stat-box {
  text-align: center;
  padding: 12px 4px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 10px;
  border: 1px solid #e8e8e8;
}

.stat-num {
  font-size: 20px;
  font-weight: 700;
  color: #667eea;
}

.stat-label {
  font-size: 12px;
  color: #999;
  margin-top: 2px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 14px;
  font-weight: 600;
  color: #666;
}

.info-value {
  font-size: 15px;
  color: #333;
  line-height: 1.6;
}

/* 预算卡片 */
.budget-card {
  height: fit-content;
}

.budget-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.budget-item {
  text-align: center;
  padding: 12px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 8px;
  border: 1px solid #e8e8e8;
}

.budget-label {
  font-size: 13px;
  color: #666;
  margin-bottom: 8px;
}

.budget-value {
  font-size: 20px;
  font-weight: 700;
  color: #1890ff;
}

.budget-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 8px;
  color: white;
}

.total-label {
  font-size: 16px;
  font-weight: 600;
}

.total-value {
  font-size: 28px;
  font-weight: 700;
}

/* 地图卡片 */
.map-card {
  height: 100%;
  min-height: 500px;
}

.map-card :deep(.ant-card-body) {
  height: calc(100% - 57px);
  padding: 0;
}

/* 每日行程卡片 */
.days-card {
  margin-top: 20px;
}

/* 天气信息卡片 */
.weather-section {
  margin-top: 20px;
}

.day-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.day-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.day-date {
  font-size: 14px;
  color: #999;
}

.day-info {
  margin-bottom: 20px;
  padding: 16px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 8px;
  border: 1px solid #e8e8e8;
}

.info-row {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-row .label {
  font-weight: 600;
  color: #666;
  min-width: 100px;
}

.info-row .value {
  color: #333;
  flex: 1;
}

/* 卡片样式优化 */
:deep(.ant-card) {
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  margin-bottom: 20px;
  transition: all 0.3s ease;
  animation: fadeInUp 0.6s ease-out;
}

:deep(.ant-card:hover) {
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

:deep(.ant-card-head) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white !important;
  border-radius: 12px 12px 0 0;
  font-weight: 600;
}

:deep(.ant-card-head-title) {
  color: white !important;
  font-size: 18px;
}

:deep(.ant-card-head-title span) {
  color: white !important;
}

/* Collapse样式 */
:deep(.ant-collapse) {
  border: none;
  background: transparent;
}

:deep(.ant-collapse-item) {
  margin-bottom: 16px;
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  overflow: hidden;
}

:deep(.ant-collapse-header) {
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  padding: 16px 20px !important;
  font-weight: 600;
}

:deep(.ant-collapse-content) {
  border-top: 1px solid #e8e8e8;
}

:deep(.ant-collapse-content-box) {
  padding: 20px;
}

/* 统计卡片样式 */
:deep(.ant-statistic-title) {
  font-size: 14px;
  color: #666;
  margin-bottom: 8px;
}

:deep(.ant-statistic-content) {
  font-size: 24px;
  font-weight: 600;
  color: #1890ff;
}

/* 景点卡片样式 */
:deep(.ant-list-item) {
  transition: all 0.3s ease;
}

:deep(.ant-list-item:hover) {
  transform: scale(1.02);
}

/* 动画 */
@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* ============ 餐厅候选择 ============ */
.meal-picker-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.meal-picker-item {
  border: 1px solid #e8e8e8;
  border-radius: 10px;
  padding: 12px 16px;
  background: #fafbff;
}

.meal-selected-main,
.meal-unselected {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.meal-type-badge {
  display: inline-block;
  min-width: 44px;
  text-align: center;
  padding: 2px 10px;
  border-radius: 6px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}

.meal-rest-name {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}

.meal-dishes {
  margin-top: 6px;
  font-size: 13px;
  color: #666;
}

.meal-hint {
  color: #999;
  font-size: 13px;
  flex: 1;
}

/* 查景点周边餐厅按钮: 白底黑字 */
.meal-search-btn {
  background: #fff !important;
  color: #333 !important;
  border: 1px solid #d9d9d9 !important;
  font-weight: 500;
}

.meal-search-btn:hover {
  background: #fff !important;
  color: #1890ff !important;
  border-color: #1890ff !important;
}

.meal-search-btn:active,
.meal-search-btn:focus {
  background: #fff !important;
  color: #333 !important;
}

.meal-candidates {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #d9d9d9;
}

/* 价位双滑块 */
.price-slider-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
  padding: 8px 12px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #eef0f7;
}

.slider-label {
  font-size: 13px;
  color: #666;
  white-space: nowrap;
}

.price-slider {
  flex: 1;
  min-width: 180px;
  margin: 4px 10px;
}

.slider-value {
  font-size: 13px;
  font-weight: 600;
  color: #667eea;
  white-space: nowrap;
  min-width: 90px;
  text-align: right;
}

.candidate-summary {
  font-size: 12px;
  color: #888;
  margin-bottom: 10px;
}

.cache-hint {
  color: #52c41a;
}

.anchor-hint {
  color: #667eea;
  font-weight: 600;
}

.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.candidate-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #eef0f7;
  border-radius: 8px;
  transition: all 0.25s ease;
}

.candidate-row:hover {
  border-color: #667eea;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.12);
}

.candidate-main {
  flex: 1;
  min-width: 0;
}

.candidate-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.candidate-name {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}

.candidate-dishes {
  margin-top: 5px;
  font-size: 13px;
  color: #555;
  line-height: 1.5;
}

.dishes-label {
  color: #999;
}

.candidate-addr {
  margin-top: 3px;
  font-size: 12px;
  color: #aaa;
}

.meal-error {
  padding: 12px;
  color: #cf1322;
  background: #fff1f0;
  border-radius: 8px;
  font-size: 13px;
}

.scope-notice {
  margin-top: 10px;
  padding: 8px 10px;
  font-size: 12px;
  color: #8c8c8c;
  background: #f5f5f5;
  border-radius: 6px;
  line-height: 1.6;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .result-container {
    padding: 20px 10px;
  }

  .page-header {
    flex-direction: column;
    gap: 16px;
  }

  .candidate-row {
    flex-direction: column;
    align-items: stretch;
  }

  .price-slider-row {
    flex-wrap: wrap;
  }

  .slider-value {
    text-align: left;
  }
}
</style>

