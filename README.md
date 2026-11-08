# Scopy Copilot

面向 ADALM2000 模电实验的中文桌面浮窗助手，可置顶、收起，支持实验步骤、模拟波形判读，以及大模型主动检查 Scopy 真实状态。

## 下载使用

进入 [Releases](https://github.com/sunflower070203/Scopy-Copilot/releases/latest)，下载 `Scopy-Copilot-0.3.0-Windows-x64.zip`，**完整解压**后双击其中的 **Scopy-Copilot.exe**。

- Windows x64 便携应用，无需安装 Python 或运行安装命令。
- ZIP 内的 `_internal`、`bridge` 等目录必须保留，不能只取出 EXE。
- 离线教程和模拟无需 API Key，也无需接设备。
- 真实仪器检查需要另行安装 [Scopy](https://github.com/analogdevicesinc/scopy/releases) 及 ADALM2000 驱动，在 Scopy 中手动连接设备并开启 General → Enable the MCP server。
- 外部模型需在本机“模型设置”输入自己的 API Key，然后选择“外部模型 API”。默认地址 `https://api.deepseek.com`，模型 `deepseek-flash`；支持更换兼容接口和模型。

本次发布没有代码签名证书。应用不要求管理员权限，不会自动修改系统安全设置。

## 当前能做什么

| 功能 | 状态 |
|---|---|
| 中文原生浮窗、置顶/收起、模型设置 | 已实现 |
| CD4007UBE 与门步骤、正常/故障模拟、三路波形、真值覆盖 | 已实现 |
| 大模型主动调用 `check_scopy_readonly` 读取真实状态 | 已实现，曾完成真实 API → MCP → Scopy 实测 |
| V+/V−使能、V+设定值、DIO2输入、逻辑采样设置只读检查 | 已实现 |
| 实际供电、数字/波形输出使能 | **未开放，程序锁定** |
| 实际采样及原始逻辑波形导出 | 尚未实现 |

示例需求：

> 请读取 Scopy 当前真实状态，报告电源使能、DIO2 输入和逻辑采样设置，保持供电与输出不变。

模型提出结构化工具请求，本地控制层检查白名单、参数和取消状态，再经官方 Scopy MCP 执行。`get_status` 是缓存；`check_scopy_readonly` 每次重新检查并附时间。程序没有任意脚本、通用MCP调用或真实写操作入口。

照片和历史状态不能证明电气连通；电源设定值不是实测电压。模拟通过仅表示软件流程和模拟逻辑通过，不能作为实际电路验证。

## 数据与密钥

便携EXE将实验记录保存在 `%LOCALAPPDATA%\ScopyCopilot\data`，不写入解压目录。每次模拟保存 raw.csv、result.json、manifest.json（SHA256）；操作记录不含对话和密钥。

Key只保存在本次进程内存，关闭后需重新输入；更换API地址清除旧Key。对话、实验说明和必要工具回执会发送到你设置的供应商，原始波形留在本地。

“停止本地”取消本助手任务并锁定到手动恢复，不能代替Scopy关闭实际输出。断连/超时不会自动重连、重试写入或恢复输出。关闭助手不关闭Scopy。

## 开发与构建

Python 3.10+（构建已使用3.13），Tkinter。源码运行：

```powershell
py -3 desktop.py
```

源码模式的官方桥接准备与测试：

```powershell
py -3 scripts/setup_scopy.py
py -3 -m unittest discover -s tests -v
```

Windows发布构建（建议在独立虚拟环境中安装）：

```powershell
py -3 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.lock.txt
.\.venv-build\Scripts\python.exe scripts/build_windows.py
```

GUI和官方桥接分别冻结为EXE；构建会保留桥接来源、许可证、依赖清单和源码。见 [第三方说明](THIRD_PARTY_NOTICES.md)。原始资料、用户数据、Key和本机调试日志均不在公开仓库中。

## 验证范围

发布前执行参数边界、逻辑判读、密钥保护、模型工具往返、取消竞态、断连/超时、原生窗口和冻结路径测试，并从解压后的EXE验证离线模拟、官方MCP工具发现与真实只读读取。具体结果见 [发布验证记录](docs/release-verification.md)。

普通用户请下载Release资产，不要将GitHub自动生成的Source code压缩包当作应用安装包。
