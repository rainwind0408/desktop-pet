import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import HomeView from './views/HomeView.vue'
import SettingsView from './views/SettingsView.vue'

const routes = [
  { path: '/', component: HomeView },
  { path: '/settings', component: SettingsView }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

const app = createApp(App)
app.use(router)
app.use(ElementPlus)
app.mount('#app')