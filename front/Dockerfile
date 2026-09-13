# ============================================================
# 生产镜像：多阶段构建
# 阶段1：Node 环境打包 Vue 源码 → dist/
# 阶段2：Nginx 托管静态文件 + 反向代理 /api、/images
# 本地开发请使用 Dockerfile.dev（vite 热更新）
# ============================================================

# ---------- 阶段1：构建 ----------
FROM node:20-alpine AS build

WORKDIR /app

# 复制依赖清单并安装（利用层缓存）
COPY package*.json ./
RUN npm install

# 复制源码并打包
COPY . .
RUN npm run build

# ---------- 阶段2：Nginx 托管 ----------
FROM nginx:alpine

# 静态产物
COPY --from=build /app/dist /usr/share/nginx/html

# 反向代理配置（/api、/images → backend）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
