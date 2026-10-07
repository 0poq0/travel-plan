<template>
  <div class="hotel-container">
    <!-- 背景装饰 (与首页一致的视觉风格) -->
    <div class="bg-decoration">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>

    <a-button class="back-btn" @click="goBack">← 返回修改</a-button>

    <div class="page-header">
      <div class="brand-badge">🏨 第 2 步 / 共 2 步</div>
      <div class="icon-wrapper"><span class="icon">🏨</span></div>
      <h1 class="page-title">选择住宿酒店</h1>
      <p class="page-subtitle">
        已按你在首页选择的「{{ formData.accommodation }}」档次筛出候选，
        选定后整个行程都住这一家
      </p>
    </div>

    <a-card class="main-card" :bordered="false">
      <!-- 顶部信息 -->
      <div class="trip-summary">
        <span>🏙️ {{ formData.city }}</span>
        <span>📅 {{ formData.start_date }} 至 {{ formData.end_date }}</span>
        <span>🌙 {{ formData.travel_days }} 天</span>
        <span>🏨 {{ formData.accommodation }}</span>
        <span v-if="priceRange.length === 2" class="ref-price">
          参考价位 ¥{{ priceRange[0] }}-{{ priceRange[1] }}/晚（档次估算，高德不提供实际房价）
        </span>
      </div>

      <a-spin :spinning="loading" tip="正在获取酒店...">
        <a-row :gutter="20">
          <!-- 左: 酒店列表 -->
          <a-col :xs="24" :md="12">
            <div class="list-title">
              共 {{ hotels.length }} 家（按下拉档次筛选，评分优先）
            </div>
            <div class="hotel-list">
              <div
                v-for="h in hotels"
                :key="h.poi_id"
                class="hotel-item"
                :class="{ active: selected?.poi_id === h.poi_id }"
                @click="selectHotel(h)"
              >
                <div class="hotel-item-main">
                  <div class="hotel-name">{{ h.name }}</div>
                  <div class="hotel-meta">
                    <a-tag v-if="h.rating" color="orange">{{ h.rating }}⭐</a-tag>
                    <a-tag v-if="h.type">{{ h.type }}</a-tag>
                    <a-tag v-if="!h.location" color="red">无坐标</a-tag>
                  </div>
                  <div class="hotel-addr">{{ h.address || '地址未提供' }}</div>
                </div>
                <a-button
                  size="small"
                  :type="selected?.poi_id === h.poi_id ? 'primary' : 'default'"
                  @click.stop="selectHotel(h)"
                >
                  {{ selected?.poi_id === h.poi_id ? '✓ 已选' : '选这家' }}
                </a-button>
              </div>

              <a-empty v-if="!loading && !hotels.length" description="该档次没有找到酒店，请返回换一个档次" />
            </div>
          </a-col>

          <!-- 右: 地图 -->
          <a-col :xs="24" :md="12">
            <div class="list-title">地图分布（{{ locatedCount }} 家有坐标）</div>
            <div id="hotel-map" class="hotel-map"></div>
            <div class="map-hint">点击地图上的标记可选中该酒店</div>
          </a-col>
        </a-row>
      </a-spin>

      <!-- 底部操作 -->
      <div class="footer-actions">
        <div class="chosen">
          <template v-if="selected">
            已选：<strong>{{ selected.name }}</strong>
          </template>
          <template v-else>
            <span class="tip">请从列表中选一家酒店，然后开始生成行程</span>
          </template>
        </div>
        <a-button
          type="primary"
          size="large"
          class="submit-button"
          :loading="generating"
          :disabled="!selected"
          @click="startPlan"
        >
          <template v-if="!generating">🚀 开始规划我的旅行</template>
          <template v-else>正在生成中...</template>
        </a-button>
      </div>

      <a-progress v-if="generating" :percent="progress" status="active" />
    </a-card>

    <div class="page-footer">Powered by LangChain · LangGraph · FastAPI · 高德地图</div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import AMapLoader from '@amap/amap-jsapi-loader'
