# observability Specification

## Purpose

应用运行期会输出日志用于人工排障（可通过 `LOG_LEVEL=DEBUG` 查看更详细信息）。日志是内部运维辅助手段，不属于系统对外接口契约：其具体格式、级别与字段由实现与运维需要决定，不作为测试断言对象，运行效果由人工线上验收。

## Requirements

无。
