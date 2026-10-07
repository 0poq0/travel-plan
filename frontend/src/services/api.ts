import axios from 'axios'
import type {
  TripFormData,
  TripPlanResponse,
  RestaurantListResponse,
  HotelListResponse
} from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000, // 2分钟超时
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    console.log('发送请求:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.message)
    return Promise.reject(error)
  }
)

/**
 * 按住宿档次获取酒店列表 (选酒店页使用)
 *
 * 高德不提供酒店实际房价, price_range 是该档次的参考估算区间。
 */
export async function fetchHotels(params: {
  city: string
  tier: string
  limit?: number
}): Promise<HotelListResponse> {
  try {
    const response = await apiClient.get<HotelListResponse>('/api/hotel/list', {
      params
    })
    return response.data
  } catch (error: any) {
    console.error('获取酒店列表失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '获取酒店列表失败')
  }
}

/**
 * 生成旅行计划
 */
export async function generateTripPlan(formData: TripFormData): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/trip/plan', formData)
    return response.data
  } catch (error: any) {
    console.error('生成旅行计划失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '生成旅行计划失败')
  }
}

/**
 * 查询景点周边餐厅候选 (按餐段)
 *
 * 后端候选池按「城市+锚点+餐段」缓存, 调整价位区间只做内存重排,
 * 不会重复请求高德, 所以拖滑块可以放心实时调用。
 *
 * @param city 城市
 * @param mealType 餐段 lunch/dinner (早餐已排除)
 * @param anchor 锚点坐标(当天景点), 用于周边搜索与距离计算
 * @param minCost/maxCost 价位区间(人均元), 对应双滑块
 */
export async function fetchRestaurants(params: {
  city: string
  meal_type: 'lunch' | 'dinner'
  lng?: number
  lat?: number
  min_cost?: number
  max_cost?: number
}): Promise<RestaurantListResponse> {
  try {
    const response = await apiClient.get<RestaurantListResponse>('/api/poi/restaurants', {
      params
    })
    return response.data
  } catch (error: any) {
    console.error('查询餐厅候选失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '查询餐厅候选失败')
  }
}

/**
 * 健康检查
 */
export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    console.error('健康检查失败:', error)
    throw new Error(error.message || '健康检查失败')
  }
}

/**
 * 查询历史行程列表 (分页)
 */
export async function fetchHistory(
  page: number = 1,
  pageSize: number = 10,
  city?: string
): Promise<any> {
  const response = await apiClient.get('/api/history', {
    params: { page, page_size: pageSize, city: city || undefined }
  })
  return response.data
}

/**
 * 查询历史行程详情 (含完整计划)
 */
export async function fetchHistoryDetail(id: number): Promise<any> {
  const response = await apiClient.get(`/api/history/${id}`)
  return response.data
}

/**
 * 更新历史行程 (编辑保存后持久化)
 */
export async function updateHistory(id: number, plan: any): Promise<any> {
  const response = await apiClient.put(`/api/history/${id}`, plan)
  return response.data
}

/**
 * 删除历史行程
 */
export async function deleteHistory(id: number): Promise<any> {
  const response = await apiClient.delete(`/api/history/${id}`)
  return response.data
}

export default apiClient

