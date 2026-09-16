<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    class="svg-icon"
  >
    <!-- 写文章 -->
    <template v-if="name === 'edit'">
      <path d="M12 20h9" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 标题 -->
    <template v-else-if="name === 'title'">
      <path d="M4 7V5h16v2M9 5v14M15 5v14M7 19h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 大纲/列表 -->
    <template v-else-if="name === 'outline'">
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 写作/钢笔 -->
    <template v-else-if="name === 'pen'">
      <path d="M12 19l7-7 3 3-7 7-3-3z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
      <path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
      <path d="M2 2l7.586 7.586" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <circle cx="11" cy="11" r="2" stroke="currentColor" stroke-width="2"/>
    </template>
    <!-- 审稿/检查 -->
    <template v-else-if="name === 'review'">
      <path d="M9 11l3 3L22 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 配图/图片 -->
    <template v-else-if="name === 'image'">
      <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" stroke-width="2"/>
      <circle cx="8.5" cy="8.5" r="1.5" stroke="currentColor" stroke-width="2"/>
      <path d="M21 15l-5-5L5 21" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 格式化/排版 -->
    <template v-else-if="name === 'format'">
      <path d="M4 7V4h16v3M9 20h6M12 4v16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 搜索/调研 -->
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="8" stroke="currentColor" stroke-width="2"/>
      <path d="M21 21l-4.35-4.35" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 发送 -->
    <template v-else-if="name === 'send'">
      <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 刷新 -->
    <template v-else-if="name === 'refresh'">
      <path d="M23 4v6h-6M1 20v-6h6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 返回 -->
    <template v-else-if="name === 'back'">
      <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 复制 -->
    <template v-else-if="name === 'copy'">
      <rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="2"/>
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 时钟 -->
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>
      <path d="M12 6v6l4 2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 字数/文档 -->
    <template v-else-if="name === 'document'">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 加号 -->
    <template v-else-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 对勾 -->
    <template v-else-if="name === 'check'">
      <path d="M20 6L9 17l-5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 魔法棒/AI -->
    <template v-else-if="name === 'magic'">
      <path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8L19 13M15 9h0M17.8 6.2L19 5M3 21l9-9M12.2 6.2L11 5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 火花/创意 -->
    <template v-else-if="name === 'spark'">
      <path d="M12 2l2.4 7.4H22l-6 4.4 2.3 7.2-6.3-4.6-6.3 4.6L8 13.8 2 9.4h7.6z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
    </template>
    <!-- 加载/旋转 -->
    <template v-else-if="name === 'loading'">
      <path d="M21 12a9 9 0 11-6.219-8.56" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 向上箭头 -->
    <template v-else-if="name === 'up'">
      <path d="M18 15l-6-6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </template>
    <!-- 向下箭头 -->
    <template v-else-if="name === 'down'">
      <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </template>
    <!-- 字数/文本行数 -->
    <template v-else-if="name === 'wordcount'">
      <path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 水平/层级 -->
    <template v-else-if="name === 'level'">
      <path d="M4 20h6M4 14h10M4 8h14M4 4h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      <path d="M18 16l3-3-3-3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 太阳（亮色主题） -->
    <template v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="2"/>
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 月亮（暗色主题） -->
    <template v-else-if="name === 'moon'">
      <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
    </template>
    <!-- 菜单（汉堡） -->
    <template v-else-if="name === 'menu'">
      <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 用户 -->
    <template v-else-if="name === 'user'">
      <circle cx="12" cy="8" r="4" stroke="currentColor" stroke-width="2"/>
      <path d="M4 21c0-4 3.6-6 8-6s8 2 8 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </template>
    <!-- 退出登录 -->
    <template v-else-if="name === 'logout'">
      <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 下载 -->
    <template v-else-if="name === 'download'">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 收藏/星标 -->
    <template v-else-if="name === 'star'">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
    </template>
    <!-- 点赞 -->
    <template v-else-if="name === 'like'">
      <path d="M7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3m7-7l-2-2a3.5 3.5 0 00-5 5l4 5v6a2 2 0 002 2h6a2 2 0 002-1.5l2.5-8a2 2 0 00-2-2.5H14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </template>
    <!-- 默认：圆点 -->
    <template v-else>
      <circle cx="12" cy="12" r="4" fill="currentColor"/>
    </template>
  </svg>
</template>

<script setup>
defineProps({
  name: {
    type: String,
    required: true
  },
  size: {
    type: [Number, String],
    default: 20
  }
})
</script>

<style scoped>
.svg-icon {
  display: inline-block;
  vertical-align: middle;
  flex-shrink: 0;
}
</style>
