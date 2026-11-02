# 第三方依赖与分发准备

项目自有代码采用根目录 MIT 许可，不改变任何第三方组件许可。

| 组件 | 用途 | 许可来源 |
|---|---|---|
| Python / SQLite | 运行时与存储 | 随 Python 分发的 LICENSE 及 sqlite.org |
| PySide6 / Shiboken / Qt | 桌面窗口 | [Qt for Python 许可](https://doc.qt.io/qtforpython-6/licenses.html) |
| FastAPI / Uvicorn / Starlette | HTTP 服务 | 各安装发行包的 dist-info/licenses |
| httpx / httpcore | HTTP 客户端 | 各安装发行包的 dist-info/licenses |
| Pydantic / platformdirs / keyring | 校验、目录、凭据库 | 各安装发行包的 dist-info/licenses |
| PyInstaller | 构建工具 | [官方许可与打包例外说明](https://pyinstaller.org/en/stable/license.html) |

当前主要发布物为 skill 源码 ZIP，只包含项目自有代码、说明和依赖声明；第三方 Python 依赖由安装脚本从包索引安装，不将 Qt 或第三方 wheel 放入 ZIP。相关依赖仍遵守各自许可。

历史桌面原型采用 onedir。若将来另行分发桌面二进制，还需基于实际构建收集第三方许可文本，检查 Qt 模块要求并提供相应材料；这不属于当前 skill 源码预览包。

当前没有分发系统字体；文档截图只在本机渲染时引用系统已安装字体。
