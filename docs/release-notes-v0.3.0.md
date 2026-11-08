Scopy Copilot 首个 Windows 便携发布版。

下载 **Scopy-Copilot-0.3.0-Windows-x64.zip**，完整解压后双击 **Scopy-Copilot.exe**。无需安装 Python，保留 ZIP 内全部目录。

已包含中文桌面浮窗、置顶/收起、模型设置、CD4007UBE 与门步骤与模拟判读，以及模型主动调用 Scopy 真实只读检查。真实供电和输出仍由程序锁定。

真实仪器检查需要另行安装 Scopy 和 ADALM2000 驱动，在 Scopy 内连接设备并启用 MCP。离线模拟无需设备或 API Key；自由对话需填入自己的模型 Key。

发布前62项自动测试通过。解压后的EXE在不使用Python PATH的环境下通过原生窗口、模拟/证据哈希、103项MCP工具发现及真实设备只读检查。

验证平台为 Windows 11 x64。本版未做代码签名；不要求管理员权限。尚不支持实际采样导出或使能供电/输出。

SHA256SUMS.txt 可校验便携包。GitHub 自动生成的 Source code 文件为源码，不是可运行应用。
