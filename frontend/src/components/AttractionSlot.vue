<template>
  <a-list :data-source="items" :grid="{ gutter: 16, column: 2 }">
    <template #renderItem="{ item, index }">
      <a-list-item>
        <a-card :title="item.name" size="small" class="attraction-card">
          <!-- 编辑模式下的操作按钮 -->
          <template #extra v-if="editMode">
            <a-space>
              <a-button
                size="small"
                @click="$emit('move', index, 'up')"
                :disabled="index === 0"
              >
                ↑
              </a-button>
              <a-button
                size="small"
                @click="$emit('move', index, 'down')"
                :disabled="index === items.length - 1"
              >
                ↓
              </a-button>
              <a-button size="small" danger @click="$emit('remove', index)">
                🗑️
              </a-button>
            </a-space>
          </template>

          <!-- 景点图片 -->
          <div class="attraction-image-wrapper">
            <img
              :src="getAttractionImage(item.name, index)"
              :alt="item.name"
              class="attraction-image"
              @error="handleImageError"
            />
            <div class="attraction-badge">
              <span class="badge-number">{{ index + 1 }}</span>
            </div>
            <div v-if="item.ticket_price" class="price-tag">
              ¥{{ item.ticket_price }}
            </div>
          </div>

          <!-- 编辑模式 -->
          <div v-if="editMode">
            <p><strong>地址:</strong></p>
            <a-input v-model:value="item.address" size="small" style="margin-bottom: 8px" />

            <p><strong>游览时长(分钟):</strong></p>
            <a-input-number v-model:value="item.visit_duration" :min="10" :max="480" size="small" style="width: 100%; margin-bottom: 8px" />

            <p><strong>描述:</strong></p>
            <a-textarea v-model:value="item.description" :rows="2" size="small" style="margin-bottom: 8px" />
          </div>

          <!-- 查看模式 -->
          <div v-else>
            <p><strong>地址:</strong> {{ item.address }}</p>
            <p><strong>游览时长:</strong> {{ item.visit_duration }}分钟</p>
            <p><strong>描述:</strong> <span class="attraction-desc">{{ item.description }}</span></p>
            <p v-if="item.rating"><strong>评分:</strong> {{ item.rating }}⭐</p>
          </div>
        </a-card>
      </a-list-item>
    </template>
  </a-list>
</template>

<script setup lang="ts">
import type { Attraction } from '@/types'

const props = defineProps<{
  /** 该时段的景点 */
  items: Attraction[]
  /** 是否处于编辑模式 */
  editMode: boolean
  /** 景点图片映射: 名称 -> 图片URL (由 Result.vue 预加载后传入) */
  photos: Record<string, string>
}>()

defineEmits<{
  (e: 'move', index: number, direction: 'up' | 'down'): void
  (e: 'remove', index: number): void
}>()

// 取景点图片: 已加载的真实图片优先, 否则用渐变占位图(避免跨域问题)
const getAttractionImage = (name: string, index: number): string => {
  const real = props.photos?.[name]
  if (real) return real

  const colors = [
    { start: '#667eea', end: '#764ba2' },
    { start: '#f093fb', end: '#f5576c' },
    { start: '#4facfe', end: '#00f2fe' },
    { start: '#43e97b', end: '#38f9d7' },
    { start: '#fa709a', end: '#fee140' }
  ]
  const { start, end } = colors[index % colors.length]

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">
    <defs>
      <linearGradient id="grad${index}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" style="stop-color:${start};stop-opacity:1" />
        <stop offset="100%" style="stop-color:${end};stop-opacity:1" />
      </linearGradient>
    </defs>
    <rect width="400" height="300" fill="url(#grad${index})"/>
    <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="24" font-weight="bold" fill="white">${name}</text>
  </svg>`

  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
}

const handleImageError = (event: Event) => {
  const img = event.target as HTMLImageElement
  img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="400" height="300"%3E%3Crect width="400" height="300" fill="%23f0f0f0"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18" fill="%23999"%3E图片加载失败%3C/text%3E%3C/svg%3E'
}
</script>

<style scoped>
/* 说明: 这些样式原先写在 Result.vue 的 scoped 样式块里, 但景点卡片现在由本组件
   渲染, 父组件的 scoped 样式匹配不到子组件元素 —— 导致 .attraction-image 的
   height 约束失效, 图片按原始尺寸撑大(实测问题)。故随组件迁移到这里。 */

.attraction-image-wrapper {
  position: relative;
  margin-bottom: 10px;
  border-radius: 8px;
  overflow: hidden;
  height: 130px;          /* 固定高度, 防止大图撑开卡片 */
  background: #f5f7fa;
}

.attraction-image {
  width: 100%;
  height: 130px;
  object-fit: cover;
  display: block;
  transition: transform 0.3s ease;
}

.attraction-image-wrapper:hover .attraction-image {
  transform: scale(1.05);
}

.attraction-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.badge-number { font-size: 13px; }

.price-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(255, 77, 79, 0.9);
  color: white;
  padding: 2px 9px;
  border-radius: 10px;
  font-weight: bold;
  font-size: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* 景点描述: 保留换行, 展示知识库多行详情(门票/开放时间/交通/避坑) */
.attraction-desc {
  white-space: pre-line;
  color: #666;
  font-size: 13px;
  line-height: 1.6;
}

/* 卡片内文字紧凑一些, 整体更小 */
:deep(.ant-card-body) { padding: 12px; }

:deep(.ant-card-head) {
  min-height: 40px;
  padding: 0 12px;
  font-size: 14px;
}
</style>
