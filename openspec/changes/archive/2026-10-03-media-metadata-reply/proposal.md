## Why

当前机器人收到照片或视频后，回复仅包含保存后的文件名，缺乏对媒体内容本身的描述。用户希望在回复中附带拍摄元数据（照片的拍照时间/光圈/快门/ISO，视频的分辨率/帧率），以便快速了解媒体的基本信息，无需手动打开文件查看。

## What Changes

- 新增媒体元数据提取能力：对落盘后的照片（JPEG/PNG 等）解析 EXIF Layer-1 字段（拍照时间、光圈、快门速度、ISO），对视频通过 pymediainfo 解析容器元数据（分辨率、帧率）。
- 媒体保存成功的回复中，在文件名下方追加一行元数据摘要；无可用元数据时不追加该行，保持原有回复不变。
- 元数据仅用于回复展示，不写入 SQLite 元数据表。
- 显式声明 `pillow` 与 `pymediainfo` 为项目直接依赖（Pillow 此前为 fastembed 的传递依赖，现显式声明以确保未来移除 fastembed 后图片 EXIF 解析能力不受影响）。
- Docker 镜像安装 `libmediainfo0v5`（pymediainfo 的系统依赖，仅共享库，比 ffmpeg 轻量）以支持视频元数据解析。

## Capabilities

### New Capabilities
- `media-metadata`: 定义从照片（EXIF）和视频（pymediainfo 容器元数据）中提取基础元数据并格式化为回复摘要行的行为，包括字段范围、格式化规则与失败降级策略。

### Modified Capabilities
- `message-pipeline`: 媒体保存成功的回复格式变更——在文件名后追加元数据摘要行（当元数据可用时）。

## Impact

- 代码：新增 `app/services/media_metadata.py`（提取与格式化）；修改 `app/handlers/message.py` 的 `_ImageProcessResult` 与回复拼接逻辑。
- 依赖：`pyproject.toml` 显式声明 `pillow>=12.0.0` 与 `pymediainfo>=6.0.0`；系统依赖 `libmediainfo0v5`（Dockerfile 新增安装）。
- 构建：Dockerfile 增加 `apt-get install libmediainfo0v5`，镜像体积增量远小于 ffmpeg。
- 数据库：无变更（元数据不入库）。
