import BalanceView from '../views/BalanceView.vue'
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
    path: '/balance/:roomId?',
    name: 'BalanceView',
    component: BalanceView,
  },
  {
    path: '/',
    redirect: '/danmaku/default',
  },
]

export default routes
