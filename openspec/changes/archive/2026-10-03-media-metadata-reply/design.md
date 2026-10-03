## Context

当前 `MediaFileHandler` 在文件落盘后回复仅包含保存文件名。Pillow 与 pymediainfo 将作为项目直接依赖显式声明：Pillow 用于图片 EXIF 解析（此前为 fastembed 传递依赖）；pymediainfo 用于视频容器元数据解析，其系统依赖为 `libmediainfo0v5`（仅共享库，比 ffmpeg 轻量得多）。当前 Docker 镜像（`python:3.14-slim`）未包含该库。元数据不入库，仅用于回复展示。

## Goals / Non-Goals

**Goals:**
- 对落盘后的照片提取 EXIF Layer-1 字段（拍照时间、光圈、快门、ISO）并格式化，兼容标准 EXIF 2.3（0x8827）与 EXIF 2.31（0x8833/0x8832）两种 ISO 标签
- 对落盘后的视频通过 pymediainfo 提取分辨率与帧率并格式化
- 在保存成功的回复中追加元数据摘要行，无可用元数据时保持原回复不变
- 解析失败时 fail-soft，不中断保存与回复流程
- 元数据提取过程在 DEBUG 级别可观测（成功摘要 / 无字段原因 / 异常原因）

**Non-Goals:**
- 不解析 EXIF 扩展字段（GPS、MakerNote、白平衡等）
- 不提取视频码率、时长（钉钉卡片已展示）
- 不将元数据写入 SQLite
- 不修改现有文件名生成与去重逻辑

## Decisions

### 1. 新建独立模块 `app/services/media_metadata.py`

将元数据提取与格式化逻辑集中在单文件中，对外暴露 `extract_media_metadata(path, msgtype) -> Optional[str]` 一个入口。`MediaFileHandler` 只需调用此入口并将结果拼入回复，保持单一职责。

**替代方案**：直接在 `message.py` 内联解析逻辑。否决理由：解析逻辑与消息处理耦合，且图片/视频解析差异大，内联会使 handler 膨胀。

### 2. 图片使用 Pillow 的 `getexif()`，并读取 Exif 子 IFD

Pillow 作为项目直接依赖显式声明于 `pyproject.toml`（此前仅作为 fastembed 的传递依赖隐式存在，考虑到未来可能移除 fastembed 改用 onnxruntime，必须显式声明以保证核心能力不丢失）。

**真机验证修正（2026-10-03）**：初版直接在 `Image.open(path).getexif()` 返回的顶层 IFD0 上按 tag ID 取值，对真实照片全部返回 None。原因是相机把拍摄参数写在 Exif 子 IFD（由 IFD0 的 ExifTag 指针 `0x8769` 指向），IFD0 仅含 Make/Model/Orientation。必须通过 `exif.get_ifd(0x8769)` 取得子 IFD 后读取：
- `0x9003` DateTimeOriginal
- `0x829D` FNumber（`IFDRational` 或 tuple rational）
- `0x829A` ExposureTime（同上）

**ISO 回退链（跨 EXIF 版本差异）**。实测不同设备 ISO 标签位置不同：
- Nikon 等标准 EXIF 2.3 设备写 `ISOSpeedRatings`（`0x8827`）
- HONOR PTP-AN00（EXIF 2.31）不写 0x8827，改为 `SensitivityType=3` + `ISOSpeed`（`0x8833`）
- 部分设备写 `RecommendedExposureIndex`（`0x8832`）

按 `0x8827 → 0x8833 → 0x8832` 顺序取第一个存在的整数标签，不以 `SensitivityType` 作为硬门控（厂商写入不一致）。

时间字符串可能带 NUL 结尾（如 Nikon IFD0 的 DateTime `'2026:09:20 08:49:30\x00'`），格式化前 strip 尾部空白与 NUL。

Pillow 按文件内容（magic bytes）检测格式，不受扩展名影响（钉钉图片存为 `.png` 但实为 JPEG）。

**已确认的上游数据限制**：钉钉投递的 HONOR 照片（含原图）全部不含 DateTimeOriginal/DateTime/XMP 时间戳，GPS 也被剥离。拍照时间字段对钉钉来源照片预期长期缺失，"只显示有值字段"的规则保证回复不出现空占位；文件名时间为接收时间，不用于冒充拍摄时间。

**备选方案：exifread**。当未来移除 fastembed 且不再需要 Pillow 的图像处理能力时，可改用纯 Python、零依赖的 `exifread` 库替代 Pillow 进行 EXIF 提取。exifread 通过 `exifread.process_file(open(path, 'rb'))` 返回 tag 字典，键名为 `'EXIF DateTimeOriginal'`、`'EXIF FNumber'` 等，用 `details=False` 可跳过 MakerNote 与缩略图以加速。此方案仅作为未来轻量化部署的备选，当前不实现。

### 3. 视频使用 pymediainfo

