## 1. 媒体元数据提取模块

- [x] 1.1 新建 `app/services/media_metadata.py`，定义 `PhotoMetadata`、`VideoMetadata` dataclass 与格式化辅助函数（时间格式转换、光圈 `f/X`、快门 `1/Ns` 或 `Ns`、`ISO N`、分辨率 `W×H`、帧率 `N.Nfps`），并验证仅显示有值字段
- [x] 1.2 实现 `extract_photo_metadata(path)`：用 Pillow `Image.open().getexif()` 按 tag ID 提取 DateTimeOriginal(0x9003)、FNumber(0x829D)、ExposureTime(0x829A)、ISOSpeedRatings(0x8827)，异常或无 EXIF 返回 None
- [x] 1.3 实现 `extract_video_metadata(path)`：用 pymediainfo `MediaInfo.parse(path)` 从 `video_tracks[0]` 提取 width/height（int）与 frame_rate（str 转 float），异常返回 None
- [x] 1.4 实现 `extract_media_metadata(path, msgtype)` 整合入口：picture 走照片提取、video 走视频提取、其余返回 None；返回格式化后的摘要行字符串或 None

## 2. 消息处理器集成

- [x] 2.1 给 `_ImageProcessResult` 增加 `metadata: Optional[str] = None` 字段
- [x] 2.2 在 `_process_one_image` 的 archive 阶段（`save_file` 成功后）调用 `extract_media_metadata(saved_path, msgtype)`，将结果写入 `_ImageProcessResult.metadata`
- [x] 2.3 修改 `handle()` 单媒体回复拼接：保存成功时若 `result.metadata` 非空，在文件名后追加换行与元数据行
- [x] 2.4 修改 `_handle_rich_text()` 多图汇总回复：对每张保存成功的图片，在其文件名行后追加各自的元数据行（非空时）

## 3. 依赖与 Docker

- [x] 3.1 在 `pyproject.toml` 的 `dependencies` 中显式声明 `pillow>=12.0.0` 与 `pymediainfo>=6.0.0`，运行 `uv lock` 更新锁文件并验证 `uv sync` 成功
- [x] 3.2 修改 `Dockerfile`，在 `uv sync` 之后增加 `apt-get install -y --no-install-recommends libmediainfo0v5` 并清理 apt 缓存
- [x] 3.3 验证 `docker build` 成功且容器内 pymediainfo 可正常解析视频元数据

## 4. 测试

- [x] 4.1 编写 `tests/test_media_metadata.py` 图片单元测试：用 Pillow 生成带 EXIF 的 JPEG fixture，验证 4 字段解析与格式化；另测无 EXIF 图片返回 None
- [x] 4.2 编写视频单元测试：mock `pymediainfo.MediaInfo.parse` 返回固定 video track 对象，验证分辨率与帧率解析与格式化；另测解析失败返回 None
- [x] 4.3 更新 `tests/test_media_file_handler.py`：mock `extract_media_metadata`，验证单媒体与多图 richText 的回复拼接逻辑（有/无元数据两种情况）
- [x] 4.4 运行 `uv run pytest` 确认全部 general 测试通过

## 5. 验证

- [x] 5.1 运行 `openspec validate --changes media-metadata-reply --strict` 确认规范校验通过
- [x] 5.2 运行 `uv run python -m app.main` 启动应用，发送一张带 EXIF 的照片与一个视频，确认回复包含元数据摘要行

## 6. 真机验证修正（2026-10-03）

- [x] 6.1 在 `tests/fixtures/` 移入三份真实样本（`sample_nikon_z63.JPG`、`sample_honor_ptp_an00_original.png`、`sample_honor_ptp_an00_thumbnail.png`），并删除根目录原文件
- [x] 6.2 修复 `extract_photo_metadata`：通过 `exif.get_ifd(0x8769)` 读取 Exif 子 IFD 的 DateTimeOriginal/FNumber/ExposureTime；ISO 按 0x8827 → 0x8833 → 0x8832 回退；时间字符串 strip 尾部空白与 NUL
- [x] 6.3 修复日志体系：`media_metadata.py` 的 logger 改为 `file-bridge.media`；成功提取、无 EXIF、无可用字段三个路径均补 DEBUG 日志（异常日志沿用现有文案）
- [x] 6.4 重建 `tests/test_media_metadata.py` 图片用例：三份真实样本的行为断言（Nikon 四字段、HONOR 原图三字段+0x8833 ISO、缩略图返回 None）；程序化 fixture 改为写入 `get_ifd(0x8769)` 子 IFD，保留格式化边界用例
- [x] 6.5 运行 `uv run pytest` 全量通过，并对 `output/2026-10-03/` 下钉钉实拍照片手工验证光圈/快门/ISO 提取结果与 `LOG_LEVEL=DEBUG` 日志输出
- [x] 6.6 重新运行 `openspec validate --changes media-metadata-reply --strict` 通过
