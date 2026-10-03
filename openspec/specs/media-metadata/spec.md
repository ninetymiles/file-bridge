# media-metadata Specification

## Purpose

定义从落盘后的照片（EXIF）与视频（容器元数据）中提取基础拍摄信息，并格式化为回复摘要行的行为，使发送者在不打开文件的情况下即可获知媒体的关键参数。

## Requirements

### Requirement: 照片 EXIF 基础元数据提取
系统 SHALL 在照片文件成功落盘后，解析其 EXIF 信息并提取以下字段：拍照时间（`DateTimeOriginal`，tag 0x9003）、光圈（`FNumber`，tag 0x829D）、快门速度（`ExposureTime`，tag 0x829A）、ISO 感光度。拍照时间、光圈、快门速度位于 Exif 子 IFD（由 IFD0 的 ExifTag 指针 0x8769 指向）中，系统 MUST 从该子 IFD 读取，不能仅查找顶层 IFD0。ISO 感光度 MUST 按以下顺序回退取值：`ISOSpeedRatings`（0x8827）→ `ISOSpeed`（0x8833）→ `RecommendedExposureIndex`（0x8832），取第一个存在的标签。解析 MUST 仅依赖 EXIF Layer-1 基础字段，不涉及 GPS、MakerNote 等扩展字段。

#### Scenario: 提取标准 EXIF 相机的完整元数据
- **WHEN** 一张由标准 EXIF 相机（如 Nikon Z6_3）拍摄的照片成功落盘，其 Exif 子 IFD 包含 DateTimeOriginal、FNumber、ExposureTime，ISOSpeedRatings(0x8827) 存在
- **THEN** 系统从子 IFD 提取到拍照时间、光圈、快门速度，并从 0x8827 提取 ISO，四个字段均可用

#### Scenario: 从 EXIF 2.31 新标签提取 ISO 且无拍照时间
- **WHEN** 一张照片（如 HONOR PTP-AN00 原图）的 Exif 子 IFD 包含 FNumber、ExposureTime 与 ISOSpeed(0x8833)，但不存在 ISOSpeedRatings(0x8827)，且任何位置均无拍照时间标签
- **THEN** 系统回退从 0x8833 提取 ISO，光圈与快门正常提取，拍照时间视为不可用且不显示

#### Scenario: 照片部分 EXIF 字段缺失
- **WHEN** 照片的 EXIF 中仅包含部分目标字段
- **THEN** 系统仅返回存在的字段，缺失字段视为不可用

#### Scenario: 缩略图 EXIF 被剥离
- **WHEN** 落盘的照片是经过传输通道处理的缩略图（如钉钉投递的缩略图），EXIF 中的厂商、型号、拍摄参数标签全部缺失
- **THEN** 系统返回无可用元数据，不产生任何元数据摘要行

#### Scenario: 照片无 EXIF 信息
- **WHEN** 落盘的照片文件不含 EXIF 数据（如截图、网络图片）
- **THEN** 系统返回无可用元数据，不产生任何元数据摘要行

### Requirement: 视频容器基础元数据提取
系统 SHALL 在视频文件成功落盘后，通过 pymediainfo 解析容器元数据并提取以下字段：分辨率（视频流的宽与高）、帧率（视频流的帧率）。解析 MUST 不涉及码率、时长等字段。

#### Scenario: 提取视频元数据
- **WHEN** 一个视频文件成功落盘且 pymediainfo 可正常解析
- **THEN** 系统提取到分辨率与帧率字段的原始值

#### Scenario: 视频解析失败
- **WHEN** 视频文件损坏或 pymediainfo 无法解析其容器结构
- **THEN** 系统返回无可用元数据，不产生任何元数据摘要行

### Requirement: 元数据摘要行格式化
系统 SHALL 将提取到的可用元数据格式化为单行文本附加在文件名回复之后，字段之间以两个空格分隔。格式化规则如下：
- 拍照时间：先去除原始字符串结尾的空白与 NUL 字符，再将 EXIF 原始格式 `YYYY:MM:DD HH:MM:SS` 转为 `YYYY-MM-DD HH:MM:SS`
- 光圈：格式化为 `f/<value>`（如 `f/2.8`）
- 快门速度：小于 1 秒时格式化为 `1/Ns`（如 `1/500s`），大于等于 1 秒时格式化为 `<N>s`
- ISO：格式化为 `ISO <value>`（如 `ISO 400`）
- 分辨率：格式化为 `<宽>x<高>`（如 `1920x1080`，分隔符为字母 x）
- 帧率：格式化为 `<value>fps`（保留一位小数，如 `29.8fps`）
- 仅显示有值的字段，无值字段 MUST 被跳过，不出现占位符或空标签

#### Scenario: 完整 EXIF 照片的格式化输出
- **WHEN** 照片包含拍照时间、光圈、快门、ISO 全部字段
- **THEN** 摘要行为 `2024-01-15 14:30:00  f/2.8  1/500s  ISO 400`

#### Scenario: 部分字段照片的格式化输出
- **WHEN** 照片仅包含拍照时间与 ISO，缺少光圈与快门
- **THEN** 摘要行为 `2024-01-15 14:30:00  ISO 400`（缺失字段被跳过）

#### Scenario: 视频元数据的格式化输出
- **WHEN** 视频分辨率为 544x960、帧率为 29.83fps
- **THEN** 摘要行为 `544x960  29.8fps`

### Requirement: 元数据提取失败降级
系统 SHALL 在元数据解析过程中遇到任何异常（文件无法打开、EXIF 结构损坏、pymediainfo 解析失败或返回非预期结构）时，返回无可用元数据而非抛出异常，确保文件保存与回复流程不被中断。

#### Scenario: EXIF 解析异常不中断保存流程
- **WHEN** 照片文件损坏导致 EXIF 解析抛出异常
- **THEN** 系统捕获异常并返回无可用元数据，文件保存成功的回复仅包含文件名，不附加元数据行

#### Scenario: 视频解析异常不中断保存流程
- **WHEN** libmediainfo 共享库缺失或 pymediainfo 解析抛出异常
- **THEN** 系统捕获异常并返回无可用元数据，文件保存成功的回复仅包含文件名，不附加元数据行
