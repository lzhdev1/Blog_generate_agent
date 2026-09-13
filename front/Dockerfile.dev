FROM node:20-alpine

WORKDIR /app

# 复制 package.json 并安装依赖
COPY package*.json ./
RUN npm install

# 复制项目代码
COPY . .

# 暴露 Vite 开发服务器端口
EXPOSE 5173

# 启动开发服务器（host 0.0.0.0 允许容器外访问）
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
