import { createRouter, createWebHistory } from 'vue-router'

const routes = [
    { path: '/', redirect: '/e.moevm.statistics/auth'},
    { path: '/start', redirect: '/e.moevm.statistics/auth'},
    { path: '/e.moevm.statistics/auth', name: 'Authorization', component: () => import('./components/Pages/AuthorizationPage.vue')},
    { path: '/e.moevm.statistics/statistics', name: 'Statistics', component: () => import('./components/Pages/StatisticsPage.vue')},
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

export default router