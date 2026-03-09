# AI 角色定义

本文件夹包含 PPT Master 系统的核心 AI 角色定义文档。

> 📖 **完整工作流程和使用指南**：请参阅 [AGENTS.md](../AGENTS.md)

## 角色速查表

| 角色 | 文件 | 职责 | 触发条件 |
|------|------|------|----------|
| **策略师** | [Strategist.md](./Strategist.md) | 三阶段确认 + 设计规范 | 项目启动时（必须） |
| **模板设计师** | [Template_Designer.md](./Template_Designer.md) | 生成页面模板 | 使用 `/create-template` 工作流 |
| **图片生成师** | [Image_Generator.md](./Image_Generator.md) | AI 图片生成 | 图片方式含「C) AI 生成」 |
| **执行师** | [Executor.md](./Executor.md) | SVG 生成 + 演讲备注 | 生成 SVG 页面（必须） |
| **CRAP 优化师** | [Optimizer_CRAP.md](./Optimizer_CRAP.md) | 视觉质量优化 | 用户要求优化（可选） |

> ⚠️ **注意**：Executor 角色已统一为单个文件，根据设计规范中的风格类型自动适配。

## 支持的画布格式

- **演示文稿**: PPT 16:9 (1280×720)、PPT 4:3 (1024×768)
- **社交媒体**: 小红书 (1242×1660)、朋友圈 (1080×1080)、Story (1080×1920)
- **营销物料**: 公众号头图 (900×383)、横版/竖版海报

详见 [画布格式规范](../docs/canvas_formats.md)

## 相关文档

| 文档 | 说明 |
|------|------|
| [AGENTS.md](../AGENTS.md) | 完整工作流程、角色切换协议、技术约束 |
| [设计指南](../docs/design_guidelines.md) | 配色、字体、布局详细规范 |
| [工作流教程](../docs/workflow_tutorial.md) | 实战案例 |
| [快速参考](../docs/quick_reference.md) | 速查手册 |
