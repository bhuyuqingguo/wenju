# Windows 7 兼容

GitHub 上的 3.4.1 Windows x64 包适用于 Win10/11。虽然启动器不依赖 .NET，包内的 Python 3.13 和 Qt 6 仍硬导入 Win7 没有的接口，例如 `api-ms-win-core-path-l1-1-0.dll`。不能把新系统包直接复制到 Win7，也不能靠安装 .NET 解决。

## Win7 x64 免安装测试版

- 目标系统是 Windows 7 SP1 x64。包内自带 Python 3.8.10、PySide2 5.15.2.1（Qt 5.15.2）、VC++ 和通用 C 运行库，不安装 Python、.NET 或系统组件。
- Win7 系统必须已经具备 KB2533623 或后续更新提供的安全 DLL 搜索接口。缺少接口时，原生启动器给出提示。装系统更新仍由电脑管理员处理。
- 软件渲染和低动效模式默认启用。Qt 5 仍有 Win7 自带的 Direct3D 11 和 DXGI 依赖；如果系统报图形组件错误，记录完整错误后再排查系统更新和显卡驱动。
- 一次性完整解压到固定、可写的目录，双击带图标的 **文矩.exe**。程序不会自动创建任务栏固定项。移动目录后，从新目录启动并重新固定；之前错误固定的旧项可手动取消固定。
- 测试版在较新的 Windows 上检查旧运行时启动和界面。Win7 实机的画面、任务栏固定并重启、单实例行为仍需现场验证。

## 构建

Windows 打包机需要 Python 3.11 或更新、PowerShell 7、Visual Studio C++ Build Tools 和 Windows SDK。将官方 Python 3.8.10 embeddable x64 解压到 `%LOCALAPPDATA%\WenjuBuild\win7\py38`，将 PySide2 和 shiboken2 5.15.2.1 的 x64 Windows wheels 放到同目录下的 `wheels`。可用 `WENJU_WIN7_CACHE` 指定其他缓存目录。

运行 `python launcher/package_win7.py`。构建检查原生入口图标和导入表，使用随包的 Python／Qt 打开窗口并选中模板，再校验中文 ZIP 文件名和文件完整性。导入表是静态检查，不能代替 Win7 真机测试。
