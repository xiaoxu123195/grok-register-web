# Docker 部署

用容器把服务跑成后台常驻进程，解决「直接 `python app.py` 占着前台、SSH 一断就停」的问题。

镜像内已经准备好：

- Python 3.12 + `requirements.txt`
- Chromium（浏览器注册后端）
- Xvfb 虚拟显示（headful Chrome 的验证基线，等价于 `scripts/run_with_xvfb.sh`）
- Camoufox 本地 Turnstile Solver 依赖，并在构建期预下载浏览器（可用 `WITH_SOLVER=0` 跳过）

---

## 1. 前置条件

- Docker Engine 20.10+ 与 Docker Compose v2（`docker compose version` 能输出版本号）
- 磁盘约 3GB（含 Chromium + Camoufox）
- 构建期需要能访问 PyPI、Debian 源和 GitHub Releases（Camoufox 从 GitHub 下载）

## 2. 启动

```bash
git clone https://github.com/HSJ-BanFan/grok-register-web.git
cd grok-register-web

# 数据目录必须先由当前用户创建，否则 Docker 会建成 root 属主导致容器内写不了
mkdir -p data

cp .env.example .env        # 可选：改端口 / 时区 / SECRET_KEY

docker compose up -d --build
```

访问 `http://<服务器IP>:5000`。

常用命令：

```bash
docker compose logs -f          # 实时日志（等同原来前台看到的输出）
docker compose ps               # 状态 + 健康检查
docker compose restart          # 重启
docker compose down             # 停止并删除容器（data/ 保留在宿主机）
docker compose up -d --build    # 拉取新代码后重新构建
```

`restart: unless-stopped` 已配置，服务器重启后容器会自动拉起。

## 3. 数据与持久化

| 宿主机 | 容器内 | 内容 |
|--------|--------|------|
| `./data` | `/app/data` | SQLite 数据库、导出文件、`diagnostics/` 诊断 |

容器以非 root 用户 `app`（uid 1000）运行。若日志出现 `/app/data is not writable`：

```bash
sudo chown -R 1000:1000 ./data
docker compose restart
```

开启 CPA 热载时，还要在 `docker-compose.yml` 里放开 `/cpa/auths` 挂载，并让「设置」页里的路径与容器内路径一致。

## 4. 环境变量

`.env`（compose 变量）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `GROK_REGISTER_PORT` | `5000` | 宿主机映射端口 |
| `GROK_REGISTER_BIND` | `0.0.0.0` | 端口发布到哪个网卡，公网机器建议 `127.0.0.1` |
| `GROK_REGISTER_SECRET_KEY` | 空 | 固定 Flask session 密钥，不设则每次启动随机 |
| `TZ` | `Asia/Shanghai` | 容器时区，影响日志与时间戳 |
| `WITH_SOLVER` | `1` | 构建时是否安装 Camoufox Solver |

容器内已固定：

| 变量 | 值 | 说明 |
|------|----|------|
| `GROK_REGISTER_BROWSER_PATH` | `/usr/bin/chromium` | 容器内 Chromium 路径 |
| `GROK_REGISTER_BROWSER_HEADLESS` | `false` | 配合 Xvfb 跑 headful，不要硬开无头 |
| `DISPLAY` | `:99` | 由 entrypoint 拉起的 Xvfb |

`GROK_REGISTER_BACKEND` / `GROK_REGISTER_CONCURRENCY` 在 compose 里默认注释掉了：**一旦设置就会覆盖「设置」页的选项**，UI 上改了也不生效。想在 UI 里控制就保持注释。完整变量表见 [CONFIGURATION.md](CONFIGURATION.md)。

## 5. 网络

- **访问宿主机上的 grok2api / CPA / 代理**：用 `host.docker.internal`（compose 已配 `host-gateway`），**不要**填容器自己的 `127.0.0.1`。
- **访问另一个容器**：把两者放进同一个 compose 网络，直接用服务名。
- 代理设置同理，容器内 `127.0.0.1:7890` 指的是容器自己，不是宿主机。

## 6. 安全

**这个服务没有任何登录认证**，任何能访问该端口的人都能看到 SSO Token 和账号密码。默认 `0.0.0.0` 发布只适合内网或有防火墙的机器。放公网时二选一：

```yaml
# docker-compose.yml：只监听回环
ports:
  - "127.0.0.1:5000:5000"
```

```bash
# 本机通过 SSH 隧道访问
ssh -N -L 5000:127.0.0.1:5000 user@server
# 然后浏览器打开 http://localhost:5000
```

或者前置 Nginx/Caddy，配 HTTPS + Basic Auth。**用 HTTPS 还有个额外好处**：浏览器只在安全上下文（HTTPS 或 localhost）下开放原生剪切板 API，走 HTTPS 时复制按钮用的是原生路径而不是兼容回退。

## 7. 常见问题

**构建卡在 `camoufox fetch`**  
从 GitHub Releases 下载约 100MB。网络不通时构建不会失败（只打 WARNING），会在首次启动求解器时重试。想完全跳过：`WITH_SOLVER=0 docker compose build`。

**日志里 `Headful Chrome requires DISPLAY`**  
Xvfb 没起来。`docker compose logs` 看 entrypoint 的报错，确认没有把 `GROK_REGISTER_BROWSER_HEADLESS` 改成 `true` 之外的奇怪值。

**Chromium 启动即崩 / 页面白屏**  
`/dev/shm` 太小。compose 已设 `shm_size: 1gb`，如果是自己 `docker run`，加 `--shm-size=1g`。

**`docker compose ps` 显示 unhealthy**  
健康检查打的是容器内 `http://127.0.0.1:5000/`。若改了 `GROK_REGISTER_PORT`，那是宿主机端口，容器内仍是 5000，不影响健康检查。真 unhealthy 就看日志。

**改了代码不生效**  
镜像里是构建时的代码副本，需要 `docker compose up -d --build`。

**时间戳差 8 小时**  
`.env` 里设 `TZ=Asia/Shanghai` 后 `docker compose up -d` 重建容器。

其余注册 / 交付层面的故障排查见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
