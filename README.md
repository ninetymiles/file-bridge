# Dingding 群聊机器人文件传输后端

### 背景介绍

公司群晖相册不对公网暴露，不提供公网访问，但是公司成员需要方便的往相册里传照片。

传统的VPN或者ZeroTrust方式需要在终端设备上安装额外的程序或者额外的连接步骤，使用并不方便，不能随手使用。

### 技术方案

因为相册的用户都是公司成员，都有企业即时通讯工具，比如钉钉企业群或者微信群，最省事的方式是在公司群里接入机器人，向机器人发送照片直接点到点传输到内网群晖。

群晖有Container套件，可以部署DockerImage，钉钉企业群机器人支持Stream模式API，可以使用WebSocket长连接接受数据推送，不需要服务器提供公网IP和域名访问，非常适合用来做单向的文件保存通道。

### 创建机器人

- 登录[钉钉开发者平台](https://open-dev.dingtalk.com/)。
- 创建企业内部钉钉应用。
- 查看应用详情，从凭证与基础信息 获取 ClientID 和 ClientSecret。
- 启用机器人配置，消息接收模式选择 Stream 模式。
- 权限管理，开通互动卡片实例写权限。
- 版本管理与发布，新建版本，确认应用信息和机器人配置，发布到企业里。

### 启动应用

项目支持通过CLI命令行方式启动应用，默认会自动加载 .env 文件中的环境变量。

```shell
$ uv run python -m app.main
```

### 单元测试

```shell
$ uv run pytest
```

### 打包发布

本地验证打包，镜像名 'file-bridge:latest'

```shell
$ docker build --tag file-bridge .
```

或者通过 docker-compose 打包：

```shell
$ docker compose build
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
  -v /path/to/storage:/out \
  <username>/file-bridge:1.2.3
```

或使用 docker-compose 启动容器：
```shell
$ docker compose up -d
```

### 群晖配置

- 控制面板终端机和SNMP启用SSH (群晖 ContainerManager GUI 不支持 GitHub 仓库)
- SSH 使用群晖管理员账号登录
- 执行sudo docker pull ghcr.io/<user-name>/<repo-name>:<tag-name>
- 打开 ContainerManager 新增项目，使用 docker-compose 配置创建容器

### 附录

- [DingTalk](https://open.dingtalk.com/document/resourcedownload/Introduction-to-stream-mode)
- [DingTalkSDK](https://github.com/open-dingtalk/dingtalk-stream-sdk-python)
