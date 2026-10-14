#!/usr/bin/env bash
# ============================================================
# 密钥轮换脚本（生产服务器使用）
# 用法：
#   bash scripts/rotate_secrets.sh              # 轮换 JWT_SECRET
#   bash scripts/rotate_secrets.sh --db-password # 轮换 PostgreSQL 密码（需同步更新数据库）
# ============================================================
set -euo pipefail

# 服务器密钥文件（已移出项目目录，仅 root 可读）
ENV_FILE="${ENV_FILE:-/etc/blog-agent/backend.env}"
PROJECT_DIR="${PROJECT_DIR:-/root/myspace/Blog_generate_agent}"
MODE="${1:-jwt}"

if [ ! -f "$ENV_FILE" ]; then
  echo "[错误] 密钥文件不存在: $ENV_FILE"
  echo "请检查路径，或设置 ENV_FILE 环境变量"
  exit 1
fi

# 确保权限正确
chmod 600 "$ENV_FILE"

rotate_jwt() {
  local new_secret
  new_secret=$(openssl rand -hex 32)
  if grep -q '^jwt_secret=' "$ENV_FILE"; then
    sed -i "s|^jwt_secret=.*|jwt_secret=${new_secret}|" "$ENV_FILE"
  else
    echo "jwt_secret=${new_secret}" >> "$ENV_FILE"
  fi
  echo "[✓] JWT_SECRET 已轮换: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "    （新值已写入 $ENV_FILE，长度为 ${#new_secret} 字符）"
}

rotate_db_password() {
  local new_pwd
  new_pwd=$(openssl rand -hex 16)
  # 1. 更新 .env 文件
  if grep -q '^POSTGRES_PASSWORD=' "$ENV_FILE"; then
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${new_pwd}|" "$ENV_FILE"
  else
    echo "POSTGRES_PASSWORD=${new_pwd}" >> "$ENV_FILE"
  fi
  # 2. 同步根目录 .env（compose 顶层变量）
  if grep -q '^POSTGRES_PASSWORD=' "$PROJECT_DIR/.env"; then
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${new_pwd}|" "$PROJECT_DIR/.env"
  fi
  # 3. 更新数据库中的密码
  echo "[!] 正在执行 ALTER USER 更新数据库密码..."
  docker exec blog-agent-postgres psql -U "${POSTGRES_USER:-blog}" -d "${POSTGRES_DB:-blog_agent}" \
    -c "ALTER USER ${POSTGRES_USER:-blog} WITH PASSWORD '${new_pwd}';"
  echo "[✓] 数据库密码已轮换: $(date '+%Y-%m-%d %H:%M:%S')"
}

restart_backend() {
  echo "[!] 正在重启 backend 使新密钥生效..."
  cd "$PROJECT_DIR"
  docker compose up -d backend
  echo "[✓] backend 已重建（env_file 经 symlink 指向 $ENV_FILE）"
}

case "$MODE" in
  jwt|--jwt)
    rotate_jwt
    restart_backend
    echo
    echo "⚠️  注意：JWT 密钥轮换后，所有已登录用户的 token 立即失效，需要重新登录。"
    ;;
  db-password|--db-password)
    rotate_db_password
    restart_backend
    echo
    echo "⚠️  注意：backend 与 postgres 均已重建后，请验证登录与数据库连接。"
    ;;
  *)
    echo "用法: bash scripts/rotate_secrets.sh [jwt | db-password]"
    exit 1
    ;;
esac
