import BalanceQuery from '../views/BalanceQuery.vue'
import ChatView from '../views/ChatView.vue'
import DanmakuView from '../views/DanmakuView.vue'

const routes = [
  {
    path: '/danmaku/:roomId?',
    name: 'DanmakuView',
    component: DanmakuView,
  },
  {
    path: '/danmaku/chat/:roomId?',
    name: 'ChatView',
    component: ChatView,
  },
  {
    path: '/balance',
    name: 'BalanceQuery',
    component: BalanceQuery,
  },
  {
    path: '/',
    redirect: '/danmaku/default',
  },
]

export default routes
