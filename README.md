# Dingding 群聊机器人文件传输后端

### 背景介绍

公司群晖相册不对公网暴露，不提供公网访问，但是公司成员需要方便的往相册里传照片。

传统的VPN或者ZeroTrust方式需要在终端设备上安装额外的程序或者额外的连接步骤，使用并不方便，不能随手使用。

### 技术方案

因为相册的用户都是公司成员，都有企业即时通讯工具，比如钉钉企业群或者微信群，最省事的方式是在公司群里接入机器人，向机器人发送照片直接点到点传输到内网群晖。

群晖有Container套件，可以部署DockerImage，钉钉企业群机器人支持Stream模式API，可以使用WebSocket长连接接受数据推送，不需要服务器提供公网IP和域名访问，非常适合用来做单向的文件保存通道。

### 启动应用

项目通过 FastAPI 提供 REST API 服务。

```shell
$ uv run uvicorn app.main:app
```

默认监听 127.0.0.1:8000，可通过参数 --host 0.0.0.0 --port 8000 或环境变量 UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000 指定监听地址和端口

### 测试接口

冒烟测试，服务器部署完成之后验证服务正常

```shell
$ uv run python -m tests.test_smoke # 打印测试报告
```

Pytest 单元测试

```shell
$ uv run pytest
$ uv run pytest -m smoke # 冒烟测试，不打印报告，只收集结果
```

### 打包发布

**快速开始**：

日常开发使用 `uv run` 直接运行，无需 Docker：
```shell
$ uv run uvicorn app.main:app --reload
```

本地验证打包，镜像名 'file-bridge:latest'

```shell
$ docker build --tag file-bridge .
```

发布版本时，推送 tag 触发自动构建：
```shell
$ git tag v1.2.3
$ git push origin v1.2.3
```

GitHub Actions 会自动构建多平台镜像并推送到 Docker Hub 仓库，镜像命名规则 'file-bridge:1.2.3'。

### 部署运行

生产环境使用 Docker 容器运行：

```shell
# 拉取镜像
$ docker pull <username>/file-bridge:1.2.3

# 启动容器（需要挂载存储目录）
$ docker run -d \
  --restart unless-stopped \
  --name file-bridge \
  -p 8000:8000 \
  -v /path/to/storage:/out \
  <username>/file-bridge:1.2.3
```

或使用 docker-compose：
```shell
$ docker compose up -d
```

docker-compose 配置默认不映射端口，如果需要映射端口，通过 docker-compose.override.yml 指定：
```yaml
services:
  api:
    ports:
      - "127.0.0.1:8000:8000"
```

### 附录

- [DingTalk](https://open.dingtalk.com/document/resourcedownload/Introduction-to-stream-mode)
- [DingTalkSDK](https://github.com/open-dingtalk/dingtalk-stream-sdk-python)
- [FastAPI](https://fastapi.tiangolo.com/)
