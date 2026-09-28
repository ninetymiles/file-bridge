# Dingding 群聊机器人文件传输后端

### 背景介绍

公司群晖相册不对公网暴露，不提供公网访问，但是公司成员需要方便的往相册里传照片。

传统的VPN或者ZeroTrust方式需要在终端设备上安装额外的程序或者额外的连接步骤，使用并不方便，不能随手使用。

### 技术方案

因为相册的用户都是公司成员，都有企业即时通讯工具，比如钉钉企业群或者微信群，最省事的方式是在公司群里接入机器人，向机器人发送照片直接点到点传输到内网群晖。

群晖有Container套件，可以部署DockerImage，钉钉企业群机器人支持Stream模式API，可以使用WebSocket长连接接受数据推送，不需要服务器提供公网IP和域名访问，非常适合用来做单向的文件保存通道。

### 平台投递限制

钉钉平台对机器人回调消息的投递范围有限制：

| 场景 | 可接收消息类型 | 说明 |
|------|---------------|------|
| 单聊 | text、picture、video、file、richText | 全部支持 |
| 群聊 | text、richText（仅图片段） | 必须 @ 机器人；文件、视频、语音平台不投递 |

- 群聊中发送文件、视频、语音时，平台不会向机器人投递回调，请通过单聊发送。
- 群聊图片以 `richText` 消息的图片段形式投递，支持单张或多张。
- 群聊 `text` 消息中 `@机器人名` 由平台自动剥离，机器人收到的是去除 @ 后的文本。

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

### 附录

- [DingTalk](https://open.dingtalk.com/document/resourcedownload/Introduction-to-stream-mode)
- [DingTalkSDK](https://github.com/open-dingtalk/dingtalk-stream-sdk-python)
