import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import App from './App.vue'
import Home from './views/Home.vue'
import HotelSelect from './views/HotelSelect.vue'
import Result from './views/Result.vue'
import History from './views/History.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'Home',
      component: Home
    },
    {
      // 首页填完基本信息后先来这里选酒店, 选定后再生成行程
      path: '/hotel',
      name: 'HotelSelect',
      component: HotelSelect
    },
    {
      path: '/result',
      name: 'Result',
      component: Result
    },
    {
      path: '/history',
      name: 'History',
      component: History
    }
  ]
})

const app = createApp(App)

app.use(router)
app.use(Antd)

app.mount('#app')

