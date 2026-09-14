# 部署文档

> 最后更新：2026-09-14
> 生产地址：https://lzhshow.top

## 一、生产架构

```
用户浏览器
    │ HTTPS (443)
    ▼
外层服务器 Nginx（系统安装，/etc/nginx/conf.d/lzhshow.top.conf）
    │  HTTPS 终止 / 80→443 跳转 / gzip / 安全头
    │  反代 127.0.0.1:8080
    ▼
前端 prod 容器 blog-agent-frontend-prod（Nginx，监听 127.0.0.1:8080）
    │  静态托管（Vue 构建产物）/ Vue Router 回退
    │  /api、/images 反代
    ▼
后端容器 blog-agent-backend（uvicorn，expose 8000，不对外）
    │  SQLAlchemy
    ▼
PostgreSQL 容器 blog-agent-postgres（expose 5432，不对外）
```

端口策略：**仅 80/443 对外**；后端 8000、数据库 5432 均不暴露公网。

## 二、服务器信息

| 项 | 值 |
|---|---|
| 服务器 | 阿里云 ECS `123.57.252.221` |
| 系统 | Alibaba Cloud Linux 3 |
| 域名 | `lzhshow.top`（阿里云，DNS 云解析） |
| 证书 | `/etc/nginx/ssl/lzhshow.top.pem` / `.key`（免费 SSL） |
| 外层 Nginx 配置 | `/etc/nginx/conf.d/lzhshow.top.conf` |
| 项目目录 | `/opt/Blog_generate_agent` |
| 远程仓库 | `https://github.com/lzhdev1/Blog_generate_agent` |

## 三、首次部署

```bash
# 1. 安装 git / docker / docker compose 后拉代码
cd /opt
git clone https://github.com/lzhdev1/Blog_generate_agent.git

# 2. 配置环境变量（不入库）
cp backend/.env.example backend/.env   # 填入真实密钥
cp .env.example .env                   # 填入 POSTGRES_* 变量

# 3. 配置外层 Nginx（HTTPS 证书 + 反代 8080）
#    参考：/etc/nginx/conf.d/lzhshow.top.conf

# 4. 启动生产
cd Blog_generate_agent
docker compose --profile prod up -d --build
```

## 四、日常更新部署

```bash
cd /opt/Blog_generate_agent

# 1. 拉取最新代码（如遇图片冲突，先备份 backend/data/images 再拉）
git pull

# 2. 重新构建并启动（后端热更新自动生效，前端必须重建）
docker compose --profile prod up -d --build

# 只重启后端（后端代码改动未生效时）
docker compose restart backend

# 只重建前端
docker compose --profile prod up -d --build frontend-prod
```

> 注意：**不要**直接 `docker compose up -d`（会同时启动 dev 前端）。
> 必须带 `--profile prod`。

## 五、验证

```bash
# 容器状态
docker compose --profile prod ps

# 容器内 Nginx 配置
docker exec blog-agent-frontend-prod cat /etc/nginx/conf.d/default.conf | grep timeout

# 后端健康
curl -s http://127.0.0.1:8000/docs -o /dev/null -w "%{http_code}\n"

# 域名访问
curl -I https://lzhshow.top
```

## 六、日志查看

```bash
# 实时日志
docker compose --profile prod logs -f backend
docker compose --profile prod logs -f frontend-prod

# 外层 Nginx 日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## 七、注意事项

1. **两层 Nginx 都要配 600s 接口超时**：内层 `front/nginx.conf` 已配；
   外层 `lzhshow.top.conf` 的 `/` location 需加 `proxy_read_timeout 600s; proxy_send_timeout 600s;`
2. **图片不进 git**：`backend/data/images/` 已在 .gitignore；pull 冲突时先备份目录
3. **前端改码必须重建镜像**（构建产物打进镜像），后端改码热更新
4. **数据库备份待做**：当前无自动备份，建议 pg_dump + cron
5. **密钥管理待做**：当前 .env 明文，建议 Docker secrets / KMS