import { fetchHotels, generateTripPlan } from '@/services/api'
import type { HotelItem } from '@/types'

const router = useRouter()

// 首页传来的表单数据
const formData = reactive<any>({
  city: '',
  start_date: '',
  end_date: '',
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: [],
  free_text_input: ''
})

const hotels = ref<HotelItem[]>([])
const selected = ref<HotelItem | null>(null)
const priceRange = ref<number[]>([])
const loading = ref(false)
const generating = ref(false)
const progress = ref(0)
let map: any = null
let markers: any[] = []

const locatedCount = computed(() => hotels.value.filter(h => h.location).length)

const goBack = () => router.push('/')

/** 选中酒店: 同步高亮地图标记 */
const selectHotel = (h: HotelItem) => {
  selected.value = h
  if (h.location && map) {
    map.setCenter([h.location.longitude, h.location.latitude])
    map.setZoom(14)
  }
}

/** 加载该档次的酒店 */
const loadHotels = async () => {
  loading.value = true
  try {
    const res = await fetchHotels({
      city: formData.city,
      tier: formData.accommodation,
      limit: 30
    })
    hotels.value = res.data || []
    priceRange.value = res.price_range || []
    await nextTick()
    initMap()
  } catch (e: any) {
    message.error(e.message || '获取酒店列表失败')
  } finally {
    loading.value = false
  }
}

/** 初始化地图并标出所有酒店 */
const initMap = () => {
  const located = hotels.value.filter(h => h.location)
  if (!located.length) return

  AMapLoader.load({
    key: import.meta.env.VITE_AMAP_WEB_JS_KEY || '',
    version: '2.0',
    plugins: ['AMap.Marker', 'AMap.InfoWindow']
  })
    .then((AMap: any) => {
      map = new AMap.Map('hotel-map', {
        zoom: 11,
        center: [
          located[0].location!.longitude,
          located[0].location!.latitude
        ]
      })

      markers.forEach(m => m.setMap(null))
      markers = []

      located.forEach(h => {
        const marker = new AMap.Marker({
          position: [h.location!.longitude, h.location!.latitude],
          title: h.name
        })
        marker.on('click', () => selectHotel(h))
        marker.setMap(map)
        markers.push(marker)
      })

      // 自动缩放到包含全部标记
      if (markers.length > 1) {
        map.setFitView(markers)
      }
    })
    .catch((e: any) => {
      console.error('地图加载失败:', e)
      message.warning('地图加载失败，不影响酒店选择')
    })
}

/** 用选定的酒店生成行程 */
const startPlan = async () => {
  if (!selected.value) {
    message.warning('请先选择一家酒店')
    return
  }
  generating.value = true
  progress.value = 10
  const timer = setInterval(() => {
    if (progress.value < 90) progress.value += 10
  }, 600)

  try {
    const payload = {
      ...formData,
      hotel: {
        name: selected.value.name,
        address: selected.value.address,
        location: selected.value.location,
        rating: selected.value.rating,
        type: selected.value.type,
        poi_id: selected.value.poi_id,
        tier: formData.accommodation
      }
    }
    progress.value = 40
    const res = await generateTripPlan(payload)
    clearInterval(timer)
    progress.value = 100

    if (res.success && res.data) {
      sessionStorage.setItem('tripPlan', JSON.stringify(res.data))
      sessionStorage.removeItem('tripPlanId')
      message.success('旅行计划生成成功!')
      setTimeout(() => router.push('/result'), 400)
    } else {
      message.error(res.message || '生成失败')
    }
  } catch (e: any) {
    clearInterval(timer)
    message.error(e.message || '生成旅行计划失败')
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  const raw = sessionStorage.getItem('tripFormData')
  if (!raw) {
    message.warning('请先在首页填写行程信息')
    router.push('/')
    return
  }
  Object.assign(formData, JSON.parse(raw))
  await loadHotels()
})
</script>

<style scoped>
/* 视觉风格与首页保持一致 */
.hotel-container {
  min-height: 100vh;
  padding: 60px 20px;
  position: relative;
  overflow: hidden;
}

