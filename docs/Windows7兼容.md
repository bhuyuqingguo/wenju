# Windows 7 兼容

结论：v3.3.0 的 Windows 便携包在 Windows 7 上启动失败，是因为 Python 3.13 硬链接了 `api-ms-win-core-path-l1-1-0.dll`。换成 Python 3.8 之后，Qt 6.10 仍会因 Windows 8 及以后的 API 集和 `kernel32` 导出而失败。Win10/11 包和麒麟包保持原样。Win7 SP1 x64 使用单独的便携包：Python 3.8.10 + PySide2 5.15.2.1（Qt 5.15.2）。

## v3.3.0 Windows 包里不能在 Win7 加载的部分

发行包 `WenJu_3.3.0_Windows_Portable.zip`（SHA256 `2a80716345f1883f9c04e9c44b1a43a956332918a39a1d714b61fa8e9c46ce7d`）是 Python 3.13 + PySide6 Essentials 6.10.3。对包内全部 PE 做导入表扫描后：

| 文件 | 硬导入 | 说明 |
| --- | --- | --- |
| `runtime/python313.dll` | `api-ms-win-core-path-l1-1-0.dll` | Windows 8 才有。这就是报错的那一个。 |
| 同上 | `CopyFile2`、`GetSystemTimePreciseAsFileTime` | `kernel32` 从 Windows 8 才导出。 |
| `PySide6/Qt6Core.dll` | `api-ms-win-core-synch-l1-2-0.dll`（`WaitOnAddress` 那一组） | Windows 8 才有。 |
| 同上 | `SetThreadDescription` | Windows 10 1607 才有。 |
| `plugins/platforms/qwindows.dll` | `api-ms-win-shcore-scaling-l1-1-1.dll`、`api-ms-win-core-winrt-*` | Windows 8 / 8.1。 |
| `vccorlib140.dll` | `api-ms-win-core-winrt-*` | 随 PySide6 带上，Windows 7 没有 WinRT。 |
| `vcruntime140.dll`、`libcrypto-3.dll`、`libssl-3.dll` | `api-ms-win-crt-*` | 包内没有通用 C 运行库。Windows 10 系统自带，Windows 7 需要 KB2999226 或随包附带。 |

OpenSSL 3（`libcrypto-3.dll` / `libssl-3.dll`）本身没有再引用 `bcryptprimitives.dll`。阻塞点仍是上面的 API 集和 CRT。

打包方式不是 PyInstaller 或 Nuitka，而是 embeddable Python 加一个 .NET 启动器。PyInstaller 6 和当前 Nuitka 也不支持 Windows 7，但这次的失败与它们无关。

官方支持边界：Python 3.9 起不支持 Windows 7；Qt 6 不支持 Windows 7；PySide6 6.10 的最低系统是 Windows 10。麒麟包的 Python 3.11 / PySide6 6.8.3 同样不能放到 Windows 7 上。

## Win7 包的取舍

界面是 Qt Quick / QML。Qt 6 写法（无版本号的 `import QtQuick`、`Basic` 样式、`ColorScheme`、`availableWidth`、`Set` 展开）只在 Win7 包里改写，源码里的 QML 仍给 PySide6 用。`qt_compat.py` 在有 PySide6 且未设置 `WENJU_QT=5` 时走原来的路径。

没有做 x86。v3.3.0 的 Windows 包是 x64，缺的 DLL 也不是 32 位问题。Win7 x86 需要另一套 Python 3.8 x86 和 PySide2 win32 轮子。

Win7 包启动器是原生程序，不依赖 .NET。Win10 的 C# 启动器没有改行为。

## 仍要满足的系统条件

- Windows 7 SP1 x64。
- 平台更新 KB2670838。`Qt5Gui.dll` 硬导入 `d3d11.dll!D3D11CreateDevice`。干净的 SP1 没有这个 DLL，装过平台更新的系统有。没有把它打进包里，避免盖住系统里真正的 Direct3D。
- 包内已有 `vcruntime140.dll`、`vcruntime140_1.dll`、`msvcp140.dll`、`ucrtbase.dll` 和 `api-ms-win-*` 转发库，放在 `runtime/`（`pythonw.exe` 旁边）。Windows 7 上这些转发库必须和进程 exe 在同一目录。不需要再装 VC++ 运行库。

显卡驱动太旧时用 `文矩.exe --safe-render`。

## 检查命令和结果

```text
python3 launcher/pe_imports.py dist/win7-stage/文矩
PE files: 140
No Windows 7 import violations.
```

同一脚本扫过 v3.3.0 的 Windows 包，会列出上面的 `api-ms-win-core-path-l1-1-0.dll`。Win7 包的 `python38.dll`、`Qt5Core.dll`、`qwindows.dll`、`libssl-1_1.dll` 没有该 DLL，也没有 `CopyFile2`、`GetSystemTimePreciseAsFileTime`、`SetThreadDescription`。`ucrtbase.dll` 引用的是随包附带的 downlevel API 集，实际转到的是 Windows 7 就有的函数（例如 `Sleep`、`MoveFileExW`、`GetTempPathW`）。

没有 Windows 7 虚拟机，也没有可用的系统安装镜像，所以没有在真机上启动界面。Wine 不能当作 Windows 7。

## 包

`dist/WenJu_3.3.0_Windows7_x64_Portable.zip`

SHA256：`a60f42e6efbd564c21babc1a4622295c78a667b82e3620037a6ebd541dc0da33`

整包一个 zip，约 63 MiB，2063 个文件。解压后双击 `文矩.exe`。