pymediainfo 是 MediaInfo 库的 Python 绑定，通过 `MediaInfo.parse(path)` 返回包含多个轨道的对象。从 `media_info.video_tracks[0]` 读取：
- `width`、`height`：分辨率（int）
- `frame_rate`：帧率（str，需转 float，如 `"30.204"`）

pymediainfo 通过 ctypes 直接调用 `libmediainfo` 共享库，无需 subprocess，解析效率高于 fork 进程。系统依赖仅为 `libmediainfo0v5`（Debian/Ubuntu 包名，约 3MB），远小于 ffmpeg 全家桶。

**备选方案：ffprobe（subprocess）**。若未来 pymediainfo 或 libmediainfo 出现兼容性问题，可回退到通过 `subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path])` 解析，从视频流的 `width`/`height`/`avg_frame_rate` 提取字段。此方案需安装 ffmpeg（约 80MB），过于重型，仅作为备选登记，当前不实现。

### 4. Dockerfile 安装 libmediainfo0v5

在 `uv sync` 之后增加：
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*
```
`libmediainfo0v5` 是 pymediainfo 运行所需的共享库，约 3MB，远小于 ffmpeg。

### 5. 失败降级策略

`extract_media_metadata` 内部对图片 EXIF 解析（Pillow）与视频容器解析（pymediainfo）均包裹 try/except，任何异常返回 `None`。`MediaFileHandler` 仅在返回非 None 时拼接元数据行。解析失败不影响文件已保存的事实。

### 6. `_ImageProcessResult` 扩展

在 dataclass 中增加 `metadata: Optional[str] = None` 字段。`handle()` 与 `_handle_rich_text()` 在拼接回复时，若 `result.metadata` 非空，则在文件名行后追加 `\n{metadata}`。

### 7. 元数据提取的 DEBUG 可观测性

真机验证时"保存成功但元数据静默为 None"无法排查，原因有二：成功路径没有任何日志；模块 logger 误用 `logging.getLogger(__name__)`（即 `app.services.media_metadata`），其 effective level 跟随 root（INFO），`LOG_LEVEL=DEBUG` 只作用于 `file-bridge` logger，DEBUG 帧在 logger 门即被丢弃。

修正：
- 模块 logger 改为 `logging.getLogger("file-bridge.media")`，与 `file-bridge.downloader`、`file-bridge.runner` 等子 logger 约定一致，随 `LOG_LEVEL=DEBUG` 生效。
- 在提取函数内补 DEBUG 日志（单一记录点，handler 不重复记录）：
  - 成功：记录最终摘要行（如 `Photo metadata: f/2.4 1/33s ISO 200`）
  - 无 EXIF / 无可用字段：记录原因（`no EXIF segment` / `no usable fields`）
  - 解析异常：已有 debug 日志保留，logger 名随之修正
- 诊断日志不作为测试断言对象（遵循项目约定）。

### 8. 测试夹具使用真实相机样本

初版单测用 Pillow 把 EXIF 标签写入顶层 IFD0 构造 fixture——该位置非标准，Pillow 可往返但真实相机从不如此写入，导致测试全绿而真机全部失败（fixture 失真）。

改为在 `tests/fixtures/` 存放用户提供的三份真实文件，直接以行为契约驱动：
- `sample_nikon_z63.JPG`：标准 EXIF 2.3，子 IFD 含完整时间/光圈/快门，ISO 在 0x8827 → 断言 4 字段齐全且时间为 `2026-09-12 14:58:16`
- `sample_honor_ptp_an00_original.png`：JPEG 内容，子 IFD 含光圈/快门，ISO 在 0x8833，无任何时间标签 → 断言 `f/1.9 1/33s ISO 320`，不含时间
- `sample_honor_ptp_an00_thumbnail.png`：EXIF 被剥离的缩略图 → 断言返回 None

另保留程序化 fixture（写入 `get_ifd(0x8769)` 子 IFD 的标准结构）用于格式化边界用例（长快门、部分字段、缺失文件）。

## Risks / Trade-offs

- **[钉钉图片格式]** 钉钉 `picture` 消息实际投递 JPEG，但代码以 `.png` 扩展名落盘。Pillow 按内容检测格式不受影响；若后续有按扩展名处理的逻辑需注意此不一致。→ 本次不改动扩展名逻辑，保持现状。
- **[libmediainfo 缺失]** 开发环境若未安装 libmediainfo，pymediainfo 导入或解析会抛异常。→ `extract_video_metadata` 内 try/except 捕获异常并返回 None，不影响保存流程；测试通过 mock `MediaInfo.parse` 避免依赖真实 libmediainfo。
- **[EXIF 时区]** `DateTimeOriginal` 为相机本地时间，无时区信息。→ 按原值展示，不做时区转换。
- **[帧率精度]** pymediainfo 的 `frame_rate` 为字符串（如 `"30.204"`），转 float 后保留一位小数展示。→ 满足展示需求，不追求工程级精度。