.back-btn {
  position: fixed;
  top: 20px;
  left: 24px;
  z-index: 10;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  border: none;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  font-weight: 500;
}

.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.circle {
  position: absolute;
  border-radius: 50%;
  animation: float 20s infinite ease-in-out;
}

.circle-1 {
  width: 320px; height: 320px; top: -100px; left: -100px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.28), transparent 70%);
}

.circle-2 {
  width: 240px; height: 240px; top: 50%; right: -60px; animation-delay: 5s;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.24), transparent 70%);
}

.circle-3 {
  width: 180px; height: 180px; bottom: -60px; left: 30%; animation-delay: 10s;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.2), transparent 70%);
}

@keyframes float {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-30px) rotate(180deg); }
}

.page-header {
  text-align: center;
  margin-bottom: 32px;
  position: relative;
  z-index: 1;
}

.brand-badge {
  display: inline-block;
  padding: 6px 18px;
  margin-bottom: 20px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  color: #667eea;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.icon-wrapper { margin-bottom: 12px; }

.icon { font-size: 64px; display: inline-block; animation: bounce 2s infinite; }

@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-16px); }
}

.page-title {
  font-size: 44px;
  font-weight: 800;
  margin-bottom: 12px;
  letter-spacing: 2px;
  background: linear-gradient(135deg, #a5b4fc 0%, #e0e7ff 40%, #c4b5fd 70%, #99f6e4 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 4px 18px rgba(139, 92, 246, 0.45));
}

.page-subtitle {
  font-size: 17px;
  color: rgba(226, 232, 255, 0.9);
  margin: 0;
  font-weight: 300;
}

.main-card {
  max-width: 1180px;
  margin: 0 auto;
  border-radius: 24px;
  position: relative;
  z-index: 1;
  backdrop-filter: blur(20px) saturate(150%);
  background: rgba(255, 255, 255, 0.95) !important;
  border: 1px solid rgba(255, 255, 255, 0.55) !important;
  box-shadow: 0 30px 80px rgba(2, 6, 23, 0.5);
}

.trip-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  padding: 12px 16px;
  margin-bottom: 18px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  font-size: 14px;
  color: #555;
}

.ref-price { color: #999; font-size: 12px; }

.list-title {
  font-size: 14px;
  font-weight: 600;
  color: #555;
  margin-bottom: 10px;
}

.hotel-list {
  max-height: 520px;
  overflow-y: auto;
  padding-right: 6px;
}

.hotel-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 10px;
  background: #fff;
  border: 2px solid #eef0f7;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.22s ease;
}

.hotel-item:hover { border-color: #667eea; box-shadow: 0 4px 14px rgba(102, 126, 234, 0.14); }

.hotel-item.active {
  border-color: #667eea;
  background: linear-gradient(135deg, #f0f3ff 0%, #ffffff 100%);
}

.hotel-item-main { flex: 1; min-width: 0; }

.hotel-name { font-size: 15px; font-weight: 600; color: #333; }

.hotel-meta { margin: 5px 0; display: flex; flex-wrap: wrap; gap: 5px; }

.hotel-addr { font-size: 12px; color: #999; }

.hotel-map {
  width: 100%;
  height: 460px;
  border-radius: 12px;
  border: 1px solid #e8e8e8;
  background: #f5f7fa;
}

.map-hint { margin-top: 8px; font-size: 12px; color: #aaa; }

.footer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #eee;
  flex-wrap: wrap;
}

.chosen { font-size: 15px; color: #555; }
.chosen .tip { color: #999; font-size: 14px; }

.submit-button {
  min-width: 260px;
  height: 50px;
  border-radius: 25px;
  font-size: 17px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.4);
}

.page-footer {
  text-align: center;
  margin-top: 32px;
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  position: relative;
  z-index: 1;
}

@media (max-width: 768px) {
  .page-title { font-size: 32px; }
  .hotel-map { height: 300px; }
  .submit-button { min-width: 100%; }
}
</style>
