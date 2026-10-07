// 类型定义

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string
  rating?: number
  image_url?: string
  ticket_price?: number
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
  /** 用户选定的餐厅 POI ID (从候选列表中选中后回填) */
  poi_id?: string
  /** 用户选定餐厅的评分 */
  rating?: number
  /** 用户选定餐厅的人均消费 */
  cost?: number
  /** 用户选定餐厅距景点距离(米) */
  distance?: number
  /** 用户选定餐厅的招牌菜 */
  tags?: string[]
  /** 是否已由用户从候选中确认选择 */
  selected?: boolean
}

/**
 * 餐厅候选 (供用户自行选择, 系统不代为决定)
 *
 * 【口径说明】榜单为近似口径: 后端用「状元榜/本地人爱去/烟火小店」
 * 作为关键词召回高德真实POI后自行打分排序, 非高德官方扫街榜排名。
 * 评分/人均消费/招牌菜均为高德真实字段。
 */
export interface RestaurantCandidate {
  poi_id: string
  name: string
  cuisine: string
  address: string
  location?: Location
  rating?: number
  cost?: number
  distance?: number
  signature_dishes: string[]
  list_hits: string[]
  business_area: string
  score: number
  score_detail: Record<string, number | boolean>
}

export interface RestaurantListResponse {
  success: boolean
  message: string
  data: RestaurantCandidate[]
  total: number
  cached: boolean
  price_range: number[]
}

export interface Hotel {
  name: string
  address: string
  location?: Location
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost?: number
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel
  /** 上午景点 */
  attractions_morning: Attraction[]
  /** 下午景点(午餐夹在上午与下午之间) */
  attractions_afternoon: Attraction[]
  /** 晚餐后 / 夜间可去景点 */
  attractions_evening: Attraction[]
  /** 三段合并(后端已填充, 供地图打点与统计使用) */
  attractions: Attraction[]
  meals: Meal[]
  morning_desc?: string
  afternoon_desc?: string
  evening_desc?: string
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget
}

export interface TripFormData {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
  /** 用户在"选择酒店"页选定的酒店 (全程只住这一家) */
  hotel?: SelectedHotel
}

/** 用户选定的酒店 */
export interface SelectedHotel {
  name: string
  address?: string
  location?: Location
  rating?: number
  type?: string
  poi_id?: string
  tier?: string
}

/** 选酒店页列表项 */
export interface HotelItem {
  poi_id: string
  name: string
  address: string
  type: string
  rating?: number
  location?: Location
}

export interface HotelListResponse {
  success: boolean
  message: string
  data: HotelItem[]
  total: number
  tier: string
  price_range: number[]
  no_location: number
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan
}

