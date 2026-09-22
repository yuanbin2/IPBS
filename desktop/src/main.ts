import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { installApiClient } from './api/client'
import './style.css'

// Install API client
installApiClient()

// Create Vue app
const app = createApp(App)

// Use plugins
app.use(createPinia())
app.use(router)
app.use(ElementPlus)

// Mount app
app.mount('#app')
