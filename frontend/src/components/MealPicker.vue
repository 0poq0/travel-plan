<template>
  <div class="meal-picker-item">
    <!-- 已选定餐厅 -->
    <div v-if="meal.selected" class="meal-selected">
      <div class="meal-selected-main">
        <span class="meal-type-badge">{{ getMealLabel(meal.type) }}</span>
        <span class="meal-rest-name">{{ meal.name }}</span>
        <a-tag v-if="meal.rating" color="orange">{{ meal.rating }}⭐</a-tag>
        <a-tag v-if="meal.cost">人均¥{{ meal.cost }}</a-tag>
        <a-tag v-if="meal.distance !== undefined">{{ meal.distance }}米</a-tag>
      </div>
      <div v-if="meal.tags && meal.tags.length" class="meal-dishes">
        招牌: {{ meal.tags.slice(0, 5).join('、') }}
      </div>
      <a-button v-if="!editMode" size="small" type="link" @click="$emit('load')">
        🔄 换一家
      </a-button>
    </div>

    <!-- 未选择: 提示用户主动挑选 -->
    <div v-else class="meal-unselected">
      <span class="meal-type-badge">{{ getMealLabel(meal.type) }}</span>
      <span class="meal-hint">{{ meal.description || '可从景点周边候选餐厅中选择' }}</span>
      <a-button
        size="small"
        class="meal-search-btn"
        :loading="picker.loading"
        @click="$emit('load')"
      >
        🔍 查景点周边餐厅
      </a-button>
    </div>

    <!-- 候选列表 -->
    <div v-if="picker.loaded || picker.loading" class="meal-candidates">
      <!-- 价位双滑块: 候选池已缓存, 拖动只做内存重排 -->
      <div class="price-slider-row">
        <span class="slider-label">人均价位</span>
        <a-slider
          class="price-slider"
          range
          :min="picker.bounds[0]"
          :max="picker.bounds[1]"
          v-model:value="picker.range"
          @afterChange="$emit('change-range')"
        />
        <span class="slider-value">
          ¥{{ picker.range[0] }} - ¥{{ picker.range[1] }}
        </span>
      </div>

      <a-spin :spinning="picker.loading">
        <div v-if="picker.error" class="meal-error">⚠️ {{ picker.error }}</div>

        <a-empty
          v-else-if="!picker.candidates.length"
          description="该价位区间内没有符合条件的餐厅, 可放宽价位"
        />

        <div v-else class="candidate-list">
          <div class="candidate-summary">
            <span v-if="picker.anchorName" class="anchor-hint">
              📍 以「{{ picker.anchorName }}」为中心 ·
            </span>
            共 {{ picker.total }} 家符合条件,
            以下为综合排序前 {{ picker.candidates.length }} 家
            <span v-if="picker.cached" class="cache-hint">
              (候选池已缓存, 调整价位不会重复请求地图接口)
            </span>
          </div>

          <div v-for="c in picker.candidates" :key="c.poi_id" class="candidate-row">
            <div class="candidate-main">
              <div class="candidate-title">
                <span class="candidate-name">{{ c.name }}</span>
                <a-tag v-if="c.rating" color="orange">{{ c.rating }}⭐</a-tag>
                <a-tag v-if="c.cost">人均¥{{ c.cost }}</a-tag>
                <a-tag color="blue">{{ distanceText(c) }}</a-tag>
                <a-tag v-if="c.cuisine">{{ c.cuisine }}</a-tag>
                <a-tag v-for="hit in c.list_hits" :key="hit" color="green">{{ hit }}</a-tag>
              </div>
              <div class="candidate-dishes">
                <span class="dishes-label">卖什么:</span> {{ dishesText(c) }}
              </div>
              <div v-if="c.address" class="candidate-addr">{{ c.address }}</div>
            </div>
            <a-button type="primary" size="small" @click="$emit('select', c)">
              选这家
            </a-button>
          </div>

          <div class="scope-notice">ⓘ {{ picker.scopeNotice }}</div>
        </div>
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Meal, RestaurantCandidate } from '@/types'

/** 餐段选择状态 (由父组件维护, 见 Result.vue 的 MealPickerState) */
interface PickerState {
  loading: boolean
  candidates: RestaurantCandidate[]
  bounds: number[]
  range: number[]
  total: number
  loaded: boolean
  cached: boolean
  scopeNotice: string
  error: string
  anchorName: string
}

defineProps<{
  meal: Meal
  dayIndex: number
  editMode: boolean
  picker: PickerState
}>()

defineEmits<{
  (e: 'load'): void
  (e: 'change-range'): void
  (e: 'select', c: RestaurantCandidate): void
}>()

const getMealLabel = (type: string): string => {
  const labels: Record<string, string> = {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐',
    snack: '小吃'
  }
  return labels[type] || type
}

/** 显示"卖什么": 高德 tag 里的真实招牌菜 */
const dishesText = (c: RestaurantCandidate): string =>
  c.signature_dishes && c.signature_dishes.length
    ? c.signature_dishes.slice(0, 5).join('、')
    : '暂无招牌菜数据'

const distanceText = (c: RestaurantCandidate): string =>
  c.distance === null || c.distance === undefined ? '距离未知' : `${c.distance}米`
</script>

<style scoped>
/* 样式随组件一起迁移(原在 Result.vue 的 scoped 样式块中) */
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

.meal-rest-name { font-size: 15px; font-weight: 600; color: #333; }

.meal-dishes { margin-top: 6px; font-size: 13px; color: #666; }

.meal-hint { color: #999; font-size: 13px; flex: 1; }

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

.slider-label { font-size: 13px; color: #666; white-space: nowrap; }

.price-slider { flex: 1; min-width: 180px; margin: 4px 10px; }

.slider-value {
  font-size: 13px;
  font-weight: 600;
  color: #667eea;
  white-space: nowrap;
  min-width: 90px;
  text-align: right;
}

.candidate-summary { font-size: 12px; color: #888; margin-bottom: 10px; }

.cache-hint { color: #52c41a; }

.anchor-hint { color: #667eea; font-weight: 600; }

.candidate-list { display: flex; flex-direction: column; gap: 10px; }

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

.candidate-main { flex: 1; min-width: 0; }

.candidate-title { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }

.candidate-name { font-size: 15px; font-weight: 600; color: #333; }

.candidate-dishes { margin-top: 5px; font-size: 13px; color: #555; line-height: 1.5; }

.dishes-label { color: #999; }

.candidate-addr { margin-top: 3px; font-size: 12px; color: #aaa; }

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

@media (max-width: 768px) {
  .candidate-row { flex-direction: column; align-items: stretch; }
  .price-slider-row { flex-wrap: wrap; }
  .slider-value { text-align: left; }
}
</style>
