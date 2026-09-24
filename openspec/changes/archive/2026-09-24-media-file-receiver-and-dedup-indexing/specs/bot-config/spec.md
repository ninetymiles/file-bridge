## ADDED Requirements

### Requirement: 文件输出目录配置
系统 SHALL 支持通过环境变量 `OUTPUT_DIR` 或命令行参数 `--output-dir` 配置接收文件的存储与索引根目录。

#### Scenario: 环境变量提供输出目录
- **WHEN** 环境变量中配置了 `OUTPUT_DIR=/path/to/files`
- **THEN** 系统使用该路径作为多媒体文件分目录归档及 `metadata.sqlite` 的根路径

#### Scenario: 命令行参数覆盖输出目录
- **WHEN** 命令行指定了 `--output-dir /custom/path`
- **THEN** 系统优先使用命令行参数指定的输出路径
