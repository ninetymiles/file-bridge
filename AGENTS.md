## 技术栈

- 语言环境: Python + venv
- 包管理器: uv
- 开发框架: DingTalkStreamSDK / FastAPI
- 测试框架: pytest

## 项目结构

- app/           - 应用主包
  - main.py       - 入口：配置解析与依赖装配
  - core/         - 生命周期与运行时编排（BotService）
  - handlers/     - 钉钉消息回调处理链（PipelineHandler 及各消息处理器）
  - services/     - 外部系统网关：文件下载、SQLite 元数据存储、生命周期通知
  - utils/        - 无状态工具函数（文件命名清洗与落盘）
- script/       - 离线执行脚本
- tests/        - 单元测试
- third-party/  - 第三方工程源码，仅作参考，不参与工程依赖和业务逻辑
- docs/         - 面向开发者和维护人员的说明，指南和手册
- openspec/     - 面向AI的SDD规范

## 项目规范

所有开发工作必须遵循以下规范文档，如果无法读取部分规范文档，请明确告知用户，不要自行假设规范内容:

- 需求规范: openspec/specs/*/spec.md
- 架构设计: openspec/specs/*/design.md

## 关键约定

- 代码风格遵循 PEP 8 官方代码风格指南，函数名、变量名、方法名和模块名使用lower_snake_case，类名使用CamelCase，常量使用UPPER_SNAKE_CASE命名。
- docs/ 和 openspec/ 目录下的文档使用中文书写；代码注释（包括 docstring）使用英文。

## 常用命令

- uv run uvicorn main:app   # 启动开发服务器，端口8000
- uv run pytest             # 运行单元测试
